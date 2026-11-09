"""Deterministic public-API tests using scpi-driver-core's scripted transport."""

from __future__ import annotations

import pytest

from dmm34411a import DMM_34411A
from scpi_driver_core import ConfigurationError, TransportTimeoutError, UnsupportedOperationError
from scpi_driver_core.simulation import ScriptedReply, ScriptedScpiTransport
from scpi_driver_core.transport import TransportState

IDN = "Agilent Technologies,34411A,MY48001027,A.03.00"


def simulator() -> ScriptedScpiTransport:
    return ScriptedScpiTransport(unknown_command_error=None).on("*IDN?", IDN)


@pytest.mark.parametrize(
    ("method", "command"),
    [
        ("conf_voltage_dc", ":CONFigure:VOLTage:DC: AUTO"),
        ("conf_resistane_4wire", ":CONFigure:FRESistance AUTO, MIN"),
        ("conf_resistane_2wire", ":CONFigure:RESistance AUTO, MIN"),
        ("conf_current_dc", ":CONFigure:CURRent:DC: AUTO"),
    ],
)
def test_legacy_configuration_commands(method: str, command: str) -> None:
    transport = simulator().on(command)
    with DMM_34411A(transport=transport) as meter:
        getattr(meter, method)()
        assert meter.idn == IDN
    assert transport.history == ["*IDN?", command]
    assert transport.state is TransportState.CLOSED


@pytest.mark.parametrize(
    ("method", "command"),
    [
        ("cmd_read", "READ?"),
        ("measure_voltage", "MEASure:VOLTage:DC? AUTO"),
        ("measure_resistnce_4wire", "MEASure:FRESistance? AUTO"),
        ("measure_resistnce_2wire", "MEASure:RESistance? AUTO"),
        ("measure_current_dc", "MEASure:CURRent:DC? AUTO ,MAX"),
    ],
)
def test_legacy_measurements_return_strings(method: str, command: str) -> None:
    transport = simulator().on(command, "+1.250000E+00")
    with DMM_34411A(transport=transport) as meter:
        result = getattr(meter, method)()
    assert isinstance(result, str)
    assert result == "+1.250000E+00"
    assert transport.history == ["*IDN?", command]


def test_raw_write_and_query_through_shared_client() -> None:
    transport = simulator().on("*CLS").on("SYST:ERR?", '0,"No error"')
    with DMM_34411A(transport=transport) as meter:
        meter.cmd_write("*CLS")
        assert meter.cmd_query("SYST:ERR?") == '0,"No error"'
    assert transport.history == ["*IDN?", "*CLS", "SYST:ERR?"]


def test_open_close_idempotent_without_implicit_device_clear() -> None:
    transport = simulator()
    meter = DMM_34411A(transport=transport, auto_open=False)
    assert transport.state is TransportState.CREATED
    meter.open()
    meter.open()
    assert transport.history == ["*IDN?"]
    meter.close()
    meter.close()
    assert transport.state is TransportState.CLOSED
    assert meter.idn is None
    assert transport.history == ["*IDN?"]


def test_reopen_after_explicit_close() -> None:
    transport = simulator()
    meter = DMM_34411A(transport=transport)
    first_generation = meter.session.generation
    meter.close()
    meter.open()
    assert meter.session.generation == first_generation + 1
    assert meter.idn == IDN
    assert transport.history == ["*IDN?", "*IDN?"]
    meter.close()


def test_query_timeout_is_not_retried_or_hidden() -> None:
    transport = simulator().on(
        "READ?",
        ScriptedReply(raises=TransportTimeoutError("simulated timeout"), disconnect=True),
    )
    with DMM_34411A(transport=transport) as meter:
        with pytest.raises(TransportTimeoutError):
            meter.cmd_read()
        assert meter.session.is_connected is False
        assert transport.state is TransportState.FAULTED
        assert transport.history.count("READ?") == 1


def test_initial_identity_failure_closes_session() -> None:
    transport = ScriptedScpiTransport().on(
        "*IDN?",
        ScriptedReply(raises=TransportTimeoutError("probe failed"), disconnect=True),
    )
    with pytest.raises(TransportTimeoutError):
        DMM_34411A(transport=transport)
    assert transport.state is TransportState.CLOSED


def test_explicit_device_clear_is_not_generic_scpi_write() -> None:
    transport = simulator()
    with DMM_34411A(transport=transport) as meter:
        with pytest.raises(UnsupportedOperationError):
            meter.device_clear()
    assert transport.history == ["*IDN?"]


def test_timeout_validation_before_hardware_open() -> None:
    with pytest.raises(ConfigurationError):
        DMM_34411A(transport=simulator(), timeout_s=0, auto_open=False)


def test_legacy_checkout_import_path() -> None:
    from src.DMM34411A_class import DMM_34411A as LegacyClass

    assert LegacyClass is DMM_34411A
