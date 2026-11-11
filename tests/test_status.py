"""P1-06 model-specific status diagnostics, queue semantics and safety gates."""

from __future__ import annotations

from datetime import timezone

import pytest

from dmm34411a import DMM_34411A, ScpiError, ErrorDrain, DiagnosticSnapshot
from scpi_driver_core import ConfigurationError, TransportTimeoutError
from scpi_driver_core.simulation import ScriptedReply, ScriptedScpiTransport


def fixture():
    return ScriptedScpiTransport(unknown_command_error=None).on(
        "*IDN?", "Agilent Technologies,34411A,MY_TEST_1,A.03.00"
    )


def snapshot_fixture():
    return (fixture()
        .on("*STB?", "32")
        .on("*ESE?", "255")
        .on("*SRE?", "48")
        .on("STATus:OPERation:CONDition?", "16")
        .on("STATus:OPERation:ENABle?", "512")
        .on("STATus:QUEStionable:CONDition?", "0")
        .on("STATus:QUEStionable:ENABle?", "8")
        .on("SYSTem:VERSion?", "1999.0")
        .on("ROUTe:TERMinals?", "FRON")
        .on("DATA:POINts? RDG_STORE", "123")
        .on("DATA:POINts? NVMEM", "4")
    )


def test_read_status_snapshot_no_event_or_error_dequeue():
    tr = snapshot_fixture().on("SYSTem:ERRor?", '-200,"Existing error"')
    with DMM_34411A(transport=tr) as dmm:
        data = dmm.diagnostics_snapshot()
        assert isinstance(data, DiagnosticSnapshot)
        assert data.manufacturer == "Agilent Technologies"
        assert data.model == "34411A"
        assert data.serial == "MY_TEST_1"
        assert data.firmware == "A.03.00"
        assert data.status_byte == 32
        assert data.operation.condition == 16
        assert data.questionable.enable == 8
        assert data.volatile_points is None
        assert data.nvm_points is None
        assert data.scpi_version == "1999.0"
        assert data.terminal_selection == "FRON"
        assert data.connected
        assert data.received_at_utc.tzinfo is timezone.utc
    assert tr.history == [
        "*IDN?", "*STB?", "*ESE?", "*SRE?",
        "STATus:OPERation:CONDition?", "STATus:OPERation:ENABle?",
        "STATus:QUEStionable:CONDition?", "STATus:QUEStionable:ENABle?",
        "SYSTem:VERSion?", "ROUTe:TERMinals?"
    ]
    assert not any(x in tr.history for x in (
        "SYSTem:ERRor?", "*ESR?", "*TST?", "*CLS",
        "STATus:OPERation:EVENt?", "STATus:QUEStionable:EVENt?",
    ))


def test_optional_memory_snapshot_query_only_no_delete():
    tr = snapshot_fixture()
    with DMM_34411A(transport=tr) as dmm:
        data = dmm.status.snapshot(include_memory=True, include_system=False)
        assert data.volatile_points == 123
        assert data.nvm_points == 4
        assert data.scpi_version is None
        assert data.terminal_selection is None
    assert tr.history[-2:] == ["DATA:POINts? RDG_STORE", "DATA:POINts? NVMEM"]
    assert "DATA:DELete NVMEM" not in tr.history


def test_scpi_errors_preserve_raw_quotes_commas():
    tr = fixture().on("SYSTem:ERRor?", '-221,"Settings conflict, no value"')
    with DMM_34411A(transport=tr) as dmm:
        value = dmm.get_error()
    assert isinstance(value, ScpiError)
    assert value.code == -221
    assert value.message == "Settings conflict, no value"
    assert value.raw == '-221,"Settings conflict, no value"'


def test_explicit_bounded_error_queue_drain():
    queue = ['-113,"Undefined header"', '-222,"Data out of range"', '0,"No error"']
    tr = fixture().on("SYSTem:ERRor?", lambda _: queue.pop(0))
    with DMM_34411A(transport=tr) as dmm:
        out = dmm.drain_errors(max_errors=5)
        assert isinstance(out, ErrorDrain)
        assert [item.code for item in out.errors] == [-113, -222]
        assert not out.exhausted
    assert tr.history.count("SYSTem:ERRor?") == 3


def test_bounded_drain_reports_unknown_remaining_queue():
    queue = ['-113,"A"', '-200,"B"', '-201,"C"']
    tr = fixture().on("SYSTem:ERRor?", lambda _: queue.pop(0))
    with DMM_34411A(transport=tr) as dmm:
        out = dmm.drain_errors(2)
        assert out.exhausted
        assert [e.message for e in out.errors] == ["A", "B"]
        assert queue == ['-201,"C"']
    assert tr.history.count("SYSTem:ERRor?") == 2


