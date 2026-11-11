"""P1-04 34411A internal trigger, pretrigger, multi-event, lifecycle tests."""

from __future__ import annotations

from datetime import timezone

import pytest

from dmm34411a import DMM_34411A, AcquisitionState, MeasurementFunction as F
from scpi_driver_core import ConfigurationError, UnsupportedOperationError, TransportTimeoutError
from scpi_driver_core.simulation import ScriptedReply, ScriptedScpiTransport


def sim(idn="Agilent,34411A,TEST,1.0", *, points=0):
    return (
        ScriptedScpiTransport(unknown_command_error=None)
        .on("*IDN?", idn)
        .on("DATA:POINts? RDG_STORE", str(points))
        .on("DATA:POINts? NVMEM", "0")
        .on("*OPC?", "1")
    )


def test_advanced_internal_trigger_and_pretrigger_scpi_and_state():
    tr = sim(points=30)
    with DMM_34411A(transport=tr) as meter:
        meter.configure_dc_voltage()
        assert meter.configure_volatile_acquisition(
            10, trigger_source="INTERNAL", trigger_level=1.25,
            trigger_slope="NEG", pretrigger_count=2, trigger_count=3
        ) == 10
        assert meter.acquisition.state is AcquisitionState.CONFIGURED
        params = meter.acquisition.progress_snapshot()
        assert params.target == 30
        assert params.trigger_count == 3
        assert params.samples_per_trigger == 10
        assert params.pretrigger_count == 2
        assert params.observed_at_utc.tzinfo is timezone.utc
        meter.start_acquisition()
        assert meter.acquisition.state is AcquisitionState.ARMED
        assert meter.acquisition.wait_complete(timeout_s=2.0) == 30
        assert meter.acquisition.state is AcquisitionState.COMPLETE
    assert tr.history == [
        "*IDN?", "CONFigure:VOLTage:DC",
        "SAMPle:COUNt 10", "TRIGger:COUNt 3", "TRIGger:SOURce INTernal",
        "TRIGger:LEVel 1.25", "TRIGger:SLOPe NEG",
        "SAMPle:COUNt:PRETrigger 2", "SAMPle:SOURce AUTO",
        "TRIGger:DELay:AUTO ON", "DATA:POINts? RDG_STORE",
        "INITiate", "DATA:POINts? RDG_STORE", "*OPC?",
    ]


@pytest.mark.parametrize("mode", [F.FREQUENCY, F.PERIOD, F.CAPACITANCE, F.DIODE, F.CONTINUITY, F.TEMPERATURE])
def test_internal_trigger_invalid_measurement_mode_sends_no_trigger_commands(mode):
    tr = sim()
    with DMM_34411A(transport=tr) as meter:
        if mode is F.TEMPERATURE:
            from dmm34411a import TemperatureProbe
            meter.configure_temperature(TemperatureProbe.RTD_2W)
        else:
            meter.measurement.configure(__import__("dmm34411a").MeasurementConfig(mode))
        before = list(tr.history)
        with pytest.raises(UnsupportedOperationError):
            meter.configure_volatile_acquisition(
                10, trigger_source="INTERNAL", trigger_level=1.0
            )
    assert tr.history == before


def test_internal_trigger_requires_known_34411a_identity():
    tr = sim(idn="Agilent,34410A,TEST,1.0")
    with DMM_34411A(transport=tr) as meter:
        meter.configure_dc_voltage()
        with pytest.raises(UnsupportedOperationError):
            meter.configure_volatile_acquisition(
                20, trigger_source="INTERNAL", trigger_level=0.5
            )
        with pytest.raises(UnsupportedOperationError):
            meter.configure_volatile_acquisition(
                20, trigger_source="EXTERNAL", pretrigger_count=3
            )
    assert tr.history == ["*IDN?", "CONFigure:VOLTage:DC"]


@pytest.mark.parametrize("kwargs,err", [
    ({"trigger_count": 0}, ConfigurationError),
    ({"trigger_count": 1000001}, ConfigurationError),
    ({"trigger_count": True}, ConfigurationError),
    ({"trigger_count": 100001, "pretrigger_count": 2}, ConfigurationError),
    ({"pretrigger_count": -1}, ConfigurationError),
    ({"pretrigger_count": 10}, ConfigurationError),
    ({"pretrigger_count": True}, ConfigurationError),
    ({"pretrigger_count": 2}, UnsupportedOperationError),  # IMMediate no useful event
    ({"trigger_source": "INTERNAL"}, ConfigurationError),
    ({"trigger_source": "BUS", "trigger_level": 1.0}, ConfigurationError),
    ({"trigger_source": "BAD"}, ConfigurationError),
    ({"trigger_delay_seconds": 3600.0001}, ConfigurationError),
    ({"trigger_slope": "POS;*RST"}, ConfigurationError),
])
def test_invalid_advanced_config_issues_no_scpi(kwargs, err):
    tr = sim()
    with DMM_34411A(transport=tr) as meter:
        meter.configure_dc_voltage()
        history = list(tr.history)
        with pytest.raises(err):
            meter.configure_volatile_acquisition(10, **kwargs)
    assert tr.history == history


