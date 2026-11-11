"""Opt-in 34411A HIL evidence runner; dry-run by default.

The CLI prints a NOT RUN plan unless an explicit authorization, environment
gate, bench resource and operator/fixture record are all supplied.
A live run performs read-only IDN/diagnostics by default. A DCV smoke
measurement additionally requires a declared safe low-voltage fixture and
explicit numerical reference/tolerance. No automatic current/ohms/diode
selection, reset, error drain, NVM deletion or calibration commands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scpi_driver_core.transport.base import Transport


CASES = (
    ("HIL-001", "IDN and read-only diagnostic snapshot"),
    ("HIL-002", "Low-voltage DCV smoke against operator supplied reference"),
    ("HIL-003", "ACV and frequency/period metrology standards"),
    ("HIL-004", "2W/4W resistance and offset compensation"),
    ("HIL-005", "Current AC/DC with independently approved fused fixture"),
    ("HIL-006", "Capacitance/diode/continuity/temperature standards"),
    ("HIL-007", "Internal/BUS/EXT trigger latency and pretrigger ordering"),
    ("HIL-008", "REAL32/64 framing, 1M throughput and buffer retention"),
    ("HIL-009", "Disposable destructive drain, safe NVM retention/persistence"),
    ("HIL-010", "Math/statistics/state/display firmware verification"),
    ("HIL-011", "USB/VXI-11/TCP disconnection and timeout behavior"),
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def plan() -> dict:
    """Pure-data worklist: no instrument access, file writes or plugin calls."""
    from . import __version__

    return {
        "driver_version": __version__,
        "mode": "PLAN_ONLY",
        "hardware_qualified": False,
        "qualification_complete": False,
        "cases": [
            {"id": ident, "description": name, "status": "NOT_RUN"}
            for ident, name in CASES
        ],
        "notes": (
            "HIL-001 is a read-only probe. HIL-002 is opt-in low-voltage "
            "DCV smoke, NOT a traceable accuracy qualification. All other "
            "cases require separate operator-controlled bench procedures."
        ),
    }


def _validate_inputs(
    *, approved: bool, approval_token: str | None, operator: str, fixture: str,
    resource: str, output: str | Path, dcv_smoke: bool, safe_dcv_fixture: bool,
    reference_volts: float | None, tolerance_volts: float | None,
) -> Path:
    if approved is not True or approval_token != "YES":
        raise PermissionError(
            "real HIL requires --authorize and DMM34411A_HIL_APPROVED=YES"
        )
    for value, label in ((operator, "operator"), (fixture, "fixture"), (resource, "resource")):
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError(f"{label} is required (1-200 characters)")
    if type(dcv_smoke) is not bool or type(safe_dcv_fixture) is not bool:
        raise ValueError("fixture switches must be boolean")
    if dcv_smoke:
        if not safe_dcv_fixture:
            raise PermissionError("DCV requires --safe-dcv-fixture approval")
        for value, label in ((reference_volts, "reference_volts"), (tolerance_volts, "tolerance_volts")):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{label} must be a finite number")
        if abs(float(reference_volts)) > 10.0 or not 0 < float(tolerance_volts) <= 1.0:
            raise ValueError("DCV reference must be within +/-10 V and 0 < tolerance <= 1 V")
    elif (safe_dcv_fixture or reference_volts is not None or tolerance_volts is not None):
        raise ValueError("DCV fixture/reference/tolerance provided without dcv_smoke")
    if not isinstance(output, (str, Path)):
        raise ValueError("output must be a new directory path")
    path = Path(output)
    if not path.name or not path.parent.is_dir() or path.exists() or path.is_symlink():
        raise FileExistsError("evidence output must be a new directory in an existing parent")
    return path


def run_authorized(
    *, approved: bool, approval_token: str | None, operator: str, fixture: str,
    resource: str, output: str | Path, dcv_smoke: bool = False,
    safe_dcv_fixture: bool = False, reference_volts: float | None = None,
    tolerance_volts: float | None = None, transport: Transport | None = None,
) -> dict:
    """Run strictly limited HIL and write a new evidence directory.

    The Transport injection is solely for deterministic offline tests; it
    never bypasses authorization. The test does NOT reset or restore an
    instrument's prior measurement function. All status/error event queues
    remain untouched. Failures are recorded with raw SCPI traces.
    """
    dest = _validate_inputs(
        approved=approved, approval_token=approval_token,
        operator=operator, fixture=fixture, resource=resource, output=output,
        dcv_smoke=dcv_smoke, safe_dcv_fixture=safe_dcv_fixture,
        reference_volts=reference_volts, tolerance_volts=tolerance_volts,
    )
    from . import __version__
    from .driver import DMM_34411A

    case_records = [
        {"id": ident, "description": name, "status": "NOT_RUN"}
        for ident, name in CASES
    ]
    report = {
        "schema_version": 1,
        "driver_version": __version__,
        "resource": resource,
        "operator": operator,
        "fixture": fixture,
        "approved": True,
        "started_at_utc": _utc(),
        "finished_at_utc": None,
        "overall_status": "IN_PROGRESS",
        "hardware_qualified": False,
        "qualification_complete": False,
        "cases": case_records,
        "errors": [],
    }
    transcript: list[dict] = []
    stage = Path(tempfile.mkdtemp(prefix=f".{dest.name}.stage.", dir=dest.parent))
    published = False
    try:
        try:
            dmm = DMM_34411A(
                resource_name=resource, transport=transport,
                timeout_s=10.0, auto_open=False,
            )
            # Capture actual raw SCPI command/reply evidence through the
            # already configured core client, without changing transport IO.
            query_original = dmm.client.query
            write_original = dmm.client.write

            def observed_query(command: str, *args, **kwargs):
                record = {"utc": _utc(), "type": "query", "command": command}
                try:
                    response = query_original(command, *args, **kwargs)
                    record["response"] = response
                    return response
                except BaseException as exc:
                    record["exception"] = type(exc).__name__
                    raise
                finally:
                    transcript.append(record)

            def observed_write(command: str, *args, **kwargs):
                record = {"utc": _utc(), "type": "write", "command": command}
                try:
                    return write_original(command, *args, **kwargs)
                except BaseException as exc:
                    record["exception"] = type(exc).__name__
                    raise
                finally:
                    transcript.append(record)

            dmm.client.query = observed_query
            dmm.client.write = observed_write
            with dmm:
                idn = dmm.idn or ""
                parts = [item.strip() for item in idn.split(",")]
                if len(parts) != 4 or parts[1].upper() != "34411A":
                    raise ValueError(f"expected 34411A identity, received {idn!r}")
                report["instrument_idn"] = idn
                snapshot = dmm.diagnostics_snapshot(
                    include_memory=True, include_system=True
                )
                report["diagnostics"] = asdict(snapshot)
                case_records[0]["status"] = "OBSERVED"
                if dcv_smoke:
                    # DCV only after explicit low-voltage fixture approval;
                    # no current, ohms, diode, or capacitance mode switching.
                    dmm.configure_dc_voltage()
                    reading = dmm.measurement.read()
                    case_records[1]["reference_volts"] = float(reference_volts)
                    case_records[1]["tolerance_volts"] = float(tolerance_volts)
                    case_records[1]["reading_volts"] = reading.value
                    case_records[1]["raw_reading"] = reading.raw
                    case_records[1]["host_received_utc"] = reading.measured_at_utc.isoformat()
                    case_records[1]["status"] = (
                        "PROVISIONAL_PASS"
                        if reading.value is not None and
                        abs(reading.value - float(reference_volts)) <= float(tolerance_volts)
                        else "FAIL"
                    )
                    if case_records[1]["status"] == "FAIL":
                        report["errors"].append(
                            "DCV smoke reading outside operator tolerance or overrange"
                        )
            report["overall_status"] = "FAIL" if report["errors"] else "PARTIAL"
        except BaseException as exc:
            report["overall_status"] = "FAIL"
            report["errors"].append(
                {"type": type(exc).__name__, "message": str(exc)}
            )
        finally:
            report["finished_at_utc"] = _utc()
            # Raw transcript is not filtered by a post-hoc status/error drain.
            transcript_bytes = "".join(
                json.dumps(item, sort_keys=True, default=str) + "\n"
                for item in transcript
            ).encode("utf-8")
            (stage / "transcript.jsonl").write_bytes(transcript_bytes)
            report["transcript_sha256"] = hashlib.sha256(transcript_bytes).hexdigest()
            report["transcript_events"] = len(transcript)
            (stage / "report.json").write_text(
                json.dumps(report, sort_keys=True, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        if dest.exists() or dest.is_symlink():
            raise FileExistsError("evidence target created before final publish")
        os.rename(stage, dest)
        published = True
        report["evidence_directory"] = str(dest)
        return report
    finally:
        if not published and stage.exists():
            # Preserve evidence if publishing failed, rather than erasing
            # a potentially unique real-device SCPI transcript.
            report["unpublished_evidence_directory"] = str(stage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Keysight 34411A HIL evidence preflight (dry-run by default)"
    )
    parser.add_argument("--authorize", action="store_true", help="explicitly authorize physical I/O")
    parser.add_argument("--resource", help="VISA address of approved 34411A")
    parser.add_argument("--operator", help="bench operator identifier")
    parser.add_argument("--fixture", help="verified fixture description")
    parser.add_argument("--output", help="new evidence output directory")
    parser.add_argument("--dcv-smoke", action="store_true",
                        help="operator-approved low-voltage DCV smoke measurement")
    parser.add_argument("--safe-dcv-fixture", action="store_true",
                        help="assert DCV terminal/fixture and <=10 V source are safe")
    parser.add_argument("--reference-volts", type=float)
    parser.add_argument("--tolerance-volts", type=float)
    args = parser.parse_args(argv)
    if not args.authorize:
        print(json.dumps(plan(), indent=2))
        return 0
    try:
        result = run_authorized(
            approved=args.authorize,
            approval_token=os.environ.get("DMM34411A_HIL_APPROVED"),
            operator=args.operator, fixture=args.fixture, resource=args.resource,
            output=args.output, dcv_smoke=args.dcv_smoke,
            safe_dcv_fixture=args.safe_dcv_fixture,
            reference_volts=args.reference_volts,
            tolerance_volts=args.tolerance_volts,
        )
    except (ValueError, PermissionError, FileExistsError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "overall_status": result["overall_status"],
        "evidence_directory": result["evidence_directory"],
        "hardware_qualified": False,
    }, indent=2))
    return 1 if result["overall_status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
