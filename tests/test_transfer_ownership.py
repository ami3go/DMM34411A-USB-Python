"""P0 transfer serialization and cancellation: real threads, fake transport."""

from __future__ import annotations

import struct
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from dmm34411a import AcquisitionState, DMM_34411A
from scpi_driver_core.simulation import ScriptedScpiTransport


def sim(values=(1., 2., 3., 4.)):
    state = {"values": list(values), "format": "ASC,9", "border": "SWAP"}
    tr = ScriptedScpiTransport(unknown_command_error=None).on(
        "*IDN?", "Agilent,34411A,SIM,A.03.00"
    )
    tr.on("DATA:POINts? RDG_STORE", lambda _: str(len(state["values"])))
    tr.on("FORMat:DATA?", lambda _: state["format"])
    tr.on("FORMat:BORDer?", lambda _: state["border"])
    tr.on_regex(r"^FORMat:DATA .+", lambda cmd: state.update(
        format=cmd.split(" ", 1)[1]
    ))
    tr.on_regex(r"^FORMat:BORDer .+", lambda cmd: state.update(
        border=cmd.split(" ", 1)[1]
    ))
    tr.on("SYSTem:VERSion?", "1999.0")
    tr.on("FETCh?", lambda _: tr.block(
        b"".join(struct.pack(">f" if state["format"].endswith("32") else ">d", value)
                 for value in state["values"])
    ))

    def remove(command):
        n = int(command.split(" ")[-1])
        data = state["values"][:n]
        del state["values"][:n]
        return tr.block(b"".join(
            struct.pack(">f" if state["format"].endswith("32") else ">d", x) for x in data
        ))
    tr.on_regex(r"^DATA:REMove\? \d+$", remove)
    return tr, state


def test_fetch_format_lease_blocks_raw_commands_until_restored():
    tr, state = sim()
    started, release = threading.Event(), threading.Event()
    def fetch(_):
        started.set()
        assert release.wait(3)
        return tr.block(b"".join(struct.pack(">f", x) for x in state["values"]))
    tr.on("FETCh?", fetch)
    with DMM_34411A(transport=tr) as dmm:
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = pool.submit(dmm.fetch_volatile_binary)
            assert started.wait(2)
            query = pool.submit(dmm.cmd_query, "SYSTem:VERSion?")
            release.set()
            assert result.result(timeout=3).samples == 4
            assert query.result(timeout=3) == "1999.0"
    assert tr.history.index("FORMat:DATA ASC,9") < tr.history.index("SYSTem:VERSion?")
    assert state["format"] == "ASC,9" and state["border"] == "SWAP"


def test_destructive_stream_holds_lock_even_while_chunk_is_yielded():
    tr, state = sim()
    with DMM_34411A(transport=tr) as dmm:
        with closing(dmm.transfer.iter_destructive_chunks(
            max_points=4, chunk_size=2
        )) as stream:
            first = next(stream)
            assert first.readings == (1., 2.)
            begun, finished = threading.Event(), threading.Event()
            def query_other_thread():
                begun.set()
                try:
                    return dmm.cmd_query("SYSTem:VERSion?")
                finally:
                    finished.set()
            with ThreadPoolExecutor(max_workers=1) as pool:
                late = pool.submit(query_other_thread)
                assert begun.wait(2)
                assert not finished.wait(0.1)
                second = next(stream)
                assert second.readings == (3., 4.)
                with pytest.raises(StopIteration):
                    next(stream)
                assert late.result(timeout=3) == "1999.0"
    assert state["values"] == []
    assert tr.history.index("FORMat:DATA ASC,9") < tr.history.index("SYSTem:VERSion?")


def test_manual_cancel_between_destructive_chunks_never_replays():
    tr, state = sim()
    with DMM_34411A(transport=tr) as dmm:
        with closing(dmm.transfer.iter_destructive_chunks(
            max_points=4, chunk_size=2
        )) as stream:
            assert next(stream).readings == (1., 2.)
            dmm.transfer.request_cancel()
            with pytest.raises(InterruptedError, match="2 confirmed"):
                next(stream)
        assert dmm.acquisition.state is AcquisitionState.UNKNOWN
    assert state["values"] == [3., 4.]
    assert tr.history.count("DATA:REMove? 2") == 1
    assert state["format"] == "ASC,9"


def test_explicit_abort_signals_then_stream_releases_lock():
    tr, state = sim()
    with DMM_34411A(transport=tr) as dmm:
        with closing(dmm.transfer.iter_destructive_chunks(
            max_points=4, chunk_size=2
        )) as stream:
            assert next(stream).first_index == 0
            with ThreadPoolExecutor(max_workers=1) as pool:
                stopping = pool.submit(dmm.abort_acquisition)
                assert dmm.transfer._cancel_requested.wait(2)
                with pytest.raises(InterruptedError):
                    next(stream)
                stopping.result(timeout=3)
            assert dmm.acquisition.state is AcquisitionState.ABORTED
    assert tr.history.count("DATA:REMove? 2") == 1
    assert tr.history.count("ABORt") == 1
    assert state["values"] == [3., 4.]


def test_abandoned_stream_close_marks_partial_state_unknown():
    tr, state = sim()
    with DMM_34411A(transport=tr) as dmm:
        stream = dmm.transfer.iter_destructive_chunks(max_points=4, chunk_size=2)
        assert next(stream).readings == (1., 2.)
        stream.close()
        assert dmm.acquisition.state is AcquisitionState.UNKNOWN
        assert dmm.transfer._active_transfer is False
    assert state["format"] == "ASC,9"
    assert state["values"] == [3., 4.]


def test_nested_fetch_during_open_stream_rejected_without_scpi():
    tr, _ = sim()
    with DMM_34411A(transport=tr) as dmm:
        with closing(dmm.transfer.iter_destructive_chunks(
            max_points=4, chunk_size=2
        )) as stream:
            next(stream)
            n = tr.history.count("FETCh?")
            with pytest.raises(RuntimeError, match="nested"):
                dmm.fetch_volatile_binary()
            assert tr.history.count("FETCh?") == n


def test_cancelled_fetch_returns_no_partial_payload_and_restores_format():
    tr, state = sim()
    dmm = DMM_34411A(transport=tr)
    def fetch(_):
        dmm.transfer.request_cancel()
        return tr.block(b"".join(struct.pack(">f", x) for x in state["values"]))
    tr.on("FETCh?", fetch)
    with dmm:
        with pytest.raises(InterruptedError):
            dmm.fetch_volatile_binary()
        assert dmm.acquisition.state is AcquisitionState.UNKNOWN
    assert state["format"] == "ASC,9"
    assert state["border"] == "SWAP"
    assert tr.history.count("FETCh?") == 1
