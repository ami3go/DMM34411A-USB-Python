"""Model-specific 34411A volatile acquisition and nonvolatile reading storage.

All SCPI I/O is serialized through scpi-driver-core's ScpiClient and session.
No constructor, start, close, timeout-retry or recovery path erases NVM.
Hardware-specific semantics require operator-authorized HIL qualification.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass
from collections.abc import Callable
from .models import MeasurementFunction as F

from scpi_driver_core import ConfigurationError, UnsupportedOperationError

VOLATILE_MEMORY_POINTS = 1_000_000
NONVOLATILE_MEMORY_POINTS = 50_000
ACQUISITION_TIMEOUT_S = 60.0
READBACK_TIMEOUT_S = 60.0
MAX_SINGLE_VOLATILE_READ = 20_000

class AcquisitionState(str, Enum):
    IDLE = "idle"
    CONFIGURED = "configured"
    ARMED = "armed"
    COMPLETE = "complete"
    ABORTED = "aborted"
    FAULTED = "faulted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AcquisitionProgress:
    """Host observation; state is local, not a firmware-confirmed status."""
    acquired: int
    target: int
    state: AcquisitionState
    trigger_source: str
    trigger_count: int
    samples_per_trigger: int
    pretrigger_count: int
    observed_at_utc: datetime


_INTERNAL_SUPPORTED = frozenset({
    F.DC_VOLTAGE, F.AC_VOLTAGE, F.DC_CURRENT, F.AC_CURRENT,
    F.RESISTANCE_2W, F.RESISTANCE_4W,
})
_INTERNAL_LIMITS = {
    F.DC_VOLTAGE: 1000.0,
    F.AC_VOLTAGE: 750.0,
    F.DC_CURRENT: 3.0,
    F.AC_CURRENT: 3.0,
    F.RESISTANCE_2W: 1.0e9,
    F.RESISTANCE_4W: 1.0e9,
}



def _count(value: int, maximum: int, name: str) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ConfigurationError(f"{name} must be an integer in [1, {maximum}]")
    return value


def _seconds(value: float | None, name: str, *, zero: bool = False) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ConfigurationError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ConfigurationError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")
    return value


def _source(source: str) -> str:
    if not isinstance(source, str):
        raise ConfigurationError("trigger_source must be IMMEDIATE, EXTERNAL, BUS or INTERNAL")
    try:
        return {
            "IMMEDIATE": "IMMediate",
            "IMM": "IMMediate",
            "EXTERNAL": "EXTernal",
            "EXT": "EXTernal",
            "BUS": "BUS",
            "INTERNAL": "INTernal",
            "INT": "INTernal",
        }[source.strip().upper()]
    except KeyError as exc:
        raise ConfigurationError("trigger_source must be IMMEDIATE, EXTERNAL, or BUS") from exc


def _timeout_seconds(timeout_ms: int | float) -> float:
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, (int, float)):
        raise ConfigurationError("timeout_ms must be a positive finite number")
    value = float(timeout_ms)
    if not math.isfinite(value) or value <= 0:
        raise ConfigurationError("timeout_ms must be a positive finite number")
    return value / 1000.0


class AcquisitionController:
    """High-level finite acquisition, stored reading count and guarded NVM.

    Memory commands are intentionally *not* retried on communication errors.
    Existing NVM prevents another copy, including overwrite=True, until
    firmware-specific overwrite/append semantics are HIL-qualified.
    """

    def __init__(self, meter: object) -> None:
        self._meter = meter
        self._target: int | None = None
        self._log_target: int | None = None
        self._sample_interval_s: float | None = None
        self._source = "IMMediate"
        self._completed = False
        self._state = AcquisitionState.IDLE
        self._triggers = 1
        self._samples_per_trigger: int | None = None
        self._pretrigger_count = 0

    @property
    def client(self):
        return self._meter.client

    @property
    def state(self) -> AcquisitionState:
        """Locally inferred state; not guaranteed to mirror external controllers."""
        return self._state

    def reset_on_close(self) -> None:
        self._target = None
        self._log_target = None
        self._sample_interval_s = None
        self._completed = False
        self._state = AcquisitionState.IDLE
        self._triggers = 1
        self._samples_per_trigger = None
        self._pretrigger_count = 0

    def _require_34411a(self) -> None:
        idn = self._meter.idn
        parts = idn.split(",") if isinstance(idn, str) else []
        if len(parts) < 2 or parts[1].strip().upper() != "34411A":
            raise UnsupportedOperationError(
                "internal/pretrigger acquisition requires *IDN?-verified 34411A"
            )

    def _active_function(self) -> F:
        active = self._meter.measurement._active
        if active is None or self._meter.measurement._generation != self._meter.session.generation:
            raise RuntimeError("explicitly configure typed measurement before advanced triggering")
        return active.function

    def _level(self, value: float) -> str:
        self._require_34411a()
        function = self._active_function()
        if function not in _INTERNAL_SUPPORTED:
            raise UnsupportedOperationError(
                "internal trigger supports only AC/DC voltage/current and 2-/4-wire ohms"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigurationError("trigger level must be a finite number")
        number = float(value)
        maximum = _INTERNAL_LIMITS[function]
        if not math.isfinite(number) or abs(number) > maximum or (
            function in (F.RESISTANCE_2W, F.RESISTANCE_4W) and number < 0
        ):
            raise ConfigurationError("trigger level outside conservative instrument function bounds")
        return f"{number:.12g}"

    @staticmethod
    def _slope(slope: str) -> str:
        if not isinstance(slope, str) or slope not in ("POS", "NEG"):
            raise ConfigurationError("trigger slope must be POS or NEG")
        return slope

    def set_level_trigger(self, level: float, slope: str = "POS") -> None:
        """Set explicit 34411A internal crossing trigger without arming it."""
        token = self._level(level)
        direction = self._slope(slope)
        if self._state is not AcquisitionState.CONFIGURED:
            raise RuntimeError("configure acquisition before selecting level trigger")
        with self._meter.session.operation_lock():
            try:
                self.client.write(f"TRIGger:LEVel {token}")
                self.client.write(f"TRIGger:SLOPe {direction}")
                self.client.write("TRIGger:SOURce INTernal")
            except Exception:
                self._state = AcquisitionState.UNKNOWN
                raise
        self._source = "INTernal"

    def set_trigger_output_slope(self, slope: str) -> None:
        """Explicit external trigger-output polarity; requires wired HIL qualification."""
        direction = self._slope(slope)
        if self._state in (AcquisitionState.ARMED, AcquisitionState.UNKNOWN):
            raise RuntimeError("do not change trigger output while armed/unknown")
        with self._meter.session.operation_lock():
            self.client.write(f"OUTPut:TRIGger:SLOPe {direction}")

    def trigger_settings_raw(self) -> dict[str, str]:
        """Non-destructive readback. No status/event clearing or trigger."""
        with self._meter.session.operation_lock():
            return {
                "source": self.client.query("TRIGger:SOURce?").strip(),
                "trigger_count": self.client.query("TRIGger:COUNt?").strip(),
                "sample_count": self.client.query("SAMPle:COUNt?").strip(),
                "pretrigger_count": self.client.query("SAMPle:COUNt:PRETrigger?").strip(),
            }

    def progress_snapshot(self) -> AcquisitionProgress:
        """One bounded point count observation with local lifecycle state."""
        if self._target is None or self._samples_per_trigger is None:
            raise RuntimeError("configure acquisition before checking progress")
        count = self.volatile_count()
        return AcquisitionProgress(
            acquired=count, target=self._target, state=self._state,
            trigger_source=self._source, trigger_count=self._triggers,
            samples_per_trigger=self._samples_per_trigger,
            pretrigger_count=self._pretrigger_count,
            observed_at_utc=datetime.now(timezone.utc),
        )

    def configure(
        self,
        points: int,
        *,
        sample_interval_seconds: float | None = None,
        trigger_source: str = "IMMEDIATE",
        trigger_delay_seconds: float | None = None,
        persist: bool = False,
        trigger_count: int = 1,
        pretrigger_count: int = 0,
        trigger_level: float | None = None,
        trigger_slope: str = "POS",
    ) -> int:
        if self._state in (AcquisitionState.ARMED, AcquisitionState.UNKNOWN):
            raise RuntimeError("acquisition is armed/unknown; explicitly abort before reconfigure")
        limit = NONVOLATILE_MEMORY_POINTS if persist else VOLATILE_MEMORY_POINTS
        points = _count(points, limit, "sample count")
        count = _count(trigger_count, limit, "trigger_count")
        total = points * count
        if total > limit:
            raise ConfigurationError(f"trigger_count * sample count exceeds {limit} reading capacity")
        if type(pretrigger_count) is not int or not 0 <= pretrigger_count < points:
            raise ConfigurationError("pretrigger_count must be an integer >=0 and < samples per trigger")
        interval = _seconds(sample_interval_seconds, "sample_interval_seconds")
        delay = _seconds(trigger_delay_seconds, "trigger_delay_seconds", zero=True)
        if delay is not None and delay > 3600:
            raise ConfigurationError("trigger delay may not exceed 3600 seconds")
        source = _source(trigger_source)
        slope = self._slope(trigger_slope)
        level = None
        if source == "INTernal":
            if trigger_level is None:
                raise ConfigurationError("INTERNAL trigger requires trigger_level")
            level = self._level(trigger_level)
        elif trigger_level is not None:
            raise ConfigurationError("trigger_level is valid only for INTERNAL trigger")
        if pretrigger_count:
            self._require_34411a()
            function = self._active_function()
            if function in (F.CONTINUITY, F.DIODE):
                raise UnsupportedOperationError("pretrigger not supported for diode or continuity")
            if source == "IMMediate":
                raise UnsupportedOperationError("pretrigger requires an event trigger, not IMMEDIATE")
        had_pretrigger = self._pretrigger_count > 0
        self.reset_on_close()
        # No implicit INIT, *RST, *CLS, data delete, or VISA clear.
        try:
            with self._meter.session.operation_lock():
                self.client.write(f"SAMPle:COUNt {points}")
                self.client.write(f"TRIGger:COUNt {count}")
                self.client.write(f"TRIGger:SOURce {source}")
                if level is not None:
                    self.client.write(f"TRIGger:LEVel {level}")
                    self.client.write(f"TRIGger:SLOPe {slope}")
                if pretrigger_count or had_pretrigger:
                    # Explicitly remove a prior pretrigger setup on this same session.
                    self.client.write(f"SAMPle:COUNt:PRETrigger {pretrigger_count}")
                if interval is None:
                    self.client.write("SAMPle:SOURce AUTO")
                else:
                    self.client.write("SAMPle:SOURce TIMer")
                    self.client.write(f"SAMPle:TIMer {interval:.12g}")
                if delay is None:
                    self.client.write("TRIGger:DELay:AUTO ON")
                else:
                    self.client.write("TRIGger:DELay:AUTO OFF")
                    self.client.write(f"TRIGger:DELay {delay:.12g}")
        except Exception:
            self._state = AcquisitionState.UNKNOWN
            raise
        self._target = total
        self._log_target = total if persist else None
        self._sample_interval_s = interval
        self._source = source
        self._triggers = count
        self._samples_per_trigger = points
        self._pretrigger_count = pretrigger_count
        self._state = AcquisitionState.CONFIGURED
        # Backward-compatible return: per-trigger count, not multiplied total.
        return points

    def initiate(self, *, log: bool = False, clear_existing: bool = False) -> None:
        if self._target is None or (log and self._log_target is None):
            raise RuntimeError("configure an acquisition before starting it")
        if clear_existing:
            raise PermissionError(
                "automatic NVM deletion is forbidden: use delete_nvm(confirm=True) explicitly"
            )
        if log and self.nvm_count() != 0:
            raise FileExistsError("NVM contains readings; export them and delete explicitly first")
        if self._state is not AcquisitionState.CONFIGURED:
            raise RuntimeError("acquisition must be configured (not armed/unknown) to initiate")
        self._completed = False
        self._state = AcquisitionState.UNKNOWN  # INIT may succeed even if reply is lost.
        self.client.write("INITiate")
        self._state = AcquisitionState.ARMED

    def send_bus_trigger(self) -> None:
        if self._target is None or self._source != "BUS":
            raise ConfigurationError("bus trigger requires an acquisition configured with BUS")
        self.client.write("*TRG")

    def abort(self) -> None:
        # ABORt may have taken effect despite timeout; never automatically retry.
        self._state = AcquisitionState.UNKNOWN
        self.client.write("ABORt")
        self._completed = False
        self._state = AcquisitionState.ABORTED

    def abort_and_snapshot(self) -> AcquisitionProgress:
        """Operator-controlled STOP plus partial-count metadata.

        The count is read only after ABORt succeeded. If read fails, state
        becomes UNKNOWN; the operator must reconcile the instrument.
        """
        self.abort()
        try:
            return self.progress_snapshot()
        except Exception:
            self._state = AcquisitionState.UNKNOWN
            raise

    def _point_count(self, memory: str, maximum: int, timeout_s: float | None = None) -> int:
        response = self.client.query(f"DATA:POINts? {memory}", timeout_s=timeout_s).strip()
        try:
            number = float(response)
        except ValueError as exc:
            raise ValueError(f"invalid {memory} count: {response!r}") from exc
        if not math.isfinite(number) or number < 0 or number > maximum or not number.is_integer():
            raise ValueError(f"invalid {memory} count: {response!r}")
        return int(number)

    def volatile_count(self, timeout_s: float | None = None) -> int:
        return self._point_count("RDG_STORE", VOLATILE_MEMORY_POINTS, timeout_s=timeout_s)

    def nvm_count(self) -> int:
        return self._point_count("NVMEM", NONVOLATILE_MEMORY_POINTS)

    def progress(self) -> dict[str, int | bool]:
        if self._target is None:
            raise RuntimeError("no acquisition configured")
        acquired = self.volatile_count()
        return {"acquired": acquired, "target": self._target, "complete": acquired >= self._target}

    def wait_complete(self, timeout_s: float | None = None, poll_interval_s: float = 0.1) -> int:
        if self._target is None:
            raise RuntimeError("no acquisition configured")
        poll = _seconds(poll_interval_s, "poll_interval_s")
        assert poll is not None
        if timeout_s is None:
            timeout_s = ACQUISITION_TIMEOUT_S + (
                self._target * self._sample_interval_s
                if self._sample_interval_s is not None else 0
            )
        budget = _seconds(timeout_s, "timeout_s")
        assert budget is not None
        deadline = time.monotonic() + budget
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._state = AcquisitionState.UNKNOWN
                raise TimeoutError("acquisition timed out; instrument may still be armed")
            # Request uses a finite remaining budget; each poll is individually bounded.
            try:
                count = self.volatile_count(timeout_s=remaining)
            except Exception:
                self._state = AcquisitionState.UNKNOWN
                raise
            if count < 0 or count > VOLATILE_MEMORY_POINTS:
                raise ValueError(f"invalid volatile point count: {count}")
            if count >= self._target:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._state = AcquisitionState.UNKNOWN
                    raise TimeoutError("acquisition completion timed out")
                try:
                    if self.client.query("*OPC?", timeout_s=remaining).strip() != "1":
                        self._state = AcquisitionState.FAULTED
                        raise RuntimeError("instrument did not acknowledge operation completion")
                except Exception:
                    if self._state is not AcquisitionState.FAULTED:
                        self._state = AcquisitionState.UNKNOWN
                    raise
                self._completed = True
                self._state = AcquisitionState.COMPLETE
                return count
            time.sleep(min(poll, max(0.0, deadline - time.monotonic())))

    def _read_ascii(self, command: str, expected: int, timeout_s: float) -> list[float]:
        if expected == 0:
            return []
        # Read-back format is a persistent instrument setting. Restore the
        # operator's previous format even if the read raises.
        with self._meter.session.operation_lock():
            previous = self.client.query("FORMat:DATA?").strip()
            if not previous or "\n" in previous or "\r" in previous:
                raise ValueError("invalid instrument data format reply")
            change = not previous.upper().startswith("ASC")
            if change:
                self.client.write("FORMat:DATA ASCii")
            try:
                values = self.client.query_csv_floats(command, timeout_s=timeout_s)
                if len(values) != expected:
                    self._meter.transport.invalidate()
                    raise ValueError(
                        f"reading count mismatch for {command}: expected {expected}, got {len(values)}"
                    )
                return values
            finally:
                if change and self._meter.session.is_connected:
                    self.client.write(f"FORMat:DATA {previous}")

    def read_volatile(self, *, erase: bool = False,
                      max_points: int | None = None,
                      timeout_s: float = READBACK_TIMEOUT_S) -> list[float]:
        budget = _seconds(timeout_s, "timeout_s")
        assert budget is not None
        if erase:
            if max_points is None:
                raise ConfigurationError("destructive read requires explicit max_points")
            requested = _count(max_points, MAX_SINGLE_VOLATILE_READ, "max_points")
            count = self.volatile_count()
            if requested > count:
                raise ValueError("max_points exceeds available volatile readings")
            # DATA:REMove? is destructive. Never automatically retry after I/O failure.
            return self._read_ascii(f"DATA:REMove? {requested}", requested, budget)
        if max_points is not None:
            raise ConfigurationError("max_points is only supported on explicit destructive reads")
        count = self.volatile_count()
        if count > MAX_SINGLE_VOLATILE_READ:
            raise ValueError("non-destructive FETCh? exceeds safe response budget")
        # FETCh? retention semantics require model-specific HIL evidence.
        return self._read_ascii("FETCh?", count, budget)

    def copy_to_nvm(self, *, overwrite: bool = False,
                    timeout_s: float = ACQUISITION_TIMEOUT_S) -> int:
        budget = _seconds(timeout_s, "timeout_s")
        assert budget is not None
        if self._log_target is None or self._target is None:
            raise RuntimeError("configure a data log before saving to NVM")
        if not self._completed:
            raise RuntimeError("acquisition must pass wait_complete before NVM copy")
        with self._meter.session.operation_lock():
            available = self.volatile_count()
            if available != self._log_target:
                raise RuntimeError(f"incomplete/changed acquisition: {available}/{self._log_target}")
            existing = self.nvm_count()
            if existing != 0:
                if overwrite:
                    raise UnsupportedOperationError(
                        "NVM overwrite is not enabled until firmware behavior is HIL-qualified"
                    )
                raise FileExistsError("NVM contains readings; export and explicitly delete first")
            if self.client.query("*OPC?", timeout_s=budget).strip() != "1":
                raise RuntimeError("instrument did not complete acquisition")
            self.client.write("DATA:COPY NVMEM, RDG_STORE", timeout_s=budget)
            if self.client.query("*OPC?", timeout_s=budget).strip() != "1":
                raise RuntimeError("instrument did not complete NVM copy")
            stored = self.nvm_count()
            if stored != self._log_target:
                raise RuntimeError(f"NVM copy count mismatch: {stored}/{self._log_target}")
            return stored

    def read_nvm(self, timeout_s: float = READBACK_TIMEOUT_S) -> list[float]:
        budget = _seconds(timeout_s, "timeout_s")
        assert budget is not None
        with self._meter.session.operation_lock():
            expected = self.nvm_count()
            values = self._read_ascii("DATA:DATA? NVMEM", expected, budget)
            if self.nvm_count() != expected:
                raise RuntimeError("NVM count changed during readback")
            return values

    def delete_nvm(self, *, confirm: bool = False) -> None:
        if confirm is not True:
            raise PermissionError("NVM deletion requires confirm=True")
        with self._meter.session.operation_lock():
            self.client.write("DATA:DELete NVMEM")
            if self.nvm_count() != 0:
                raise RuntimeError("NVM deletion not confirmed by instrument")
