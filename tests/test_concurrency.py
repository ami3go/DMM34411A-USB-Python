"""P0 real-thread interleavings using scripted transport; never physical I/O."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from dmm34411a import AcquisitionState, DMM_34411A
from scpi_driver_core.simulation import ScriptedScpiTransport


def fake(*, count=0):
    return (ScriptedScpiTransport(unknown_command_error=None)
            .on("*IDN?", "Agilent,34411A,SIM,A.03.00")
            .on("DATA:POINts? RDG_STORE", str(count))
            .on("DATA:POINts? NVMEM", "0")
            .on("*OPC?", "1"))


def _hold_command(tr, command):
    entered, release = threading.Event(), threading.Event()
    def stop_here(_):
        entered.set()
        if not release.wait(timeout=3):
            raise AssertionError("test transport release timed out")
    tr.on(command, stop_here)
    return entered, release


def test_trigger_waits_for_in_flight_init_commit():
    tr = fake()
    entered, release = _hold_command(tr, "INITiate")
    with DMM_34411A(transport=tr) as meter:
        meter.configure_volatile_acquisition(10, trigger_source="BUS")
        with ThreadPoolExecutor(max_workers=2) as workers:
            started = workers.submit(meter.start_acquisition)
            assert entered.wait(2)
            triggered = workers.submit(meter.send_bus_trigger)
            release.set()
            started.result(timeout=3)
            triggered.result(timeout=3)
        assert meter.acquisition.state is AcquisitionState.ARMED
    assert tr.history.count("INITiate") == 1
    assert tr.history.count("*TRG") == 1
    assert tr.history.index("INITiate") < tr.history.index("*TRG")


def test_duplicate_parallel_init_does_not_reissue_command():
    tr = fake()
    entered, release = _hold_command(tr, "INITiate")
    with DMM_34411A(transport=tr) as meter:
        meter.configure_volatile_acquisition(5)
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(meter.start_acquisition)
            assert entered.wait(2)
            second = workers.submit(meter.start_acquisition)
            release.set()
            first.result(timeout=3)
            with pytest.raises(RuntimeError):
                second.result(timeout=3)
    assert tr.history.count("INITiate") == 1
    assert "ABORt" not in tr.history


def test_wait_is_woken_by_stop_without_waiting_for_long_poll():
    tr = fake(count=0)
    observed = threading.Event()
    def count_query(_):
        observed.set()
        return "0"
    tr.on("DATA:POINts? RDG_STORE", count_query)
    with DMM_34411A(transport=tr) as meter:
        meter.configure_volatile_acquisition(10, trigger_source="EXTERNAL")
        meter.start_acquisition()
        with ThreadPoolExecutor(max_workers=2) as workers:
            waited = workers.submit(
                meter.acquisition.wait_complete,
                timeout_s=30, poll_interval_s=10
            )
            assert observed.wait(2)
            t0 = time.monotonic()
            meter.abort_acquisition()
            with pytest.raises(InterruptedError):
                waited.result(timeout=3)
            assert time.monotonic() - t0 < 2
            assert meter.acquisition.state is AcquisitionState.ABORTED
    assert tr.history.count("ABORt") == 1
    assert "DATA:COPY NVMEM, RDG_STORE" not in tr.history


def test_abort_during_opc_never_commits_complete():
    tr = fake(count=3)
    entered, release = _hold_command(tr, "*OPC?")
    with DMM_34411A(transport=tr) as meter:
        meter.configure_volatile_acquisition(3)
        meter.start_acquisition()
        with ThreadPoolExecutor(max_workers=2) as workers:
            waiting = workers.submit(meter.acquisition.wait_complete, timeout_s=8)
            assert entered.wait(2)
            stopping = workers.submit(meter.abort_acquisition)
            # STOP request must be observable even while the client is busy.
            assert meter.acquisition._stop_requested.wait(timeout=2)
            release.set()
            with pytest.raises(InterruptedError):
                waiting.result(timeout=3)
            stopping.result(timeout=3)
            assert meter.acquisition.state is AcquisitionState.ABORTED
    assert tr.history.count("*OPC?") == 1
    assert tr.history.count("ABORt") == 1


def test_raw_scpi_command_cannot_interrupt_partial_trigger_configuration():
    tr = fake()
    entered, release = _hold_command(tr, "TRIGger:COUNt 1")
    with DMM_34411A(transport=tr) as meter:
        with ThreadPoolExecutor(max_workers=2) as workers:
            configured = workers.submit(meter.configure_volatile_acquisition, 10)
            assert entered.wait(2)
            raw = workers.submit(meter.cmd_write, "FORMat:DATA ASCii")
            release.set()
            assert configured.result(timeout=3) == 10
            raw.result(timeout=3)
        assert meter.acquisition.state is AcquisitionState.UNKNOWN
    assert tr.history.index("FORMat:DATA ASCii") > tr.history.index(
        "TRIGger:DELay:AUTO ON"
    )


def test_close_waits_for_inflight_initiate_and_does_not_abort():
    tr = fake()
    entered, release = _hold_command(tr, "INITiate")
    meter = DMM_34411A(transport=tr)
    meter.configure_volatile_acquisition(2)
    with ThreadPoolExecutor(max_workers=2) as workers:
        starting = workers.submit(meter.start_acquisition)
        assert entered.wait(2)
        closed = workers.submit(meter.close)
        release.set()
        starting.result(timeout=3)
        closed.result(timeout=3)
    assert meter.acquisition.state is AcquisitionState.IDLE
    assert not meter.session.is_connected
    assert "ABORt" not in tr.history


def test_two_parallel_nvm_copies_send_only_one_copy_command():
    tr = fake(count=3)
    copy_started, release = _hold_command(tr, "DATA:COPY NVMEM, RDG_STORE")
    # Simulate persistent count becoming 3 only after the copy completes.
    nvm = {"count": 0}
    def actual_copy(_):
        copy_started.set()
        if not release.wait(timeout=3):
            raise AssertionError("COPY release timed out")
        nvm["count"] = 3
    tr.on("DATA:COPY NVMEM, RDG_STORE", actual_copy)
    tr.on("DATA:POINts? NVMEM", lambda _: str(nvm["count"]))
    with DMM_34411A(transport=tr) as meter:
        meter.configure_data_log(3)
        meter.start_data_log()
        assert meter.acquisition.wait_complete(timeout_s=3) == 3
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(meter.save_data_log)
            assert copy_started.wait(2)
            second = workers.submit(meter.save_data_log)
            release.set()
            assert first.result(timeout=3) == 3
            with pytest.raises(RuntimeError, match="already attempted"):
                second.result(timeout=3)
    assert tr.history.count("DATA:COPY NVMEM, RDG_STORE") == 1
    assert tr.history.count("ABORt") == 0
