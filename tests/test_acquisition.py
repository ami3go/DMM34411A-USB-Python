"""Core-backed 34411A volatile acquisition and guarded nonvolatile storage.

Hardware-free tests exercise ordering, preservation, limits and uncertain I/O.
"""

from __future__ import annotations

import math

import pytest

from dmm34411a import DMM_34411A, NONVOLATILE_MEMORY_POINTS, VOLATILE_MEMORY_POINTS
from scpi_driver_core import ConfigurationError, TransportTimeoutError, UnsupportedOperationError
from scpi_driver_core.simulation import ScriptedReply, ScriptedScpiTransport
from scpi_driver_core.transport import TransportState


def meter_simulator(*, volatile: int = 0, nvm: int = 0, format_reply: str = "ASC"):
    state = {"volatile": volatile, "nvm": nvm}

    def copy(_command):
        state["nvm"] = state["volatile"]

    def delete(_command):
        state["nvm"] = 0

    transport = ScriptedScpiTransport(unknown_command_error=None)
    transport.on("*IDN?", "Agilent,34411A,SIM,1.0")
    transport.on("DATA:POINts? RDG_STORE", lambda _: str(state["volatile"]))
    transport.on("DATA:POINts? NVMEM", lambda _: str(state["nvm"]))
    transport.on("*OPC?", "1")
    transport.on("FORMat:DATA?", format_reply)
    transport.on("DATA:COPY NVMEM, RDG_STORE", copy)
    transport.on("DATA:DELete NVMEM", delete)
    transport.on("DATA:DATA? NVMEM", "1.0,2.0,3.0")
    transport.on("FETCh?", "1.0,2.0,3.0")
    transport.on("DATA:REMove? 2", "1.0,2.0")
    return transport, state


def test_memory_capacities_exported():
    assert VOLATILE_MEMORY_POINTS == 1_000_000
    assert NONVOLATILE_MEMORY_POINTS == 50_000


def test_configuration_is_core_serialized_and_not_destructive():
    transport, _ = meter_simulator()
    with DMM_34411A(transport=transport) as dmm:
        assert dmm.configure_volatile_acquisition(
            1000, sample_interval_seconds=0.005, trigger_source="BUS",
            trigger_delay_seconds=0,
        ) == 1000
        with pytest.raises(RuntimeError):
            dmm.send_bus_trigger()
        dmm.start_acquisition()
        dmm.send_bus_trigger()
    assert transport.history == [
        "*IDN?", "SAMPle:COUNt 1000", "TRIGger:COUNt 1",
        "TRIGger:SOURce BUS", "SAMPle:SOURce TIMer", "SAMPle:TIMer 0.005",
        "TRIGger:DELay:AUTO OFF", "TRIGger:DELay 0", "INITiate", "*TRG",
    ]


@pytest.mark.parametrize(
    ("points", "persist"),
    [(0, False), (-1, False), (True, False), (1.0, False),
     (1_000_001, False), (50_001, True), (False, True)],
)
def test_count_validation_before_instrument_write(points, persist):
    transport, _ = meter_simulator()
    with DMM_34411A(transport=transport) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.acquisition.configure(points, persist=persist)
    assert transport.history == ["*IDN?"]


@pytest.mark.parametrize("interval", [0, -1, math.inf, math.nan, True])
def test_sample_interval_rejected_before_instrument_write(interval):
    transport, _ = meter_simulator()
    with DMM_34411A(transport=transport) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.configure_data_log(10, sample_interval_seconds=interval)
    assert transport.history == ["*IDN?"]


def test_preserves_existing_nvm_on_default_start():
    transport, state = meter_simulator(nvm=4)
    with DMM_34411A(transport=transport) as dmm:
        dmm.configure_data_log(3)
        with pytest.raises(FileExistsError):
            dmm.start_data_log()
        with pytest.raises(PermissionError):
            dmm.start_data_log(clear_existing=True)
        assert dmm.nonvolatile_point_count() == 4
    assert state["nvm"] == 4
    assert "INITiate" not in transport.history
    assert "DATA:DELete NVMEM" not in transport.history


def test_explicit_delete_requires_confirmation_and_verifies_empty():
    transport, state = meter_simulator(nvm=3)
    with DMM_34411A(transport=transport) as dmm:
        with pytest.raises(PermissionError):
            dmm.delete_data_log()
        assert state["nvm"] == 3
        dmm.delete_data_log(confirm=True)
        assert dmm.nonvolatile_point_count() == 0
    assert transport.history.count("DATA:DELete NVMEM") == 1