@pytest.mark.parametrize("invalid", [0, -1, 257, True, False, 2.0, "5"])
def test_invalid_queue_depth_no_query(invalid):
    tr = fixture()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.drain_errors(invalid)
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize("raw", [
    "", "foo", "a,b", "1,", '5,"unclosed', 'not-an-error',
    '-90000,"Out of range"', '0,"No error",5',
])
def test_malformed_error_reply_not_ignored(raw):
    tr = fixture().on("SYSTem:ERRor?", raw)
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ValueError):
            dmm.get_error()
    assert tr.history == ["*IDN?", "SYSTem:ERRor?"]


def test_status_register_read_write_and_read_to_clear_only_on_explicit_call():
    tr = (fixture()
          .on("*STB?", "33")
          .on("*ESE?", "1")
          .on("*SRE?", "16")
          .on("*ESR?", "64")
          .on("STATus:OPERation:CONDition?", "1024")
          .on("STATus:QUEStionable:ENABle?", "2048")
          .on("STATus:OPERation:EVENt?", "8"))
    with DMM_34411A(transport=tr) as dmm:
        s = dmm.status
        s.set_standard_event_enable(255)
        s.set_service_request_enable(48)
        s.set_enable("operation", 1234)
        s.set_enable("questionable", 0)
        assert s.standard_event_enable() == 1
        assert s.service_request_enable() == 16
        assert s.status_byte() == 33
        assert s.condition("operation") == 1024
        assert s.enable("questionable") == 2048
        assert s.standard_event_register() == 64
        assert s.event("operation") == 8
    assert tr.history == [
        "*IDN?", "*ESE 255", "*SRE 48",
        "STATus:OPERation:ENABle 1234", "STATus:QUEStionable:ENABle 0",
        "*ESE?", "*SRE?", "*STB?", "STATus:OPERation:CONDition?",
        "STATus:QUEStionable:ENABle?", "*ESR?", "STATus:OPERation:EVENt?",
    ]


@pytest.mark.parametrize("method,args", [
    ("set_standard_event_enable", (256,)),
    ("set_standard_event_enable", (True,)),
    ("set_service_request_enable", (64,)),
    ("set_service_request_enable", (999,)),
    ("set_enable", ("operation", -1)),
    ("set_enable", ("questionable", 32768)),
    ("set_enable", ("unknown", 1)),
    ("enable", ("unknown",)),
    ("condition", ("operaton",)),
    ("event", ("query?",)),
    ("snapshot", ()),
])
def test_unsafe_input_rejected_no_status_commands(method, args):
    tr = fixture()
    with DMM_34411A(transport=tr) as dmm:
        if method == "snapshot":
            with pytest.raises(ConfigurationError):
                dmm.status.snapshot(include_memory=1)
        else:
            with pytest.raises(ConfigurationError):
                getattr(dmm.status, method)(*args)
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize("raw", ["-1", "256", "1.5", "nan", "2;*RST", ""])
def test_status_byte_strict_parser(raw):
    tr = fixture().on("*STB?", raw)
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ValueError):
            dmm.status.status_byte()


def test_explicit_opc_with_bounded_timeout():
    tr = fixture().on("*OPC?", "1")
    with DMM_34411A(transport=tr) as dmm:
        assert dmm.status.operation_complete(timeout_s=2)
    assert tr.history == ["*IDN?", "*OPC?"]


def test_self_test_requires_confirm_and_invalidate_mode():
    tr = fixture().on("*TST?", "0")
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_dc_voltage()
        with pytest.raises(PermissionError):
            dmm.status.self_test()
        assert dmm.status.self_test(confirm=True, timeout_s=10) == 0
        with pytest.raises(RuntimeError):
            dmm.measurement.read()
    assert tr.history == ["*IDN?", "CONFigure:VOLTage:DC", "*TST?"]


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), True, "5"])
def test_opc_bad_deadline_has_no_query(bad):
    tr = fixture()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.status.operation_complete(timeout_s=bad)
    assert tr.history == ["*IDN?"]


def test_error_read_timeout_does_not_retry():
    tr = fixture().on(
        "SYSTem:ERRor?", ScriptedReply(
            raises=TransportTimeoutError("lost error queue reply"), disconnect=True
        )
    )
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(TransportTimeoutError):
            dmm.get_error()
    assert tr.history.count("SYSTem:ERRor?") == 1


def test_status_snapshot_is_not_alternative_to_hardware_self_test():
    tr = snapshot_fixture()
    with DMM_34411A(transport=tr) as dmm:
        assert dmm.status.snapshot().model == "34411A"
    assert "*TST?" not in tr.history
    assert "*CLS" not in tr.history
    assert "*RST" not in tr.history