def test_total_samples_respects_nvm_capacity():
    tr = sim()
    with DMM_34411A(transport=tr) as meter:
        meter.configure_dc_voltage()
        with pytest.raises(ConfigurationError):
            meter.configure_data_log(5000, trigger_count=11)
    assert tr.history == ["*IDN?", "CONFigure:VOLTage:DC"]


def test_set_level_trigger_after_configuration_with_readback():
    tr = sim().on("TRIGger:SOURce?", "INT").on(
        "TRIGger:COUNt?", "1"
    ).on("SAMPle:COUNt?", "10").on("SAMPle:COUNt:PRETrigger?", "0")
    with DMM_34411A(transport=tr) as meter:
        meter.configure_ac_voltage()
        meter.configure_volatile_acquisition(10, trigger_source="BUS")
        meter.acquisition.set_level_trigger(1.5, slope="POS")
        assert meter.acquisition.trigger_settings_raw() == {
            "source": "INT", "trigger_count": "1",
            "sample_count": "10", "pretrigger_count": "0"
        }
        assert meter.acquisition.state is AcquisitionState.CONFIGURED
        assert meter.acquisition.progress_snapshot().trigger_source == "INTernal"
    assert tr.history.count("TRIGger:LEVel 1.5") == 1
    assert tr.history.count("TRIGger:SOURce INTernal") == 1
    assert "ABORt" not in tr.history


def test_armed_acquisition_blocks_reconfigure_and_trigger_output():
    tr = sim()
    with DMM_34411A(transport=tr) as meter:
        meter.configure_dc_voltage()
        meter.configure_volatile_acquisition(5, trigger_source="BUS")
        meter.start_acquisition()
        with pytest.raises(RuntimeError):
            meter.configure_volatile_acquisition(10)
        with pytest.raises(RuntimeError):
            meter.acquisition.set_trigger_output_slope("POS")
        meter.abort_acquisition()
        assert meter.acquisition.state is AcquisitionState.ABORTED
        meter.acquisition.set_trigger_output_slope("NEG")
    assert tr.history[-2:] == ["ABORt", "OUTPut:TRIGger:SLOPe NEG"]


def test_explicit_abort_returns_partial_metadata():
    tr = sim(points=3)
    with DMM_34411A(transport=tr) as meter:
        meter.configure_volatile_acquisition(10)
        meter.start_acquisition()
        part = meter.acquisition.abort_and_snapshot()
        assert part.acquired == 3
        assert part.target == 10
        assert part.state is AcquisitionState.ABORTED
        assert meter.acquisition.state is AcquisitionState.ABORTED
    assert tr.history.count("ABORt") == 1


def test_untriggered_timeout_is_bounded_and_leaves_unknown_state():
    tr = sim(points=0)
    with DMM_34411A(transport=tr) as meter:
        meter.configure_volatile_acquisition(5, trigger_source="EXTERNAL")
        meter.start_acquisition()
        with pytest.raises(TimeoutError):
            meter.acquisition.wait_complete(timeout_s=0.005, poll_interval_s=0.001)
        assert meter.acquisition.state is AcquisitionState.UNKNOWN
        with pytest.raises(RuntimeError):
            meter.configure_volatile_acquisition(4)
        meter.abort_acquisition()
        assert meter.acquisition.state is AcquisitionState.ABORTED
        meter.configure_volatile_acquisition(4)
    assert tr.history.count("ABORt") == 1
    assert "DATA:DELete NVMEM" not in tr.history


def test_opc_timeout_does_not_retry_and_marks_unknown():
    tr = sim(points=4).on("*OPC?", ScriptedReply(
        raises=TransportTimeoutError("device still busy"), disconnect=True
    ))
    with DMM_34411A(transport=tr) as meter:
        meter.configure_volatile_acquisition(4)
        meter.start_acquisition()
        with pytest.raises(TransportTimeoutError):
            meter.acquisition.wait_complete(timeout_s=2.0)
        assert meter.acquisition.state is AcquisitionState.UNKNOWN
    assert tr.history.count("*OPC?") == 1
    assert "ABORt" not in tr.history


def test_close_resets_local_state_without_issuing_abort():
    tr = sim()
    meter = DMM_34411A(transport=tr)
    meter.configure_volatile_acquisition(5)
    meter.start_acquisition()
    meter.close()
    assert meter.acquisition.state is AcquisitionState.IDLE
    assert "ABORt" not in tr.history



def test_pretrigger_is_reset_on_next_configuration():
    tr = sim(points=0)
    with DMM_34411A(transport=tr) as meter:
        meter.configure_dc_voltage()
        meter.configure_volatile_acquisition(
            8, trigger_source="EXTERNAL", pretrigger_count=2
        )
        meter.configure_volatile_acquisition(8, trigger_source="IMMEDIATE")
        assert meter.acquisition.progress_snapshot().pretrigger_count == 0
    assert tr.history.count("SAMPle:COUNt:PRETrigger 2") == 1
    assert tr.history.count("SAMPle:COUNt:PRETrigger 0") == 1
