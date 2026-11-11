"""P0 safety regression: stale capture, uncertain writes, partial export retention."""

from __future__ import annotations

import hashlib
import json
import struct

import pytest

from dmm34411a import AcquisitionState, DMM_34411A, TransferUncertainError
from scpi_driver_core import TransportTimeoutError
from scpi_driver_core.simulation import ScriptedReply, ScriptedScpiTransport


def sim(*, volatile=3, nvm=0):
    state = {"volatile": volatile, "nvm": nvm}
    tr = ScriptedScpiTransport(unknown_command_error=None).on(
        "*IDN?", "Agilent,34411A,SIM,A.03.00"
    )
    tr.on("DATA:POINts? RDG_STORE", lambda _: str(state["volatile"]))
    tr.on("DATA:POINts? NVMEM", lambda _: str(state["nvm"]))
    tr.on("*OPC?", "1")
    return tr, state


def test_stale_readings_never_complete_unarmed_acquisition():
    tr, _ = sim(volatile=4)
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_volatile_acquisition(4)
        with pytest.raises(RuntimeError, match="INITiate"):
            dmm.acquisition.wait_complete(timeout_s=1.0)
        assert dmm.acquisition.state is AcquisitionState.CONFIGURED
    assert "DATA:POINts? RDG_STORE" not in tr.history
    assert "*OPC?" not in tr.history


def test_bus_trigger_requires_armed_state():
    tr, _ = sim(volatile=0)
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_volatile_acquisition(10, trigger_source="BUS")
        with pytest.raises(RuntimeError, match="armed"):
            dmm.send_bus_trigger()
        assert "*TRG" not in tr.history
        dmm.start_acquisition()
        dmm.send_bus_trigger()
    assert tr.history.count("INITiate") == 1
    assert tr.history.count("*TRG") == 1


def test_raw_scpi_invalidates_last_complete_run_before_nvm_copy():
    tr, _ = sim(volatile=3, nvm=0)
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_data_log(3)
        dmm.start_data_log()
        assert dmm.acquisition.wait_complete(timeout_s=1.0) == 3
        assert dmm.acquisition.state is AcquisitionState.COMPLETE
        dmm.cmd_write("TRIGger:DELay 0.1")
        assert dmm.acquisition.state is AcquisitionState.UNKNOWN
        with pytest.raises(RuntimeError):
            dmm.save_data_log()
    assert "DATA:COPY NVMEM, RDG_STORE" not in tr.history


def test_raw_query_may_mutate_and_invalidates_last_complete_run():
    tr, _ = sim(volatile=3, nvm=0)
    tr.on("READ?", "1.0")
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_data_log(3)
        dmm.start_data_log()
        dmm.acquisition.wait_complete(timeout_s=1.0)
        assert dmm.cmd_read() == "1.0"
        assert dmm.acquisition.state is AcquisitionState.UNKNOWN
        with pytest.raises(RuntimeError):
            dmm.save_data_log()
    assert "DATA:COPY NVMEM, RDG_STORE" not in tr.history


def test_copy_latch_prevents_reissue_after_ambiguous_completion():
    tr, state = sim(volatile=3, nvm=0)
    opc_queries = {"n": 0}
    def opc(_):
        opc_queries["n"] += 1
        return "0" if opc_queries["n"] == 3 else "1"
    # First OPC during wait, second pre-copy, third after DATA:COPY.
    tr.on("*OPC?", opc)
    tr.on("DATA:COPY NVMEM, RDG_STORE")
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_data_log(3)
        dmm.start_data_log()
        dmm.acquisition.wait_complete(timeout_s=1.0)
        with pytest.raises(RuntimeError, match="did not complete NVM copy"):
            dmm.save_data_log(timeout_ms=1000)
        with pytest.raises(RuntimeError, match="already attempted"):
            dmm.save_data_log(timeout_ms=1000)
    assert state["nvm"] == 0
    assert tr.history.count("DATA:COPY NVMEM, RDG_STORE") == 1


def test_copy_after_success_is_not_reissued():
    tr, state = sim(volatile=2, nvm=0)
    tr.on("DATA:COPY NVMEM, RDG_STORE", lambda _: state.update(nvm=2))
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_data_log(2)
        dmm.start_data_log()
        dmm.acquisition.wait_complete(timeout_s=1.0)
        assert dmm.save_data_log() == 2
        with pytest.raises(RuntimeError, match="already attempted"):
            dmm.save_data_log()
    assert tr.history.count("DATA:COPY NVMEM, RDG_STORE") == 1


def _stream_sim():
    state = {"values": [1.0, 2.0, 3.0, 4.0], "format": "ASC,9", "border": "SWAP"}
    tr = ScriptedScpiTransport(unknown_command_error=None).on(
        "*IDN?", "Agilent,34411A,SIM,A.03.00"
    )
    tr.on("DATA:POINts? RDG_STORE", lambda _: str(len(state["values"])))
    tr.on("FORMat:DATA?", lambda _: state["format"])
    tr.on("FORMat:BORDer?", lambda _: state["border"])
    tr.on_regex(r"^FORMat:DATA .+", lambda command: state.update(
        format=command.split(" ", 1)[1]
    ))
    tr.on_regex(r"^FORMat:BORDer .+", lambda command: state.update(
        border=command.split(" ", 1)[1]
    ))
    calls = {"n": 0}
    def remove(_command):
        calls["n"] += 1
        if calls["n"] == 2:
            return ScriptedReply(
                raises=TransportTimeoutError("second chunk timeout"), disconnect=True
            )
        values = state["values"][:2]
        del state["values"][:2]
        return tr.block(struct.pack(">2f", *values))
    tr.on("DATA:REMove? 2", remove)
    return tr, state


def test_partial_destructive_export_survives_second_chunk_failure(tmp_path):
    tr, state = _stream_sim()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(TransferUncertainError) as error:
            dmm.transfer.export_volatile_bundle(
                tmp_path / "new", destructive=True,
                max_points=4, chunk_size=2, precision_bits=32,
            )
        assert error.value.confirmed_removed == 2
        assert error.value.confirmed_csv_rows == 2
        partial = error.value.partial_directory
        assert partial.is_dir()
        meta = json.loads((partial / "metadata.json").read_text())
        assert meta["status"] == "INCOMPLETE"
        assert meta["confirmed_csv_rows"] == 2
        assert meta["current_chunk_outcome"] == "UNKNOWN"
        raw = (partial / "readings.csv").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == meta["readings_csv_sha256"]
        assert b"0,1.0,0" in raw and b"1,2.0,0" in raw
        assert dmm.acquisition.state is AcquisitionState.UNKNOWN
    assert state["values"] == [3.0, 4.0]
    assert not (tmp_path / "new").exists()
    assert tr.history.count("DATA:REMove? 2") == 2
    assert "DATA:DELete NVMEM" not in tr.history


def test_aborted_complete_run_cannot_write_nvm():
    tr, state = sim(volatile=3)
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_data_log(3)
        dmm.start_data_log()
        dmm.acquisition.wait_complete(timeout_s=1.0)
        dmm.abort_acquisition()
        with pytest.raises(RuntimeError):
            dmm.save_data_log()
    assert state["nvm"] == 0
    assert "DATA:COPY NVMEM, RDG_STORE" not in tr.history
