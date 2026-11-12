"""34411A bounded IEEE binary reading transfers and atomic host exports.

Extends the existing AcquisitionController; never creates another acquisition
engine. FETCh? is explicitly non-destructive; DATA:REMove? is EXPLICITLY
destructive and must never be retried after an uncertain reply.

All IEEE definite-length framing uses the pinned scpi-driver-core client.
The 34411A's exact binary block terminator, endianness and retention rules
still require physical hardware qualification.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import struct
import tempfile
from threading import Event
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from collections.abc import Callable, Iterator

from scpi_driver_core import ConfigurationError

from .acquisition import AcquisitionState, VOLATILE_MEMORY_POINTS

_MAX_CHUNK = 100_000
_MAX_TRANSFER_BYTES = VOLATILE_MEMORY_POINTS * 8
_FORMAT_PATTERN = re.compile(r"^(?:ASC(?:II)?(?:,[0-9]+)?|REAL(?:,(?:32|64))?)$", re.I)
_BORDER_PATTERN = re.compile(r"^(?:NORM(?:AL)?|SWAP(?:PED)?)$", re.I)


@dataclass(frozen=True)
class BinaryCapture:
    """Raw IEEE-754 bytes, retaining instrument bit-level transfer precision."""

    samples: int
    precision_bits: int
    payload: bytes
    source: str = "FETCh? (non-destructive)"

    def readings(self) -> Iterator[float | None]:
        yield from decode_readings(self.payload, self.precision_bits)


@dataclass(frozen=True)
class ReadingChunk:
    """Confirmed partial dequeue, with original sample positions."""

    first_index: int
    readings: tuple[float | None, ...]
    remaining_in_instrument: int
    precision_bits: int


@dataclass(frozen=True)
class ExportReceipt:
    directory: Path
    samples: int
    sha256: str
    destructive: bool
    overrange_samples: int
    metadata_file: Path
    readings_file: Path


class TransferUncertainError(RuntimeError):
    """Destructive DATA:REMove? outcome or count reconciliation is unknown."""

    def __init__(self, message: str, *, confirmed_removed: int) -> None:
        super().__init__(message)
        self.confirmed_removed = confirmed_removed


def _precision(bits: int) -> int:
    if type(bits) is not int or bits not in (32, 64):
        raise ConfigurationError("precision_bits must be integer 32 or 64")
    return bits // 8


def _positive(value: int, maximum: int, what: str) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ConfigurationError(f"{what} must be integer from 1 to {maximum}")
    return value


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ConfigurationError("timeout_s must be a finite positive number")
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 < parsed <= 3600:
        raise ConfigurationError("timeout_s must be 0 < timeout_s <=3600 seconds")
    return parsed


def _format(value: str) -> str:
    text = value.strip().upper()
    if not _FORMAT_PATTERN.fullmatch(text):
        raise ValueError(f"invalid instrument FORMat:DATA? reply: {value!r}")
    if text == "REAL":
        return "REAL,64"  # documented default REAL length
    return text


def _border(value: str) -> str:
    text = value.strip().upper()
    if not _BORDER_PATTERN.fullmatch(text):
        raise ValueError(f"invalid instrument FORMat:BORDer? reply: {value!r}")
    return "NORM" if text.startswith("NORM") else "SWAP"


def decode_readings(payload: bytes, precision_bits: int) -> Iterator[float | None]:
    """Decode big-endian IEEE754 values in constant additional memory.

    34411A overload +/-9.9E37 is mapped to None; nonfinite NaN/Inf values
    are rejected rather than silently reported as valid measurements.
    """
    width = _precision(precision_bits)
    if len(payload) % width:
        raise ValueError(f"binary payload is not a multiple of {width} bytes")
    fmt = ">f" if precision_bits == 32 else ">d"
    for (reading,) in struct.iter_unpack(fmt, payload):
        if not math.isfinite(reading):
            raise ValueError("non-finite IEEE reading in DMM binary block")
        # A REAL,32 encoding may round 9.9E37 slightly below the sentinel.
        yield None if abs(reading) >= 9.8e37 else float(reading)


class ReadingTransferController:
    """Binary readout/export that delegates acquisition lifecycle to meter.acquisition."""

    def __init__(self, meter: object) -> None:
        self._meter = meter
        self._active_transfer = False
        self._cancel_requested = Event()

    def request_cancel(self) -> None:
        """Nonblocking signal; never emits SCPI or replays a command."""
        self._cancel_requested.set()

    @contextmanager
    def _exclusive_transfer(self) -> Iterator[None]:
        """Hold the canonical SCPI client lock across a full transfer.

        A destructive iterator must be exhausted or explicitly closed.
        """
        with self._meter.session.operation_lock():
            if self._active_transfer:
                raise RuntimeError("nested binary transfers are prohibited")
            acq = self._meter.acquisition
            if (acq._stop_requested.is_set()
                    and acq._state not in (AcquisitionState.ABORTED,
                                           AcquisitionState.CONFIGURED,
                                           AcquisitionState.IDLE)):
                raise InterruptedError("STOP pending; do not begin transfer")
            self._cancel_requested.clear()
            self._active_transfer = True
            try:
                yield
            finally:
                if acq._state in (AcquisitionState.UNKNOWN, AcquisitionState.FAULTED):
                    self._meter.recovery.mark_uncertain(
                        "binary transfer interrupted or uncertain; inspect memory"
                    )
                self._active_transfer = False

    @property
    def _client(self):
        return self._meter.client

    def _ready(self) -> None:
        if not self._meter.session.is_connected:
            raise RuntimeError("instrument is disconnected")
        if self._meter.acquisition.state in (
            AcquisitionState.ARMED, AcquisitionState.UNKNOWN, AcquisitionState.FAULTED
        ):
            raise RuntimeError(
                "capture is still armed/unknown/faulted; reconcile or explicitly abort"
            )

    @contextmanager
    def _binary_format(self, precision_bits: int) -> Iterator[None]:
        """Format and border are persistent settings; restore on every safe exit.

        Caller holds _exclusive_transfer for full format/read/restore
        lifetime; no other client command may interleave.
        """
        _precision(precision_bits)
        previous_data = previous_border = None
        selected = f"REAL,{precision_bits}"
        with self._meter.session.operation_lock():
            previous_data = _format(self._client.query("FORMat:DATA?"))
            previous_border = _border(self._client.query("FORMat:BORDer?"))
        try:
            with self._meter.session.operation_lock():
                if previous_data != selected:
                    self._client.write(f"FORMat:DATA {selected}")
                if previous_border != "NORM":
                    self._client.write("FORMat:BORDer NORMal")
                self._verify_format(selected)
            yield
        finally:
            if previous_data is not None and previous_border is not None and (
                self._meter.session.is_connected
            ):
                try:
                    with self._meter.session.operation_lock():
                        self._client.write(f"FORMat:BORDer {previous_border}")
                        self._client.write(f"FORMat:DATA {previous_data}")
                except BaseException:
                    self._meter.transport.invalidate()
                    raise

    def _verify_format(self, selected: str) -> None:
        # Called under the session lock; no caller may interleave on this client.
        current_data = _format(self._client.query("FORMat:DATA?"))
        current_border = _border(self._client.query("FORMat:BORDer?"))
        if current_data != selected or current_border != "NORM":
            raise RuntimeError("instrument binary data format/byte order changed unexpectedly")

    def _query_binary(self, command: str, count: int, bits: int, budget: float) -> bytes:
        width = _precision(bits)
        expected = count * width
        if expected > _MAX_TRANSFER_BYTES:
            raise ConfigurationError("transfer exceeds configured bounded binary memory")
        payload = self._client.query_binary_block(
            command,
            maximum_size=max(expected, 1),
            timeout_s=budget,
            consume_terminator=True,
        )
        if len(payload) != expected:
            self._meter.transport.invalidate()
            raise ValueError(
                f"{command} returned {len(payload)} bytes; expected {expected}; stream faulted"
            )
        return payload

    def fetch_volatile_binary(
        self, *, precision_bits: int = 32, timeout_s: float = 120.0,
    ) -> BinaryCapture:
        """Non-destructive capture with exclusive count/format/read/restore.

        Serializes the entire binary transaction against all other users of
        the same ScpiClient, including raw commands and status queries.
        """
        _precision(precision_bits)
        budget = _timeout(timeout_s)
        with self._exclusive_transfer():
            self._ready()
            count = self._meter.acquisition.volatile_count()
            if count == 0:
                return BinaryCapture(0, precision_bits, b"")
            if count > VOLATILE_MEMORY_POINTS:
                raise ValueError("instrument reports more than 1 million volatile samples")
            try:
                with self._binary_format(precision_bits):
                    self._ready()
                    self._verify_format(f"REAL,{precision_bits}")
                    if self._cancel_requested.is_set():
                        raise InterruptedError("binary FETCh cancelled before read")
                    payload = self._query_binary("FETCh?", count, precision_bits, budget)
                    if self._cancel_requested.is_set():
                        raise InterruptedError("binary FETCh cancelled, result not published")
                    count_after = self._meter.acquisition.volatile_count()
                    if count_after != count:
                        raise RuntimeError(
                            "volatile buffer changed during FETCh?; result uncertain"
                        )
            except BaseException:
                self._meter.acquisition._state = AcquisitionState.UNKNOWN
                raise
            return BinaryCapture(count, precision_bits, payload)

    def iter_destructive_chunks(
        self, *, max_points: int, chunk_size: int = 10_000,
        precision_bits: int = 32, timeout_s: float = 120.0,
        cancelled: Callable[[], bool] | None = None,
    ) -> Iterator[ReadingChunk]:
        """Explicit destructive stream with an instrument-wide transfer lease.

        Consumer MUST exhaust this iterator or call .close() (prefer
        contextlib.closing); the core lock remains held across yields.
        This is intentional to preserve FIFO/format integrity. STOP or
        request_cancel() interrupts before the next destructive query.
        """
        target = _positive(max_points, VOLATILE_MEMORY_POINTS, "max_points")
        chunk = _positive(chunk_size, _MAX_CHUNK, "chunk_size")
        _precision(precision_bits)
        budget = _timeout(timeout_s)
        if cancelled is not None and not callable(cancelled):
            raise ConfigurationError("cancelled must be callable or None")
        with self._exclusive_transfer():
            self._meter.recovery.require_reconciled("destructive binary drain")
            self._ready()
            available = self._meter.acquisition.volatile_count()
            if target > available:
                raise ConfigurationError(
                    f"requested {target} destructive readings; only {available} available"
                )
            removed = 0
            completed = False
            try:
                with self._binary_format(precision_bits):
                    while removed < target:
                        if self._cancel_requested.is_set() or (
                            cancelled is not None and cancelled()
                        ):
                            self._meter.acquisition._state = AcquisitionState.UNKNOWN
                            raise InterruptedError(
                                f"destructive drain cancelled after {removed} confirmed readings"
                            )
                        take = min(chunk, target - removed)
                        try:
                            self._ready()
                            self._verify_format(f"REAL,{precision_bits}")
                            before = self._meter.acquisition.volatile_count()
                            if before != available:
                                raise RuntimeError(
                                    "volatile count changed between chunks; external interference"
                                )
                            payload = self._query_binary(
                                f"DATA:REMove? {take}", take, precision_bits, budget
                            )
                            after = self._meter.acquisition.volatile_count()
                            if after != available - take:
                                raise RuntimeError(
                                    f"destructive count mismatch: {before}->{after} for {take}"
                                )
                            readings = tuple(decode_readings(payload, precision_bits))
                        except Exception as exc:
                            self._meter.acquisition._state = AcquisitionState.UNKNOWN
                            raise TransferUncertainError(
                                "DATA:REMove? outcome/reading integrity uncertain; do not retry",
                                confirmed_removed=removed,
                            ) from exc
                        first = removed
                        # Update confirmed offsets BEFORE yielding, so caller
                        # closes/aborts cannot undercount consumed samples.
                        removed += take
                        available = after
                        yield ReadingChunk(
                            first_index=first, readings=readings,
                            remaining_in_instrument=after, precision_bits=precision_bits,
                        )
                completed = True
            finally:
                if not completed and removed:
                    self._meter.acquisition._state = AcquisitionState.UNKNOWN

    def export_volatile_bundle(
        self, directory: str | Path, *, destructive: bool = False,
        max_points: int | None = None, precision_bits: int = 32,
        chunk_size: int = 10_000, timeout_s: float = 120.0,
        cancelled: Callable[[], bool] | None = None,
    ) -> ExportReceipt:
        """Atomically publish a directory with readings.csv + metadata.json.

        A successful bundle is published with a sibling directory rename.
        If a destructive export fails after writing confirmed readings, the
        partial CSV is PRESERVED with incomplete metadata in a uniquely
        named .partial directory; the original failure still propagates.
        Never silently retry an uncertain destructive transfer.
        """
        _precision(precision_bits)
        _timeout(timeout_s)
        if type(destructive) is not bool:
            raise ConfigurationError("destructive must be bool")
        if not isinstance(directory, (str, Path)):
            raise ConfigurationError("directory must be str or Path")
        dest = Path(directory)
        if not dest.name or not dest.parent.is_dir() or dest.exists() or dest.is_symlink():
            raise FileExistsError("export destination must be new in an existing directory")
        if destructive:
            if max_points is None:
                raise ConfigurationError("destructive export requires explicit max_points")
            _positive(max_points, VOLATILE_MEMORY_POINTS, "max_points")
        elif max_points is not None:
            raise ConfigurationError("non-destructive FETCh? exports entire buffer; omit max_points")
        _positive(chunk_size, _MAX_CHUNK, "chunk_size")
        if cancelled is not None and not callable(cancelled):
            raise ConfigurationError("cancelled must be callable or None")
        self._ready()
        from . import __version__ as driver_version

        capture_started_utc = datetime.now(timezone.utc).isoformat()
        buffer = self._meter.acquisition
        idn = self._meter.idn or ""
        idparts = idn.split(",", 3)
        try:
            core_version = package_version("scpi-driver-core")
        except PackageNotFoundError:
            core_version = "unavailable"
        active = self._meter.measurement._active
        function = active.function if active is not None else None
        # Unit is not fabricated; non-temperature unit from command map only.
        from .measurement import _COMMANDS
        unit = _COMMANDS[function][2] if function is not None else None
        stage = Path(tempfile.mkdtemp(prefix=f".{dest.name}.stage.", dir=dest.parent))
        published = False
        overrange = 0
        count = 0
        csvfile = stage / "readings.csv"
        metafile = stage / "metadata.json"
        try:
            import csv
            with csvfile.open("w", encoding="utf-8", newline="") as out:
                writer = csv.writer(out, lineterminator="\n")
                writer.writerow(("index", "reading", "overrange"))
                if destructive:
                    from contextlib import closing
                    with closing(self.iter_destructive_chunks(
                        max_points=max_points, chunk_size=chunk_size,
                        precision_bits=precision_bits, timeout_s=timeout_s,
                        cancelled=cancelled,
                    )) as stream:
                        for chunk in stream:
                            for reading in chunk.readings:
                                writer.writerow((count, "" if reading is None else repr(reading),
                                                 1 if reading is None else 0))
                                count += 1
                                overrange += reading is None
                else:
                    capture = self.fetch_volatile_binary(
                        precision_bits=precision_bits, timeout_s=timeout_s
                    )
                    for reading in capture.readings():
                        if cancelled is not None and cancelled():
                            raise InterruptedError("non-destructive export cancelled")
                        writer.writerow((count, "" if reading is None else repr(reading),
                                         1 if reading is None else 0))
                        count += 1
                        overrange += reading is None
            digest = hashlib.sha256()
            with csvfile.open("rb") as inp:
                while True:
                    part = inp.read(1024 * 1024)
                    if not part:
                        break
                    digest.update(part)
            record = {
                "format_version": 1,
                "driver_version": driver_version,
                "scpi_core_version": core_version,
                "instrument_idn": idn,
                "manufacturer": idparts[0].strip() if len(idparts) > 0 else None,
                "model": idparts[1].strip() if len(idparts) > 1 else None,
                "serial": idparts[2].strip() if len(idparts) > 2 else None,
                "firmware": idparts[3].strip() if len(idparts) > 3 else None,
                "transport_type": type(self._meter.transport).__name__,
                "sample_function": function.value if function is not None else None,
                "unit": unit or None,
                "nominal_sample_interval_s": buffer._sample_interval_s,
                "nominal_interval_is_measured": False,
                "sample_timestamps": None,
                "timestamp_source": "host-export-start only",
                "export_started_at_utc": capture_started_utc,
                "export_completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "trigger_source": buffer._source,
                "trigger_count": buffer._triggers,
                "pretrigger_per_event": buffer._pretrigger_count,
                "sample_count": count,
                "overrange_samples": overrange,
                "precision_bits": precision_bits,
                "instrument_byte_order_used": "NORM (big endian)",
                "destructive": destructive,
                "source_command": "DATA:REMove?" if destructive else "FETCh?",
                "readings_csv_sha256": digest.hexdigest(),
                "readings_csv_bytes": csvfile.stat().st_size,
                "hardware_qualified": False,
            }
            metafile.write_text(
                json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            # One parent-local rename: readers never see a half-written bundle.
            # The destination must not pre-exist; never delete/overwrite results.
            if dest.exists() or dest.is_symlink():
                raise FileExistsError("export destination created concurrently")
            os.rename(stage, dest)
            published = True
            return ExportReceipt(
                directory=dest, samples=count, sha256=digest.hexdigest(),
                destructive=destructive, overrange_samples=overrange,
                metadata_file=dest / "metadata.json",
                readings_file=dest / "readings.csv",
            )
        except BaseException as error:
            if destructive and count:
                # Dequeued readings are irrecoverable from instrument memory.
                # Preserve even incomplete CSV rows instead of deleting them
                # during cleanup. Do not present them as a successful capture.
                partial = dest.with_name(
                    f"{dest.name}.partial.{secrets.token_hex(8)}"
                )
                try:
                    if csvfile.is_file():
                        digest = hashlib.sha256(csvfile.read_bytes()).hexdigest()
                    else:
                        digest = None
                    metafile.write_text(
                        json.dumps({
                            "format_version": 1,
                            "status": "INCOMPLETE",
                            "destructive": True,
                            "confirmed_csv_rows": count,
                            "current_chunk_outcome": "UNKNOWN",
                            "reason": type(error).__name__,
                            "instrument_idn": idn,
                            "readings_csv_sha256": digest,
                            "timestamp_source": "host-export-start only",
                            "hardware_qualified": False,
                        }, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    os.rename(stage, partial)
                    published = True  # Protect partial artifact from cleanup.
                except BaseException:
                    # Preserve the staging directory for manual recovery if
                    # even the partial publication fails (e.g. disk full).
                    partial = stage
                    published = True
                try:
                    error.partial_directory = partial
                    error.confirmed_csv_rows = count
                except (AttributeError, TypeError):
                    pass
            raise
        finally:
            if not published:
                shutil.rmtree(stage, ignore_errors=True)
