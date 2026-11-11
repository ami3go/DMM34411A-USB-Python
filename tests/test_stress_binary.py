"""Large-buffer and throughput regressions, simulated: no physical 34411A."""

from __future__ import annotations

import hashlib
import json
import struct

import pytest

from dmm34411a import DMM_34411A

pytestmark = pytest.mark.stress


def _instrument(payload: bytes, *, points: int):
    """Simulate one finite IEEE block in the core's byte transport."""
    tr = __import__(
        "scpi_driver_core.simulation", fromlist=["ScriptedScpiTransport"]
    ).ScriptedScpiTransport(unknown_command_error=None)
    state = {"format": "ASC,9", "border": "SWAP", "points": points}
    tr.on("*IDN?", "Agilent,34411A,OFFLINE,A.03.00")
    tr.on("DATA:POINts? RDG_STORE", lambda _: str(state["points"]))
    tr.on("FORMat:DATA?", lambda _: state["format"])
    tr.on("FORMat:BORDer?", lambda _: state["border"])
    tr.on_regex(
        r"^FORMat:DATA .+",
        lambda command: state.update(format=command.split(" ", 1)[1]),
    )
    tr.on_regex(
        r"^FORMat:BORDer .+",
        lambda command: state.update(border=command.split(" ", 1)[1]),
    )
    tr.reply_block("FETCh?", payload)
    return tr, state


@pytest.mark.parametrize("points", [1, 50_000, 100_000, 1_000_000])
@pytest.mark.parametrize("bits", [32, 64])
@pytest.mark.timeout(180)
def test_full_buffer_binary_exact_framing_and_lazy_decoding(points, bits):
    """1M × REAL64 = 8MB; no million-element Python list is materialized."""
    width = 4 if bits == 32 else 8
    payload = struct.pack(">f" if bits == 32 else ">d", 1.25) * points
    assert len(payload) == points * width
    tr, state = _instrument(payload, points=points)
    with DMM_34411A(transport=tr, timeout_s=180) as dmm:
        captured = dmm.fetch_volatile_binary(
            precision_bits=bits, timeout_s=180
        )
        assert captured.samples == points
        assert len(captured.payload) == points * width
        assert hashlib.sha256(captured.payload).digest() == hashlib.sha256(payload).digest()
        assert sum(1 for value in captured.readings() if value == 1.25) == points
        assert state["format"] == "ASC,9"
        assert state["border"] == "SWAP"
        assert state["points"] == points
    assert tr.history.count("FETCh?") == 1
    assert not any("REMove?" in command for command in tr.history)
    assert "DATA:DELete NVMEM" not in tr.history


@pytest.mark.timeout(180)
def test_50000_point_atomic_csv_export_and_hash(tmp_path):
    points = 50_000
    payload = struct.pack(">f", -3.75) * points
    tr, state = _instrument(payload, points=points)
    with DMM_34411A(transport=tr, timeout_s=180) as dmm:
        receipt = dmm.export_volatile_bundle(
            tmp_path / "capture50k", precision_bits=32, timeout_s=180
        )
    assert receipt.samples == points
    assert receipt.overrange_samples == 0
    assert state["points"] == points
    meta = json.loads(receipt.metadata_file.read_text())
    assert meta["sample_count"] == points
    assert meta["hardware_qualified"] is False
    with receipt.readings_file.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    assert receipt.sha256 == digest == meta["readings_csv_sha256"]
    assert receipt.readings_file.stat().st_size > points * 6
    assert not list(tmp_path.glob(".capture50k.stage.*"))
