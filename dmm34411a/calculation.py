"""34411A CALCulate math, statistics, limits and SENSe per-function null.

No operations occur at connect/close. Math mode selection is exclusive; an
active different mode is preserved unless replace=True. Enable-statistics,
function changes and explicit CALCulate:AVERage:CLEar can destroy accumulated
statistics. No automatic reset, error clear, or measurement is performed.

Keysight 34410A/11A Command Quick Reference 9018-61141, CALCulate/SENSe;
Keysight 34410A/11A User's Guide, math functions pp. 63-67.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from scpi_driver_core import ConfigurationError, UnsupportedOperationError
from .models import MeasurementFunction as F


class MathMode(str, Enum):
    NULL = "NULL"  # legacy; not exposed as enable API
    STATISTICS = "AVERage"
    DB = "DB"
    DBM = "DBM"
    LIMITS = "LIMit"


@dataclass(frozen=True)
class Statistics:
    count: int
    mean: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    standard_deviation: float | None = None
    peak_to_peak: float | None = None


@dataclass(frozen=True)
class Limits:
    lower: float
    upper: float


_NULL_PATHS = {
    F.DC_VOLTAGE: "VOLTage:DC",
    F.AC_VOLTAGE: "VOLTage:AC",
    F.DC_CURRENT: "CURRent:DC",
    F.AC_CURRENT: "CURRent:AC",
    F.RESISTANCE_2W: "RESistance",
    F.RESISTANCE_4W: "FRESistance",
    F.FREQUENCY: "FREQuency",
    F.PERIOD: "PERiod",
    F.CAPACITANCE: "CAPacitance",
    F.TEMPERATURE: "TEMPerature",
}
_DBM_RESISTANCES = frozenset((
    50, 75, 93, 110, 124, 125, 135, 150,
    250, 300, 500, 600, 800, 900, 1000, 1200, 8000,
))
_MODES = {
    "NULL": MathMode.NULL,
    "AVER": MathMode.STATISTICS, "AVERAGE": MathMode.STATISTICS,
    "DB": MathMode.DB, "DBM": MathMode.DBM,
    "LIM": MathMode.LIMITS, "LIMIT": MathMode.LIMITS,
}


def _float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{name} must be a finite number")
    try:
        x = float(value)
    except (ValueError, OverflowError) as exc:
        raise ConfigurationError(f"{name} must be finite") from exc
    if not math.isfinite(x) or abs(x) > 1.0e37:
        raise ConfigurationError(f"{name} must be finite and within supported magnitude")
    return x


def _parse_float(text: str, name: str) -> float:
    try:
        result = float(text.strip())
    except ValueError as exc:
        raise ValueError(f"invalid {name} response: {text!r}") from exc
    if not math.isfinite(result) or abs(result) >= 9.9e37:
        raise ValueError(f"invalid/overrange {name} response: {text!r}")
    return result


def _parse_bool(raw: str) -> bool:
    if raw.strip() in ("1", "ON"):
        return True
    if raw.strip() in ("0", "OFF"):
        return False
    raise ValueError(f"invalid CALCulate state: {raw!r}")


def _parse_count(raw: str) -> int:
    n = _parse_float(raw, "statistics count")
    if n < 0 or n > 1e12 or not n.is_integer():
        raise ValueError(f"invalid statistics count: {raw!r}")
    return int(n)


class MathController:
    """Instrument-backed math with non-destructive read-only status queries."""

    def __init__(self, meter: object) -> None:
        self._meter = meter

    @property
    def _client(self):
        return self._meter.client

    def _mode(self) -> MathMode:
        raw = self._client.query("CALCulate:FUNCtion?").strip().strip('"').upper()
        try:
            return _MODES[raw]
        except KeyError as exc:
            raise ValueError(f"unrecognized CALCulate mode: {raw!r}") from exc

    def selected_mode(self) -> MathMode:
        return self._mode()

    def enabled(self) -> bool:
        return _parse_bool(self._client.query("CALCulate:STATe?"))

    def _require_measurement(self, *, voltage: bool = False) -> F:
        configured = self._meter.measurement._active
        if configured is None or (
            self._meter.measurement._generation != self._meter.session.generation
        ):
            raise RuntimeError("explicitly configure a typed measurement function first")
        function = configured.function
        if function not in _NULL_PATHS:
            raise UnsupportedOperationError("math not supported for diode or continuity")
        if voltage and function not in (F.DC_VOLTAGE, F.AC_VOLTAGE):
            raise UnsupportedOperationError("dB/dBm are voltage-only measurement functions")
        return function

    def _preflight(self, new_mode: MathMode, replace: bool) -> bool:
        """Return True if the requested mode is already active; no writes."""
        if type(replace) is not bool:
            raise ConfigurationError("replace must be bool")
        state = self.enabled()
        mode = self._mode()
        if state and mode is not new_mode and not replace:
            raise FileExistsError(
                f"instrument math {mode.name} already enabled; use replace=True explicitly"
            )
        return state and mode is new_mode

    def _activate(self, new_mode: MathMode, already_active: bool) -> None:
        if already_active:
            return  # Especially important: enabling statistics can clear accumulated data.
        self._client.write(f"CALCulate:FUNCtion {new_mode.value}")
        self._client.write("CALCulate:STATe ON")

    def disable(self) -> None:
        """Disable currently selected math without resetting other settings."""
        self._client.write("CALCulate:STATe OFF")

    def enable_statistics(self, *, replace: bool = False) -> None:
        self._require_measurement()
        with self._meter.session.operation_lock():
            self._activate(MathMode.STATISTICS, self._preflight(MathMode.STATISTICS, replace))

    def clear_statistics(self, *, confirm: bool = False) -> None:
        if confirm is not True:
            raise PermissionError("clearing accumulated statistics requires confirm=True")
        with self._meter.session.operation_lock():
            if not self.enabled() or self._mode() is not MathMode.STATISTICS:
                raise RuntimeError("statistics mode is not currently enabled")
            self._client.write("CALCulate:AVERage:CLEar")

    def read_statistics(self) -> Statistics:
        with self._meter.session.operation_lock():
            if not self.enabled() or self._mode() is not MathMode.STATISTICS:
                raise RuntimeError("statistics mode is not currently enabled")
            count = _parse_count(self._client.query("CALCulate:AVERage:COUNt?"))
            if count == 0:
                return Statistics(count=0)
            def get(field: str) -> float:
                return _parse_float(
                    self._client.query(f"CALCulate:AVERage:{field}?"),
                    f"statistics {field}"
                )
            return Statistics(
                count=count,
                mean=get("AVERage"), minimum=get("MINimum"),
                maximum=get("MAXimum"), standard_deviation=get("SDEViation"),
                peak_to_peak=get("PTPeak"),
            )

    def configure_db(self, reference: float, *, replace: bool = False) -> None:
        self._require_measurement(voltage=True)
        ref = _float(reference, "dB reference")
        if ref <= 0:
            raise ConfigurationError("dB reference must be positive")
        with self._meter.session.operation_lock():
            active = self._preflight(MathMode.DB, replace)
            self._client.write(f"CALCulate:DB:REFerence {ref:.12g}")
            self._activate(MathMode.DB, active)

    def get_db_reference(self) -> float:
        return _parse_float(self._client.query("CALCulate:DB:REFerence?"), "dB reference")

    def configure_dbm(self, reference_ohms: int = 600, *, replace: bool = False) -> None:
        self._require_measurement(voltage=True)
        if type(reference_ohms) is not int or reference_ohms not in _DBM_RESISTANCES:
            raise ConfigurationError("dBm reference must be a documented resistance in ohms")
        with self._meter.session.operation_lock():
            active = self._preflight(MathMode.DBM, replace)
            self._client.write(f"CALCulate:DBM:REFerence {reference_ohms}")
            self._activate(MathMode.DBM, active)

    def get_dbm_reference(self) -> float:
        return _parse_float(self._client.query("CALCulate:DBM:REFerence?"), "dBm reference")

    def configure_limits(self, lower: float, upper: float, *, replace: bool = False) -> None:
        self._require_measurement()
        lo = _float(lower, "lower limit")
        hi = _float(upper, "upper limit")
        if lo >= hi:
            raise ConfigurationError("lower limit must be strictly below upper limit")
        with self._meter.session.operation_lock():
            active = self._preflight(MathMode.LIMITS, replace)
            self._client.write(f"CALCulate:LIMit:LOWer {lo:.12g}")
            self._client.write(f"CALCulate:LIMit:UPPer {hi:.12g}")
            self._activate(MathMode.LIMITS, active)

    def get_limits(self) -> Limits:
        with self._meter.session.operation_lock():
            lo = _parse_float(self._client.query("CALCulate:LIMit:LOWer?"), "lower limit")
            hi = _parse_float(self._client.query("CALCulate:LIMit:UPPer?"), "upper limit")
            if lo >= hi:
                raise ValueError("invalid instrument limit ordering")
            return Limits(lo, hi)

    def evaluate_limits(self, value: float) -> bool:
        """HOST-SIDE limit comparison; does not claim a DMM limit-status query."""
        n = _float(value, "reading")
        settings = self.get_limits()
        return settings.lower <= n <= settings.upper

    @staticmethod
    def _null_path(function: F) -> str:
        if not isinstance(function, F) or function not in _NULL_PATHS:
            raise UnsupportedOperationError("per-function null unavailable for this mode")
        return f"SENSe:{_NULL_PATHS[function]}:NULL"

    def set_null(self, function: F, offset: float, *, enabled: bool = True) -> None:
        prefix = self._null_path(function)
        n = _float(offset, "null offset")
        if type(enabled) is not bool:
            raise ConfigurationError("enabled must be bool")
        with self._meter.session.operation_lock():
            self._client.write(f"{prefix}:VALue {n:.12g}")
            self._client.write(f"{prefix}:STATe {'ON' if enabled else 'OFF'}")

    def get_null(self, function: F) -> tuple[float, bool]:
        prefix = self._null_path(function)
        with self._meter.session.operation_lock():
            value = _parse_float(self._client.query(f"{prefix}:VALue?"), "null offset")
            raw = self._client.query(f"{prefix}:STATe?").strip()
            if raw not in ("0", "1"):
                raise ValueError(f"invalid null state: {raw!r}")
            return (value, raw == "1")
