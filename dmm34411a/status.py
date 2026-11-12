"""34411A SCPI status, error queue and non-destructive diagnostics.

Reads of *ESR?, STATus:*:EVENt?, and SYSTem:ERRor? consume instrument
events/errors; they are NEVER called from snapshot(), open() or close().
No automatic *CLS, *RST, self-test, VISA device clear, or retry on timeout.

Commands cross-checked against Keysight 34410A/11A SCPI comparison
5990-3515 and 34410A/11A/L4411A User Guide 34410-90001.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from scpi_driver_core import ConfigurationError


_REGISTER_HEADERS = {
    "operation": "STATus:OPERation",
    "questionable": "STATus:QUEStionable",
}
_ERROR_PATTERN = re.compile(r"^\s*([+-]?\d+)\s*,(.*)$", re.DOTALL)


@dataclass(frozen=True)
class ScpiError:
    code: int
    message: str
    raw: str

    @property
    def is_no_error(self) -> bool:
        return self.code == 0


@dataclass(frozen=True)
class ErrorDrain:
    """Explicitly removed errors; exhausted=True means the queue may continue."""

    errors: tuple[ScpiError, ...]
    exhausted: bool


@dataclass(frozen=True)
class StatusBank:
    condition: int
    enable: int


@dataclass(frozen=True)
class DiagnosticSnapshot:
    """Non-destructive status values (never reads event/error queues)."""

    received_at_utc: datetime
    idn_raw: str
    manufacturer: str
    model: str
    serial: str
    firmware: str
    connected: bool
    transport_type: str
    status_byte: int
    standard_event_enable: int
    service_request_enable: int
    operation: StatusBank
    questionable: StatusBank
    scpi_version: str | None
    terminal_selection: str | None
    volatile_points: int | None
    nvm_points: int | None


def _count(value: int, *, maximum: int, name: str) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ConfigurationError(f"{name} must be integer 1..{maximum}")
    return value


def _mask(value: int, *, maximum: int, name: str) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ConfigurationError(f"{name} must be integer 0..{maximum}")
    return value


def _int_reply(raw: str, *, maximum: int, name: str) -> int:
    text = raw.strip()
    if not re.fullmatch(r"[+]?\d+", text):
        raise ValueError(f"invalid {name} reply: {raw!r}")
    value = int(text)
    if value > maximum:
        raise ValueError(f"{name} reply outside 0..{maximum}: {raw!r}")
    return value


def _parse_error(raw: str) -> ScpiError:
    match = _ERROR_PATTERN.fullmatch(raw)
    if match is None:
        raise ValueError(f"invalid SCPI error reply: {raw!r}")
    code = int(match.group(1))
    if not -32768 <= code <= 32767:
        raise ValueError(f"SCPI error code outside signed 16-bit range: {raw!r}")
    body = match.group(2).strip()
    if not body:
        raise ValueError(f"missing SCPI error text: {raw!r}")
    if body.startswith('"'):
        try:
            parsed = next(csv.reader(io.StringIO(body), strict=True))
        except csv.Error as exc:
            raise ValueError(f"invalid quoted SCPI error text: {raw!r}") from exc
        if len(parsed) != 1 or not body.endswith('"'):
            raise ValueError(f"invalid SCPI error text: {raw!r}")
        message = parsed[0]
    else:
        # Some firmware returns unquoted plain text. Retain the raw reply.
        message = body
    if not message or any(ord(ch) < 32 and ch not in "\t" for ch in message):
        raise ValueError(f"invalid SCPI error message: {raw!r}")
    return ScpiError(code=code, message=message, raw=raw)


def _idn(raw: str) -> tuple[str, str, str, str]:
    parts = raw.split(",", 3)
    if len(parts) != 4 or not all(p.strip() for p in parts):
        raise ValueError(f"malformed *IDN? identity: {raw!r}")
    return tuple(x.strip() for x in parts)  # type: ignore[return-value]


def _bank(which: str) -> str:
    if not isinstance(which, str) or which not in _REGISTER_HEADERS:
        raise ConfigurationError("status bank must be 'operation' or 'questionable'")
    return _REGISTER_HEADERS[which]


def _deadline(value: float) -> float:
    import math
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError("timeout_s must be a finite positive number")
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 3600:
        raise ConfigurationError("timeout_s must be positive, finite, <=3600 seconds")
    return number


class StatusController:
    """Instrument-backed, explicitly scoped health/status API."""

    def __init__(self, meter: object) -> None:
        self._meter = meter

    @property
    def _client(self):
        return self._meter.client

    def get_error(self) -> ScpiError:
        """DEQUEUE exactly one error. This query is NOT non-destructive."""
        with self._meter.session.operation_lock():
            return _parse_error(self._client.query("SYSTem:ERRor?").strip())

    def drain_errors(self, max_errors: int = 32) -> ErrorDrain:
        """Explicitly dequeue up to max_errors; no hidden *CLS.

        A final code=0 reply confirms empty; if the budget is spent first,
        exhausted=True and remaining queue state is UNKNOWN. No extra
        dequeue is performed just to learn whether there are more errors.
        """
        limit = _count(max_errors, maximum=256, name="max_errors")
        errors: list[ScpiError] = []
        with self._meter.session.operation_lock():
            for _ in range(limit):
                item = self.get_error()
                if item.is_no_error:
                    return ErrorDrain(tuple(errors), exhausted=False)
                errors.append(item)
        return ErrorDrain(tuple(errors), exhausted=True)

    def status_byte(self) -> int:
        """*STB? is a non-consuming snapshot, unlike a serial poll in some backends."""
        with self._meter.session.operation_lock():
            return _int_reply(self._client.query("*STB?"), maximum=255, name="status byte")

    def standard_event_enable(self) -> int:
        with self._meter.session.operation_lock():
            return _int_reply(self._client.query("*ESE?"), maximum=255, name="ESE")

    def set_standard_event_enable(self, mask: int) -> None:
        value = _mask(mask, maximum=255, name="ESE")
        with self._meter.session.operation_lock():
            self._client.write(f"*ESE {value}")

    def service_request_enable(self) -> int:
        with self._meter.session.operation_lock():
            return _int_reply(self._client.query("*SRE?"), maximum=255, name="SRE")

    def set_service_request_enable(self, mask: int) -> None:
        value = _mask(mask, maximum=255, name="SRE")
        if value & 0x40:
            raise ConfigurationError("service request enable bit 6 is reserved")
        with self._meter.session.operation_lock():
            self._client.write(f"*SRE {value}")

    def standard_event_register(self) -> int:
        """*ESR? reads AND CLEARS the standard event register: explicit only."""
        with self._meter.session.operation_lock():
            return _int_reply(self._client.query("*ESR?"), maximum=255, name="ESR")

    def condition(self, bank: str) -> int:
        prefix = _bank(bank)
        with self._meter.session.operation_lock():
            return _int_reply(self._client.query(f"{prefix}:CONDition?"),
                              maximum=32767, name=f"{bank} condition")

    def enable(self, bank: str) -> int:
        prefix = _bank(bank)
        with self._meter.session.operation_lock():
            return _int_reply(self._client.query(f"{prefix}:ENABle?"),
                              maximum=32767, name=f"{bank} enable")

    def set_enable(self, bank: str, mask: int) -> None:
        prefix = _bank(bank)
        value = _mask(mask, maximum=32767, name=f"{bank} enable")
        with self._meter.session.operation_lock():
            self._client.write(f"{prefix}:ENABle {value}")

    def event(self, bank: str) -> int:
        """Status bank event query is READ-TO-CLEAR. Not used in snapshots."""
        prefix = _bank(bank)
        with self._meter.session.operation_lock():
            return _int_reply(self._client.query(f"{prefix}:EVENt?"),
                              maximum=32767, name=f"{bank} event")

    def snapshot(
        self, *, include_memory: bool = False, include_system: bool = True,
    ) -> DiagnosticSnapshot:
        """Non-destructive instrument status snapshot.

        Does not dequeue errors, read event registers or initiate acquisition.
        Counts are optional to avoid probing buffers during active transfers.
        Individual SCPI queries are sequential, not a device-atomic snapshot.
        """
        if type(include_memory) is not bool or type(include_system) is not bool:
            raise ConfigurationError("include_memory and include_system must be bool")
        with self._meter.session.operation_lock():
            if not self._meter.session.is_connected:
                raise RuntimeError("instrument session is not connected")
            idn = self._meter.idn
            if idn is None:
                raise RuntimeError("no successful *IDN? probe available")
            vendor, model, serial, fw = _idn(idn)
            stb = self.status_byte()
            ese = self.standard_event_enable()
            sre = self.service_request_enable()
            op = StatusBank(self.condition("operation"), self.enable("operation"))
            quest = StatusBank(self.condition("questionable"), self.enable("questionable"))
            ver = self._client.query("SYSTem:VERSion?").strip() if include_system else None
            terminals = self._client.query("ROUTe:TERMinals?").strip() if include_system else None
            if include_memory:
                volatile_count = self._meter.acquisition.volatile_count()
                nvm_count = self._meter.acquisition.nvm_count()
            else:
                volatile_count = nvm_count = None
            return DiagnosticSnapshot(
                received_at_utc=datetime.now(timezone.utc),
                idn_raw=idn, manufacturer=vendor, model=model, serial=serial,
                firmware=fw, connected=self._meter.session.is_connected,
                transport_type=type(self._meter.transport).__name__,
                status_byte=stb, standard_event_enable=ese,
                service_request_enable=sre, operation=op,
                questionable=quest, scpi_version=ver,
                terminal_selection=terminals,
                volatile_points=volatile_count, nvm_points=nvm_count,
            )

    def operation_complete(self, *, timeout_s: float = 30.0) -> bool:
        """Explicit *OPC? synchronization; never used in connect/snapshot."""
        deadline = _deadline(timeout_s)
        with self._meter.session.operation_lock():
            value = _int_reply(self._client.query("*OPC?", timeout_s=deadline),
                               maximum=1, name="OPC")
            return value == 1

    def self_test(self, *, confirm: bool = False, timeout_s: float = 120.0) -> int:
        """Explicit potentially disruptive *TST?; NEVER automatic."""
        if confirm is not True:
            raise PermissionError("self-test may disrupt measurements; confirm=True required")
        deadline = _deadline(timeout_s)
        with self._meter.session.operation_lock():
            self._meter.recovery.require_reconciled("explicit self-test")
            # Status of any prior acquisition becomes unknown after a self-test.
            self._meter.measurement.invalidate()
            self._meter.acquisition.reset_on_close()
            return _int_reply(self._client.query("*TST?", timeout_s=deadline),
                              maximum=32767, name="self-test")
