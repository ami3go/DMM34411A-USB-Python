"""34411A function-aware metrology settings via scpi-driver-core.

Model-specific SENSe commands from Keysight 34410A/11A User's Guide and
Keysight SCPI Comparison Guide. Setters affect the named instrument function;
they never switch the active measurement function or initiate a reading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scpi_driver_core import ConfigurationError, UnsupportedOperationError

from .models import MeasurementFunction

if TYPE_CHECKING:
    from .driver import DMM_34411A

# Voltage/current/resistance/capacitance ranges in base SI units.
# The instrument may round a requested value up to the next available range;
# get_range() reports the actual instrument-selected range.
_RANGE_LIMITS: dict[MeasurementFunction, tuple[float, float]] = {
    MeasurementFunction.DC_VOLTAGE: (0.1, 1000.0),
    MeasurementFunction.AC_VOLTAGE: (0.1, 750.0),
    MeasurementFunction.DC_CURRENT: (0.0001, 3.0),
    MeasurementFunction.AC_CURRENT: (0.0001, 3.0),
    MeasurementFunction.RESISTANCE_2W: (100.0, 1.0e9),
    MeasurementFunction.RESISTANCE_4W: (100.0, 1.0e9),
    MeasurementFunction.CAPACITANCE: (1.0e-9, 1.0e-2),
}
_SENSE: dict[MeasurementFunction, str] = {
    MeasurementFunction.DC_VOLTAGE: "SENSe:VOLTage:DC",
    MeasurementFunction.AC_VOLTAGE: "SENSe:VOLTage:AC",
    MeasurementFunction.DC_CURRENT: "SENSe:CURRent:DC",
    MeasurementFunction.AC_CURRENT: "SENSe:CURRent:AC",
    MeasurementFunction.RESISTANCE_2W: "SENSe:RESistance",
    MeasurementFunction.RESISTANCE_4W: "SENSe:FRESistance",
    MeasurementFunction.CAPACITANCE: "SENSe:CAPacitance",
    MeasurementFunction.FREQUENCY: "SENSe:FREQuency",
    MeasurementFunction.PERIOD: "SENSe:PERiod",
    MeasurementFunction.TEMPERATURE: "SENSe:TEMPerature",
}
_RESOLUTION = frozenset({
    MeasurementFunction.DC_VOLTAGE, MeasurementFunction.AC_VOLTAGE,
    MeasurementFunction.DC_CURRENT, MeasurementFunction.AC_CURRENT,
    MeasurementFunction.RESISTANCE_2W, MeasurementFunction.RESISTANCE_4W,
})
_INTEGRATION = frozenset({
    MeasurementFunction.DC_VOLTAGE, MeasurementFunction.DC_CURRENT,
    MeasurementFunction.RESISTANCE_2W, MeasurementFunction.RESISTANCE_4W,
    MeasurementFunction.TEMPERATURE,
})
_AUTOZERO = frozenset({
    MeasurementFunction.DC_VOLTAGE, MeasurementFunction.DC_CURRENT,
    MeasurementFunction.RESISTANCE_2W, MeasurementFunction.TEMPERATURE,
})
_AC = frozenset({MeasurementFunction.AC_VOLTAGE, MeasurementFunction.AC_CURRENT})
_GATE = frozenset({MeasurementFunction.FREQUENCY, MeasurementFunction.PERIOD})
_OHMS = frozenset({MeasurementFunction.RESISTANCE_2W, MeasurementFunction.RESISTANCE_4W})
_NPLC = (0.001, 0.002, 0.006, 0.02, 0.06, 0.2, 1.0, 2.0, 10.0, 100.0)
_GATE_VALUES = (0.001, 0.01, 0.1, 1.0)
_SELECTORS = frozenset({"MIN", "MAX", "DEF"})
_BANDWIDTH = (3, 20, 200)


@dataclass(frozen=True)
class MetrologySnapshot:
    """Read-only live instrument settings; no hidden mode change."""

    function: MeasurementFunction
    range_value: float | None = None
    autorange: bool | None = None
    resolution: float | None = None
    nplc: float | None = None
    aperture_seconds: float | None = None
    aperture_enabled: bool | None = None
    autozero: bool | None = None
    ac_bandwidth_hz: float | None = None
    gate_time_seconds: float | None = None
    offset_compensated: bool | None = None
    input_impedance_auto: bool | None = None


def _function(function: MeasurementFunction, supported: object) -> str:
    if not isinstance(function, MeasurementFunction) or function not in supported:
        raise UnsupportedOperationError(
            "setting is unsupported for this measurement function"
        )
    return _SENSE[function]


def _numeric(value: float, *, name: str, minimum: float, maximum: float) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{name} must be a finite numeric value")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ConfigurationError(f"{name} cannot be represented as a finite float") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ConfigurationError(f"{name} must be finite and between {minimum:g} and {maximum:g}")
    return f"{number:.12g}"


def _choice(value: object, *, allowed: frozenset[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ConfigurationError(f"{name} must be one of {sorted(allowed)}")
    return value


def _flag(enabled: bool) -> str:
    if type(enabled) is not bool:
        raise ConfigurationError("enabled must be a bool")
    return "ON" if enabled else "OFF"


def _parse_float(response: str, name: str) -> float:
    try:
        n = float(response.strip())
    except ValueError as exc:
        raise ValueError(f"invalid {name} query response: {response!r}") from exc
    if not math.isfinite(n):
        raise ValueError(f"nonfinite {name} query response: {response!r}")
    return n


def _parse_flag(response: str, name: str) -> bool:
    val = response.strip().upper()
    if val == "ON":
        return True
    if val == "OFF":
        return False
    try:
        numeric = float(val)
    except ValueError as exc:
        raise ValueError(f"invalid {name} flag response: {response!r}") from exc
    if numeric == 1:
        return True
    if numeric == 0:
        return False
    raise ValueError(f"invalid {name} flag response: {response!r}")


class MetrologyController:
    """Instrument-backed per-function metrology settings.

    Setters do not select a function, trigger a reading, clear errors, or
    overwrite NVM. Readback is always from the instrument, not a cache.
    """

    def __init__(self, meter: DMM_34411A) -> None:
        self._meter = meter

    def _is_34411a(self) -> bool:
        idn = self._meter.idn
        return bool(idn and len(idn.split(",")) > 1 and idn.split(",")[1].strip().upper() == "34411A")

    def _require_fast_model(self) -> None:
        if not self._is_34411a():
            raise UnsupportedOperationError(
                "20 us aperture and 0.001/0.002 NPLC require verified 34411A identity"
            )

    def _write(self, scpi: str) -> None:
        self._meter.client.write(scpi)

    def _float_query(self, scpi: str) -> float:
        return _parse_float(self._meter.client.query(scpi), scpi)

    def _flag_query(self, scpi: str) -> bool:
        return _parse_flag(self._meter.client.query(scpi), scpi)

    def set_range(self, function: MeasurementFunction, value: float | str) -> None:
        prefix = _function(function, _RANGE_LIMITS)
        if isinstance(value, str):
            selected = _choice(value, allowed=frozenset({"AUTO", "MIN", "MAX"}), name="range")
        else:
            lo, hi = _RANGE_LIMITS[function]
            selected = _numeric(value, name="range", minimum=lo, maximum=hi)
        self._write(f"{prefix}:RANGe {selected}")

    def get_range(self, function: MeasurementFunction) -> float:
        return self._float_query(f"{_function(function, _RANGE_LIMITS)}:RANGe?")

    def set_autorange(self, function: MeasurementFunction, enabled: bool) -> None:
        prefix = _function(function, _RANGE_LIMITS)
        self._write(f"{prefix}:RANGe:AUTO {_flag(enabled)}")

    def get_autorange(self, function: MeasurementFunction) -> bool:
        return self._flag_query(f"{_function(function, _RANGE_LIMITS)}:RANGe:AUTO?")

    def set_resolution(self, function: MeasurementFunction, value: float | str) -> None:
        prefix = _function(function, _RESOLUTION)
        if isinstance(value, str):
            selected = _choice(value, allowed=_SELECTORS, name="resolution")
        else:
            # Instrument rounds to an achievable resolution for selected range.
            # Reject clearly invalid values before any SCPI command.
            selected = _numeric(value, name="resolution", minimum=1e-12,
                                maximum=_RANGE_LIMITS[function][1])
        self._write(f"{prefix}:RESolution {selected}")

    def get_resolution(self, function: MeasurementFunction) -> float:
        return self._float_query(f"{_function(function, _RESOLUTION)}:RESolution?")

    def set_nplc(self, function: MeasurementFunction, value: float | str) -> None:
        prefix = _function(function, _INTEGRATION)
        if isinstance(value, str):
            selected = _choice(value, allowed=_SELECTORS, name="NPLC")
        else:
            selected = _numeric(value, name="NPLC", minimum=0.001, maximum=100)
            if float(value) not in _NPLC:
                raise ConfigurationError(f"NPLC must be one of {_NPLC}")
            if float(value) in (0.001, 0.002):
                self._require_fast_model()
        self._write(f"{prefix}:NPLC {selected}")

    def get_nplc(self, function: MeasurementFunction) -> float:
        return self._float_query(f"{_function(function, _INTEGRATION)}:NPLC?")

    def set_aperture(self, function: MeasurementFunction, seconds: float | str) -> None:
        prefix = _function(function, _INTEGRATION)
        if isinstance(seconds, str):
            selected = _choice(seconds, allowed=_SELECTORS, name="aperture")
        else:
            selected = _numeric(seconds, name="aperture", minimum=0.00002, maximum=1.0)
            if float(seconds) < 0.0001:
                self._require_fast_model()
        self._write(f"{prefix}:APERture {selected}")

    def get_aperture(self, function: MeasurementFunction) -> float:
        return self._float_query(f"{_function(function, _INTEGRATION)}:APERture?")

    def _aperture_enable_header(self, function: MeasurementFunction) -> str:
        prefix = _function(function, _INTEGRATION)
        # The Keysight SCPI comparison calls the FRESistance suffix ENABle,
        # whereas the other integration functions use ENABled.
        suffix = "ENABle" if function is MeasurementFunction.RESISTANCE_4W else "ENABled"
        return f"{prefix}:APERture:{suffix}"

    def set_aperture_enabled(self, function: MeasurementFunction, enabled: bool) -> None:
        header = self._aperture_enable_header(function)
        self._write(f"{header} {_flag(enabled)}")

    def get_aperture_enabled(self, function: MeasurementFunction) -> bool:
        return self._flag_query(f"{self._aperture_enable_header(function)}?")

    def set_autozero(
        self, function: MeasurementFunction, state: bool | str
    ) -> None:
        prefix = _function(function, _AUTOZERO)
        if state == "ONCE" and type(state) is str:
            flag = "ONCE"
        else:
            flag = _flag(state)
        self._write(f"{prefix}:ZERO:AUTO {flag}")

    def get_autozero(self, function: MeasurementFunction) -> bool:
        return self._flag_query(f"{_function(function, _AUTOZERO)}:ZERO:AUTO?")

    def set_ac_bandwidth(
        self, function: MeasurementFunction, hz: int | str
    ) -> None:
        prefix = _function(function, _AC)
        if isinstance(hz, str):
            selected = _choice(hz, allowed=_SELECTORS, name="AC bandwidth")
        elif type(hz) is int and hz in _BANDWIDTH:
            selected = str(hz)
        else:
            raise ConfigurationError(f"AC bandwidth must be 3, 20 or 200 Hz (or MIN/MAX/DEF)")
        self._write(f"{prefix}:BANDwidth {selected}")

    def get_ac_bandwidth(self, function: MeasurementFunction) -> float:
        return self._float_query(f"{_function(function, _AC)}:BANDwidth?")

    def set_gate_time(self, function: MeasurementFunction, seconds: float | str) -> None:
        prefix = _function(function, _GATE)
        if isinstance(seconds, str):
            selected = _choice(seconds, allowed=_SELECTORS, name="gate time")
        else:
            selected = _numeric(seconds, name="gate time", minimum=0.001, maximum=1)
            if float(seconds) not in _GATE_VALUES:
                raise ConfigurationError("gate time must be 0.001, 0.01, 0.1 or 1 seconds")
        self._write(f"{prefix}:APERture {selected}")

    def get_gate_time(self, function: MeasurementFunction) -> float:
        return self._float_query(f"{_function(function, _GATE)}:APERture?")

    def set_input_impedance_auto(self, enabled: bool) -> None:
        self._write(f"SENSe:VOLTage:DC:IMPedance:AUTO {_flag(enabled)}")

    def get_input_impedance_auto(self) -> bool:
        return self._flag_query("SENSe:VOLTage:DC:IMPedance:AUTO?")

    def set_offset_compensation(self, function: MeasurementFunction, enabled: bool) -> None:
        prefix = _function(function, _OHMS)
        flag = _flag(enabled)
        if enabled:
            # Offset compensation is effective only on low resistance ranges.
            # Autorange can move to an unsupported range after configuration.
            with self._meter.session.operation_lock():
                if self.get_autorange(function):
                    raise ConfigurationError(
                        "offset compensation requires fixed 100/1k/10k ohm range"
                    )
                selected_range = self.get_range(function)
                if not any(
                    math.isclose(selected_range, x, rel_tol=1e-6)
                    for x in (100, 1000, 10000)
                ):
                    raise ConfigurationError(
                        "offset compensation requires fixed 100/1k/10k ohm range"
                    )
                self._write(f"{prefix}:OCOMpensated {flag}")
        else:
            self._write(f"{prefix}:OCOMpensated {flag}")

    def get_offset_compensation(self, function: MeasurementFunction) -> bool:
        return self._flag_query(f"{_function(function, _OHMS)}:OCOMpensated?")

    def set_temperature_unit(self, unit: str) -> None:
        selected = _choice(unit, allowed=frozenset({"C", "F", "K"}), name="temperature unit")
        self._write(f"UNIT:TEMPerature {selected}")

    def get_temperature_unit(self) -> str:
        response = self._meter.client.query("UNIT:TEMPerature?").strip().upper()
        if response not in {"C", "F", "K", "CEL", "FAR"}:
            raise ValueError(f"unexpected temperature unit {response!r}")
        return {"CEL": "C", "FAR": "F"}.get(response, response)

    def snapshot(self, function: MeasurementFunction) -> MetrologySnapshot:
        """Read live metrology settings; never trust cached configuration.

        A mode-specific set of queries is issued. This does not switch the
        instrument function and may not be a coherent snapshot if a different
        host modifies settings concurrently.
        """
        _function(function, _SENSE)
        with self._meter.session.operation_lock():
            range_value = autorange = resolution = None
            nplc = aperture_seconds = aperture_enabled = autozero = None
            ac_bandwidth = gate_time = offset = input_z = None
            if function in _RANGE_LIMITS:
                range_value = self.get_range(function)
                autorange = self.get_autorange(function)
            if function in _RESOLUTION:
                resolution = self.get_resolution(function)
            if function in _INTEGRATION:
                nplc = self.get_nplc(function)
                aperture_seconds = self.get_aperture(function)
                aperture_enabled = self.get_aperture_enabled(function)
            if function in _AUTOZERO:
                autozero = self.get_autozero(function)
            if function in _AC:
                ac_bandwidth = self.get_ac_bandwidth(function)
            if function in _GATE:
                gate_time = self.get_gate_time(function)
            if function in _OHMS:
                offset = self.get_offset_compensation(function)
            if function is MeasurementFunction.DC_VOLTAGE:
                input_z = self.get_input_impedance_auto()
            return MetrologySnapshot(
                function=function, range_value=range_value, autorange=autorange,
                resolution=resolution, nplc=nplc, aperture_seconds=aperture_seconds,
                aperture_enabled=aperture_enabled, autozero=autozero,
                ac_bandwidth_hz=ac_bandwidth, gate_time_seconds=gate_time,
                offset_compensated=offset, input_impedance_auto=input_z,
            )
