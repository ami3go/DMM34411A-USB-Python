"""P1-05 bounded IEEE binary transfer and atomic export, hardware-free."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import struct
from contextlib import closing

import pytest

from dmm34411a import (
    DMM_34411A, AcquisitionState, BinaryCapture, TransferUncertainError,
)
from dmm34411a.transfer import decode_readings
from scpi_driver_core import ConfigurationError, TransportTimeoutError
from scpi_driver_core.simulation import ScriptedReply, ScriptedScpiTransport
from scpi_driver_core.transport import TransportState


def binary_sim(values=(1., 2., 3.), *, format_value="ASC,9", border="SWAP"):
    state = {"values": list(values), "format": format_value, "border": border}
    tr = ScriptedScpiTransport(unknown_command_error=None)
    tr.on("*IDN?", "Agilent Technologies,34411A,TEST,A.03.00")
    tr.on("DATA:POINts? RDG_STORE", lambda _: str(len(state["values"])))
    tr.on("FORMat:DATA?", lambda _: state["format"])
    tr.on("FORMat:BORDer?", lambda _: state["border"])

    def select_format(command):
        state["format"] = command.split(" ", 1)[1]

    def select_border(command):
        state["border"] = command.split(" ", 1)[1]

    tr.on_regex(r"^FORMat:DATA .+$", select_format)
    tr.on_regex(r"^FORMat:BORDer .+$", select_border)

    def payload(data):
        width = 32 if state["format"].upper().endswith("32") else 64
        fmt = ">f" if width == 32 else ">d"
        return tr.block(b"".join(struct.pack(fmt, v) for v in data))

    tr.on("FETCh?", lambda _: payload(state["values"]))

    def remove(command):
        take = int(command.rsplit(" ", 1)[1])
        popped = state["values"][:take]
        del state["values"][:take]
        return payload(popped)

    tr.on_regex(r"^DATA:REMove\? \d+$", remove)
    return tr, state


def test_core_binary_fetch_nondestructive_and_restores_settings():
    tr, state = binary_sim([1.25, -2.0, 3.125])
    with DMM_34411A(transport=tr) as dmm:
        result = dmm.transfer.fetch_volatile_binary(precision_bits=32)
        assert isinstance(result, BinaryCapture)
        assert result.samples == 3
        assert result.precision_bits == 32
        assert result.source.startswith("FETCh?")
        assert list(result.readings()) == pytest.approx([1.25, -2., 3.125])
    assert state["values"] == [1.25, -2., 3.125]
    assert state["format"] == "ASC,9"
    assert state["border"] == "SWAP"
    assert tr.history.count("FETCh?") == 1
    assert "DATA:REMove? 3" not in tr.history
    assert "DATA:DELete NVMEM" not in tr.history
    assert "FORMat:DATA REAL,32" in tr.history
    assert "FORMat:BORDer NORMal" in tr.history


@pytest.mark.parametrize("bits", [32, 64])
def test_binary_ieee32_64_and_big_endian(bits):
    tr, _ = binary_sim([1.125, -99.5])
    with DMM_34411A(transport=tr) as dmm:
        capture = dmm.transfer.fetch_volatile_binary(precision_bits=bits)
        assert capture.payload == struct.pack(">2f" if bits == 32 else ">2d", 1.125, -99.5)
        assert list(capture.readings()) == [1.125, -99.5]


def test_empty_buffer_does_not_modify_format():
    tr, state = binary_sim([])
    with DMM_34411A(transport=tr) as dmm:
        capture = dmm.transfer.fetch_volatile_binary()
        assert capture == BinaryCapture(0, 32, b"")
    assert tr.history == ["*IDN?", "DATA:POINts? RDG_STORE"]
    assert state["format"] == "ASC,9"


def test_destructive_chunked_read_decrements_verified_count():
    tr, state = binary_sim([0., 1., 2., 3., 4.])
    with DMM_34411A(transport=tr) as dmm:
        with closing(dmm.transfer.iter_destructive_chunks(
            max_points=5, chunk_size=2, precision_bits=64
        )) as source:
            rows = list(source)
        assert [len(r.readings) for r in rows] == [2, 2, 1]
        assert [r.first_index for r in rows] == [0, 2, 4]
        assert [r.remaining_in_instrument for r in rows] == [3, 1, 0]
        assert [n for r in rows for n in r.readings] == [0., 1., 2., 3., 4.]
    assert state["values"] == []
    assert tr.history.count("DATA:REMove? 2") == 2
    assert tr.history.count("DATA:REMove? 1") == 1
    assert "FETCh?" not in tr.history


def test_destructive_export_requires_max_points_before_query(tmp_path):
    tr, _ = binary_sim([1., 2.])
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.transfer.export_volatile_bundle(
                tmp_path / "unsafe", destructive=True
            )
    assert tr.history == ["*IDN?"]


def test_non_destructive_export_contains_hash_and_provenance(tmp_path):
    tr, state = binary_sim([1.125, 2., -5.])
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_dc_voltage()
        receipt = dmm.transfer.export_volatile_bundle(tmp_path / "capture")
    assert receipt.samples == 3
    assert receipt.overrange_samples == 0
    assert not receipt.destructive
    assert (tmp_path / "capture" / "readings.csv").is_file()
    assert (tmp_path / "capture" / "metadata.json").is_file()
    m = json.loads(receipt.metadata_file.read_text())
    assert m["model"] == "34411A"
    assert m["serial"] == "TEST"
    assert m["driver_version"] == "0.8.0"
    assert m["sample_function"] == "dc_voltage"
    assert m["unit"] == "V"
    assert m["timestamp_source"] == "host-export-start only"
    assert m["sample_timestamps"] is None
    assert m["hardware_qualified"] is False
    raw = receipt.readings_file.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == receipt.sha256 == m["readings_csv_sha256"]
    with receipt.readings_file.open(newline="") as src:
        rows = list(csv.DictReader(src))
    assert len(rows) == 3
    assert [float(x["reading"]) for x in rows] == [1.125, 2., -5.]
    assert state["values"] == [1.125, 2., -5.]
    assert not list(tmp_path.glob(".capture.stage.*"))


def test_destructive_export_checks_actual_chunk_progress(tmp_path):
    tr, state = binary_sim([1., 2., 3., 4., 5.])
    with DMM_34411A(transport=tr) as dmm:
        receipt = dmm.transfer.export_volatile_bundle(
            tmp_path / "drain", destructive=True, max_points=3,
            chunk_size=2,
        )
        assert receipt.samples == 3
    assert receipt.destructive
    assert state["values"] == [4., 5.]
    assert json.loads(receipt.metadata_file.read_text())["source_command"] == "DATA:REMove?"
    assert tr.history.count("DATA:REMove? 2") == 1
    assert tr.history.count("DATA:REMove? 1") == 1


def test_duplicate_export_directory_cannot_be_overwritten(tmp_path):
    tr, state = binary_sim([1.])
    (tmp_path / "exists").mkdir()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(FileExistsError):
            dmm.transfer.export_volatile_bundle(tmp_path / "exists")
    assert state["values"] == [1.]
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize(("payload", "bits"), [
    (b"\x00", 32), (b"\0\0\0\0\0", 64)
])
def test_malformed_binary_payload_length(payload, bits):
    with pytest.raises(ValueError):
        list(decode_readings(payload, bits))


@pytest.mark.parametrize("bad", [0, -1, 16, 128, True, 32.0, "32"])
def test_invalid_precision_rejected_before_i_o(bad):
    tr, state = binary_sim([1.])
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.transfer.fetch_volatile_binary(precision_bits=bad)
    assert state["values"] == [1.]
    assert tr.history == ["*IDN?"]


def test_overrange_real32_and_real64_is_null_not_valid_number():
    for bits in (32, 64):
        fmt = ">f" if bits == 32 else ">d"
        payload = b"".join(struct.pack(fmt, x) for x in (1.0, 9.9e37, -9.9e37))
        assert list(decode_readings(payload, bits)) == [1.0, None, None]


@pytest.mark.parametrize("bits", [32, 64])
def test_nan_and_infinity_not_accepted_as_valid_meter_data(bits):
    fmt = ">f" if bits == 32 else ">d"
    payload = struct.pack(fmt, math.nan)
    with pytest.raises(ValueError):
        list(decode_readings(payload, bits))


def test_byte_count_mismatch_invalidates_transport():
    tr, _ = binary_sim([1., 2., 3.])
    tr.on("FETCh?", tr.block(struct.pack(">2f", 1., 2.)))
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ValueError):
            dmm.transfer.fetch_volatile_binary()
        assert not dmm.session.is_connected
    assert tr.history.count("FETCh?") == 1


def test_cancelled_drain_marks_unknown_without_deleting_nvm():
    tr, state = binary_sim([1., 2., 3.])
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(InterruptedError):
            list(dmm.transfer.iter_destructive_chunks(
                max_points=3, cancelled=lambda: True
            ))
        assert dmm.acquisition.state is AcquisitionState.UNKNOWN
        assert state["values"] == [1., 2., 3.]
    assert not any(x.startswith("DATA:REMove?") for x in tr.history)
    assert "DATA:DELete NVMEM" not in tr.history


def test_destructive_count_mismatch_is_uncertain_no_retry():
    tr, state = binary_sim([1., 2., 3.])
    tr.on("DATA:REMove? 2", tr.block(struct.pack(">2f", 1., 2.)))
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(TransferUncertainError) as exc:
            list(dmm.transfer.iter_destructive_chunks(max_points=2))
        assert exc.value.confirmed_removed == 0
        assert dmm.acquisition.state is AcquisitionState.UNKNOWN
        assert state["values"] == [1., 2., 3.]
    assert tr.history.count("DATA:REMove? 2") == 1


def test_destructive_timeout_not_replayed_and_no_final_bundle(tmp_path):
    tr, state = binary_sim([1., 2., 3.])
    tr.on("DATA:REMove? 2", ScriptedReply(
        raises=TransportTimeoutError("mid payload"), disconnect=True
    ))
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(TransferUncertainError):
            dmm.transfer.export_volatile_bundle(
                tmp_path / "failed",
                destructive=True, max_points=2, chunk_size=2
            )
        assert dmm.acquisition.state is AcquisitionState.UNKNOWN
    assert tr.history.count("DATA:REMove? 2") == 1
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob(".failed.stage.*"))


@pytest.mark.parametrize("bad", [0, 100001, True, None, "100"])
def test_invalid_chunk_size_preflight_no_removal(bad):
    tr, state = binary_sim([1., 2., 3.])
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            list(dmm.transfer.iter_destructive_chunks(
                max_points=2, chunk_size=bad
            ))
    assert state["values"] == [1., 2., 3.]
    assert tr.history == ["*IDN?"]


def test_large_request_exceeding_available_never_removes():
    tr, state = binary_sim([1., 2., 3.])
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            list(dmm.transfer.iter_destructive_chunks(max_points=4))
    assert state["values"] == [1., 2., 3.]
    assert "DATA:REMove? 4" not in tr.history


def test_faulted_or_armed_capture_refuses_binary_transfer():
    tr, _ = binary_sim([1., 2.])
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_volatile_acquisition(2, trigger_source="BUS")
        dmm.start_acquisition()
        with pytest.raises(RuntimeError):
            dmm.transfer.fetch_volatile_binary()
        with pytest.raises(RuntimeError):
            list(dmm.transfer.iter_destructive_chunks(max_points=1))
    assert "FETCh?" not in tr.history
    assert "DATA:REMove? 1" not in tr.history