def test_safe_acquire_copy_to_empty_nvm_and_readback():
    transport, state = meter_simulator(volatile=3, nvm=0)
    with DMM_34411A(transport=transport) as dmm:
        assert dmm.configure_data_log(3, sample_interval_seconds=0.01) == 3
        dmm.start_data_log()
        assert dmm.data_log_progress() == {"acquired": 3, "target": 3, "complete": True}
        assert dmm.wait_for_data_log(timeout_seconds=2.0) == 3
        assert dmm.read_data_log() == [1.0, 2.0, 3.0]
        assert dmm.nonvolatile_point_count() == 3
    assert state["nvm"] == 3
    assert transport.history.count("DATA:COPY NVMEM, RDG_STORE") == 1
    assert "DATA:DELete NVMEM" not in transport.history
    assert "ABORt" not in transport.history


def test_copy_rejects_untested_overwrite_even_when_requested():
    transport, state = meter_simulator(volatile=3, nvm=0)
    with DMM_34411A(transport=transport) as dmm:
        dmm.configure_data_log(3)
        dmm.start_data_log()
        dmm.acquisition.wait_complete(timeout_s=2)
        state["nvm"] = 2
        with pytest.raises(FileExistsError):
            dmm.save_data_log()
        with pytest.raises(UnsupportedOperationError):
            dmm.acquisition.copy_to_nvm(overwrite=True)
    assert state["nvm"] == 2
    assert "DATA:COPY NVMEM, RDG_STORE" not in transport.history


def test_volatile_fetch_retained_and_destructive_removal_is_explicit():
    transport, state = meter_simulator(volatile=3)
    with DMM_34411A(transport=transport) as dmm:
        assert dmm.read_volatile_readings() == [1.0, 2.0, 3.0]
        with pytest.raises(ConfigurationError):
            dmm.read_volatile_readings(erase=True)
        with pytest.raises(ConfigurationError):
            dmm.read_volatile_readings(max_points=2)
        assert dmm.read_volatile_readings(erase=True, max_points=2) == [1.0, 2.0]
        assert state["nvm"] == 0
    assert "FETCh?" in transport.history
    assert transport.history.count("DATA:REMove? 2") == 1


def test_restore_original_response_format_after_nvm_read():
    transport, _ = meter_simulator(nvm=3, format_reply="REAL,64")
    with DMM_34411A(transport=transport) as dmm:
        assert dmm.read_data_log() == [1.0, 2.0, 3.0]
    assert transport.history.index("FORMat:DATA ASCii") < transport.history.index("DATA:DATA? NVMEM")
    assert transport.history[-2:] == ["FORMat:DATA REAL,64", "DATA:POINts? NVMEM"]


def test_copy_timeout_is_not_retried_and_invalidates_transport():
    transport, _ = meter_simulator(volatile=3, nvm=0)
    transport.on("*OPC?", ScriptedReply(
        raises=TransportTimeoutError("NVM completion unknown"), disconnect=True
    ))
    with DMM_34411A(transport=transport) as dmm:
        dmm.configure_data_log(3)
        dmm.start_data_log()
        # A count check alone must not allow copying.
        with pytest.raises(RuntimeError):
            dmm.save_data_log()
    assert "DATA:COPY NVMEM, RDG_STORE" not in transport.history


def test_malformed_count_and_large_nondestructive_fetch_refused():
    max_big = 100_000
    transport, state = meter_simulator(volatile=max_big)
    with DMM_34411A(transport=transport) as dmm:
        with pytest.raises(ValueError):
            dmm.read_volatile_readings()
        assert dmm.volatile_point_count() == max_big
    state["volatile"] = 0


def test_no_reuse_of_acquisition_state_after_close():
    transport, _ = meter_simulator(volatile=3)
    dmm = DMM_34411A(transport=transport)
    dmm.configure_volatile_acquisition(3)
    dmm.close()
    dmm.open()
    with pytest.raises(RuntimeError):
        dmm.start_acquisition()
    dmm.close()


def test_no_copy_when_acquisition_incomplete():
    transport, _ = meter_simulator(volatile=1)
    with DMM_34411A(transport=transport) as dmm:
        dmm.configure_data_log(3)
        dmm.start_data_log()
        with pytest.raises(RuntimeError):
            dmm.save_data_log()
    assert "DATA:COPY NVMEM, RDG_STORE" not in transport.history
