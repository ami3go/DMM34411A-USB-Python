"""HIL runner preflight tests. All actual I/O uses scripted offline transport."""

from __future__ import annotations

import hashlib
import json

import pytest

from dmm34411a.hil import CASES, main, plan, run_authorized
from scpi_driver_core.simulation import ScriptedScpiTransport


def simulated(idn="Agilent,34411A,SIM,A.03.00"):
    tr = ScriptedScpiTransport(unknown_command_error=None).on("*IDN?", idn)
    for command, reply in (
        ("*STB?", "0"),
        ("*ESE?", "0"),
        ("*SRE?", "0"),
        ("STATus:OPERation:CONDition?", "0"),
        ("STATus:OPERation:ENABle?", "0"),
        ("STATus:QUEStionable:CONDition?", "0"),
        ("STATus:QUEStionable:ENABle?", "0"),
        ("SYSTem:VERSion?", "1999.0"),
        ("ROUTe:TERMinals?", "FRON"),
        ("DATA:POINts? RDG_STORE", "12"),
        ("DATA:POINts? NVMEM", "7"),
        ("CONFigure:VOLTage:DC", None),
        ("READ?", "1.2500"),
    ):
        tr.on(command, reply)
    return tr


def args(tmp_path, **overrides):
    data = {
        "approved": True, "approval_token": "YES",
        "operator": "OFFLINE_SIMULATOR",
        "fixture": "BENCH_REFERENCE_SIM",
        "resource": "USB0::SIMULATOR::INSTR",
        "output": tmp_path / "evidence",
    }
    data.update(overrides)
    return data


def test_plan_is_pure_data_with_every_case_not_run(capsys):
    info = plan()
    assert len(info["cases"]) == len(CASES)
    assert info["hardware_qualified"] is False
    assert all(case["status"] == "NOT_RUN" for case in info["cases"])
    assert main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "PLAN_ONLY"
    assert all(case["status"] == "NOT_RUN" for case in output["cases"])


def test_authorization_rejected_before_any_transport_open(tmp_path):
    tr = simulated()
    with pytest.raises(PermissionError):
        run_authorized(transport=tr, **args(tmp_path, approved=False))
    with pytest.raises(PermissionError):
        run_authorized(transport=tr, **args(tmp_path, approval_token="NO"))
    assert tr.history == []
    assert not (tmp_path / "evidence").exists()


def test_existing_evidence_directory_cannot_be_overwritten(tmp_path):
    tr = simulated()
    (tmp_path / "evidence").mkdir()
    with pytest.raises(FileExistsError):
        run_authorized(transport=tr, **args(tmp_path))
    assert tr.history == []


def test_voltage_requires_independent_fixture_and_numeric_tolerance(tmp_path):
    tr = simulated()
    with pytest.raises(PermissionError):
        run_authorized(
            transport=tr, **args(tmp_path, dcv_smoke=True,
                                 reference_volts=1.25, tolerance_volts=0.01)
        )
    with pytest.raises(ValueError):
        run_authorized(
            transport=tr, **args(tmp_path, dcv_smoke=True,
                                 safe_dcv_fixture=True,
                                 reference_volts=1000, tolerance_volts=0.01)
        )
    with pytest.raises(ValueError):
        run_authorized(
            transport=tr, **args(tmp_path, dcv_smoke=True,
                                 safe_dcv_fixture=True,
                                 reference_volts=1.25, tolerance_volts=float("nan"))
        )
    assert tr.history == []


def test_read_only_preflight_records_live_queries_without_destructive_operations(tmp_path):
    tr = simulated()
    data = run_authorized(transport=tr, **args(tmp_path))
    assert data["overall_status"] == "PARTIAL"
    assert data["qualification_complete"] is False
    assert data["hardware_qualified"] is False
    assert data["cases"][0]["status"] == "OBSERVED"
    assert all(case["status"] == "NOT_RUN" for case in data["cases"][1:])
    evidence = tmp_path / "evidence"
    report = json.loads((evidence / "report.json").read_text())
    transcript_bytes = (evidence / "transcript.jsonl").read_bytes()
    assert hashlib.sha256(transcript_bytes).hexdigest() == report["transcript_sha256"]
    records = [json.loads(line) for line in transcript_bytes.decode().splitlines()]
    assert records[0]["command"] == "*IDN?"
    assert records[0]["response"].startswith("Agilent,34411A")
    assert report["diagnostics"]["nvm_points"] == 7
    assert report["diagnostics"]["volatile_points"] == 12
    assert all(item["type"] == "query" for item in records)
    assert not any(word in tr.history for word in (
        "*RST", "*CLS", "ABORt", "*ESR?", "SYSTem:ERRor?",
        "DATA:DELete NVMEM", "DATA:REMove? 1", "CONFigure:VOLTage:DC"
    ))


def test_explicit_10v_limited_dcv_smoke_records_provisional_status(tmp_path):
    tr = simulated()
    data = run_authorized(
        transport=tr,
        **args(tmp_path, dcv_smoke=True, safe_dcv_fixture=True,
               reference_volts=1.25, tolerance_volts=0.01),
    )
    assert data["overall_status"] == "PARTIAL"
    assert data["cases"][1]["status"] == "PROVISIONAL_PASS"
    assert data["cases"][1]["reading_volts"] == 1.25
    assert tr.history.count("CONFigure:VOLTage:DC") == 1
    assert tr.history.count("READ?") == 1
    assert "CONFigure:CURRent:DC" not in tr.history
    assert "DATA:DELete NVMEM" not in tr.history


def test_wrong_model_is_reported_not_hardware_qualified(tmp_path):
    tr = simulated(idn="Agilent,34410A,SIM,A.03.00")
    data = run_authorized(transport=tr, **args(tmp_path))
    assert data["overall_status"] == "FAIL"
    assert data["hardware_qualified"] is False
    assert data["errors"][0]["type"] == "ValueError"
    assert (tmp_path / "evidence" / "report.json").exists()
    assert tr.history == ["*IDN?"]


def test_voltage_mismatch_reports_failure_and_preserves_reading(tmp_path):
    tr = simulated()
    data = run_authorized(
        transport=tr,
        **args(tmp_path, dcv_smoke=True, safe_dcv_fixture=True,
               reference_volts=2.0, tolerance_volts=0.01),
    )
    assert data["overall_status"] == "FAIL"
    assert data["cases"][1]["status"] == "FAIL"
    assert (tmp_path / "evidence" / "transcript.jsonl").is_file()
