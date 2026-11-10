"""Model-specific metrology controls for Keysight/Agilent 34411A.

Implements explicit, function-scoped SENSe commands. It does not change the
selected measurement function, clear errors, start a reading or touch NVM.
Instrument-side readback is preferred to local cached parameter assumptions.

References: 34410A/11A/L4411A User's Guide pp. 52-59 and Keysight
34410A/34411A SCPI command comparison 5990-3515.
"""

from __future__ import annotations

import math
from dataclasses import replace

from scpi_driver_core import ConfigurationError, UnsupportedOperationError

from .models import MeasurementFunction as F, MetrologySettings, TemperatureProbe

_SENSE = {
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
_RANGE = frozenset(_SENSE) - {F.TEMPERATURE}
_RESOLUTION = {
    F.DC_VOLTAGE, F.AC_VOLTAGE, F.DC_CURRENT, F.AC_CURRENT,
    F.RESISTANCE_2W, F.RESISTANCE_4W,
}
_INTEGRATION = {
    F.DC_VOLTAGE, F.DC_CURRENT, F.RESISTANCE_2W, F.RESISTANCE_4W, F.TEMPERATURE,
}
_ZERO = {F.DC_VOLTAGE, F.DC_CURRENT, F.RESISTANCE_2W, F.TEMPERATURE}
_AC_FILTER = {F.AC_VOLTAGE, F.AC_CURRENT, F.FREQUENCY, F.PERIOD}
_GATE = {F.FREQUENCY, F.PERIOD}
_OHMS = {F.RESISTANCE_2W, F.RESISTANCE_4W}
_NPLC_34411A = (0.001, 0.002, 0.006, 0.02, 0.06, 0.2, 1.0, 2.0, 10.0, 100.0)
_GATE_TIMES_S = (0.001, 0.01, 0.1, 1.0)
_FILTER_HZ = (3, 20, 200)
_SYMBOLIC = frozenset(("MIN", "MAX", "DEF"))
_RANGE_MAX = {
    F.DC_VOLTAGE: 1000.0,
    F.AC_VOLTAGE: 750.0,
    F.DC_CURRENT: 3.0,
    F.AC_CURRENT: 3.0,
    F.RESISTANCE_2W: 1.0e9,
    F.RESISTANCE_4W: 1.0e9,
    F.FREQUENCY: 750.0,  # AC input voltage range, NOT hertz.
    F.PERIOD: 750.0,
    F.CAPACITANCE: 0.01,  # Upper bound only; meter may round to a supported range.
}


def _function(value: F, supported: set[F] | frozenset[F], setting: str) -> str:
    if not isinstance(value, F):
        raise ConfigurationError("function must be a MeasurementFunction")
    if value not in supported:
        raise UnsupportedOperationError(f"{setting} is not supported in {value.value}")
    return _SENSE[value]


def _number(value: float | int, name: str, *, minimum: float = 0.0,
            maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ConfigurationError(f"{name} must be a finite numeric value")
    result = float(value)
    if not math.isfinite(result) or not result > minimum or (
        maximum is not None and result > maximum
    ):
        raise ConfigurationError(f"{name} is outside supported bounds")
    return result


def _parameter(value: str | float, name: str, *, maximum: float | None = None) -> str:
    if isinstance(value, str):
        if value not in _SYMBOLIC:
            raise ConfigurationError(f"{name} must be a supported symbolic selector or number")
        return value
    return f"{_number(value, name, maximum=maximum):.12g}"


def _finite_reply(raw: str, command: str) -> float:
    try:
        value = float(raw.strip())
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"malformed {command}: {raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"invalid {command}: {raw!r}")
    return value


def _bool_reply(raw: str, command: str) -> bool:
    value = raw.strip()
    if value not in ("0", "1"):
        raise ValueError(f"expected 0/1 from {command}: {raw!r}")
    return value == "1"


class MetrologyController:
    """Explicit instrument metrology settings and actual-setting readback.

    Settings can be addressed for a function independently of the instrument's
    currently active measurement mode. No function-switch command is sent.
    This class is not a measurement accuracy calibration service.
    """

    def __init__(self, meter: object) -> None:
        self._meter = meter

    @property
    def _client(self):
        return self._meter.client

    def _write(self, header: str, value: str) -> None:
        with self._meter.session.operation_lock():
            self._client.write(f"SENSe:{header} {value}")

    def _query(self, header: str) -> str:
        with self._meter.session.operation_lock():
            return self._client.query(f"SENSe:{header}?").strip()

    def _query_number(self, header: str) -> float:
        return _finite_reply(self._query(header), header)

    def _query_bool(self, header: str) -> bool:
        return _bool_reply(self._query(header), header)

    @staticmethod
    def _range_prefix(function: F) -> str:
        path = _function(function, _RANGE, "range")
        if function in _GATE:
            return f"{path}:VOLTage:RANGe"
        return f"{path}:RANGe"

    def set_range(self, function: F, value: float | str) -> None:
        """Select an instrument manual range, or explicitly enable AUTO.

        Numerical values are in V, A, ohm or F, except frequency/period,
        where the range is the AC input amplitude in V, not Hz or seconds.
        The meter selects a supported range; query get_range() to verify.
        """
        path = self._range_prefix(function)
        if value == "AUTO":
            self._write(f"{path}:AUTO", "ON")
            return
        maximum = _RANGE_MAX[function]
        token = _parameter(value, "range", maximum=maximum)
        self._write(path, token)

    def get_range(self, function: F) -> float:
        return self._query_number(self._range_prefix(function))

    def set_autorange(self, function: F, enabled: bool) -> None:
        path = self._range_prefix(function)
        if type(enabled) is not bool:
            raise ConfigurationError("enabled must be bool")
        self._write(f"{path}:AUTO", "ON" if enabled else "OFF")

    def get_autorange(self, function: F) -> bool:
        return self._query_bool(f"{self._range_prefix(function)}:AUTO")

    def set_resolution(self, function: F, value: float | str) -> None:
        path = _function(function, _RESOLUTION, "resolution")
        token = _parameter(value, "resolution", maximum=_RANGE_MAX[function])
        self._write(f"{path}:RESolution", token)

    def get_resolution(self, function: F) -> float:
        path = _function(function, _RESOLUTION, "resolution")
        return self._query_number(f"{path}:RESolution")

    def set_nplc(self, function: F, value: float | str) -> None:
        """Select 34411A NPLC integration; explicitly disable aperture mode."""
        path = _function(function, _INTEGRATION, "NPLC")
        if isinstance(value, str):
            token = _parameter(value, "NPLC")
        else:
            numeric = _number(value, "NPLC")
            if numeric not in _NPLC_34411A:
                raise ConfigurationError(f"NPLC must be one of {_NPLC_34411A}")
            token = f"{numeric:.12g}"
        with self._meter.session.operation_lock():
            self._client.write(f"SENSe:{path}:NPLC {token}")
            self._client.write(f"SENSe:{path}:APERture:ENABled OFF")

    def get_nplc(self, function: F) -> float:
        path = _function(function, _INTEGRATION, "NPLC")
        return self._query_number(f"{path}:NPLC")

    def set_aperture(self, function: F, seconds: float | str) -> None:
        """Select aperture integration (34411A: 20 µs through 1 s)."""
        path = _function(function, _INTEGRATION, "aperture")
        if isinstance(seconds, str):
            token = _parameter(seconds, "aperture")
        else:
            value = _number(seconds, "aperture", maximum=1.0)
            if value < 20e-6:
                raise ConfigurationError("34411A aperture minimum is 20 microseconds")
            token = f"{value:.12g}"
        with self._meter.session.operation_lock():
            self._client.write(f"SENSe:{path}:APERture {token}")
            self._client.write(f"SENSe:{path}:APERture:ENABled ON")

    def get_aperture(self, function: F) -> float:
        path = _function(function, _INTEGRATION, "aperture")
        return self._query_number(f"{path}:APERture")

    def set_aperture_enabled(self, function: F, enabled: bool) -> None:
        path = _function(function, _INTEGRATION, "aperture")
        if type(enabled) is not bool:
            raise ConfigurationError("enabled must be bool")
        self._write(f"{path}:APERture:ENABled", "ON" if enabled else "OFF")

    def get_aperture_enabled(self, function: F) -> bool:
        path = _function(function, _INTEGRATION, "aperture")
        return self._query_bool(f"{path}:APERture:ENABled")

    def _zero_path(self, function: F) -> str:
        path = _function(function, _ZERO, "autozero")
        if function is F.TEMPERATURE:
            # Four-wire temperature always has autozero enabled. Only permit
            # changes when a known 2-wire temperature probe is configured.
            current = self._meter.measurement._active
            if current is None or current.function is not F.TEMPERATURE or (
                current.temperature_probe not in (
                    TemperatureProbe.RTD_2W, TemperatureProbe.THERMISTOR_2W
                )
            ):
                raise UnsupportedOperationError(
                    "temperature autozero requires explicit 2-wire probe configuration"
                )
        return f"{path}:ZERO:AUTO"

    def set_autozero(self, function: F, mode: bool | str) -> None:
        path = self._zero_path(function)
        if type(mode) is bool:
            token = "ON" if mode else "OFF"
        elif isinstance(mode, str) and mode in ("ON", "OFF", "ONCE"):
            token = mode
        else:
            raise ConfigurationError("autozero mode must be ON, OFF, ONCE or bool")
        self._write(path, token)

    def get_autozero(self, function: F) -> bool:
        return self._query_bool(self._zero_path(function))

    @staticmethod
    def _filter_path(function: F) -> str:
        _function(function, _AC_FILTER, "AC bandwidth")
        # FREQ/PER input filters share the AC voltage bandwidth setting.
        return "CURRent:AC:BANDwidth" if function is F.AC_CURRENT else "VOLTage:AC:BANDwidth"

    def set_ac_bandwidth(self, function: F, hz: int) -> None:
        path = self._filter_path(function)
        if type(hz) is not int or hz not in _FILTER_HZ:
            raise ConfigurationError("AC bandwidth must be 3, 20 or 200 Hz")
        self._write(path, str(hz))

    def get_ac_bandwidth(self, function: F) -> float:
        return self._query_number(self._filter_path(function))

    def set_gate_time(self, function: F, seconds: float) -> None:
        path = _function(function, _GATE, "frequency/period gate")
        value = _number(seconds, "gate time", maximum=1.0)
        if value not in _GATE_TIMES_S:
            raise ConfigurationError(f"gate time must be one of {_GATE_TIMES_S}")
        self._write(f"{path}:APERture", f"{value:.12g}")

    def get_gate_time(self, function: F) -> float:
        path = _function(function, _GATE, "frequency/period gate")
        return self._query_number(f"{path}:APERture")

    def set_input_impedance_auto(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ConfigurationError("enabled must be bool")
        self._write("VOLTage:DC:IMPedance:AUTO", "ON" if enabled else "OFF")

    def get_input_impedance_auto(self) -> bool:
        return self._query_bool("VOLTage:DC:IMPedance:AUTO")

    def set_offset_compensated(self, function: F, enabled: bool) -> None:
        """Enable offset compensation only on a supported fixed 100/1k/10k ohm range."""
        path = _function(function, _OHMS, "offset compensation")
        if type(enabled) is not bool:
            raise ConfigurationError("enabled must be bool")
        if enabled:
            # Offset compensation is only effective on three low-resistance
            # ranges; refuse autoranging because the range may later change.
            with self._meter.session.operation_lock():
                if self.get_autorange(function):
                    raise ConfigurationError("turn off autorange before enabling offset compensation")
                value = self.get_range(function)
                if not any(abs(value - x) <= x * 1e-6 for x in (100.0, 1000.0, 10000.0)):
                    raise ConfigurationError("offset compensation requires 100, 1k or 10k ohms")
                self._client.write(f"SENSe:{path}:OCOMpensated ON")
        else:
            self._write(f"{path}:OCOMpensated", "OFF")

    def get_offset_compensated(self, function: F) -> bool:
        path = _function(function, _OHMS, "offset compensation")
        return self._query_bool(f"{path}:OCOMpensated")

    def get_settings(self, function: F) -> MetrologySettings:
        """Read live settings under one session lock, never relying on cache."""
        _function(function, frozenset(_SENSE), "settings")
        with self._meter.session.operation_lock():
            rng = self.get_range(function) if function in _RANGE else None
            autorange = self.get_autorange(function) if function in _RANGE else None
            resolution = self.get_resolution(function) if function in _RESOLUTION else None
            nplc = self.get_nplc(function) if function in _INTEGRATION else None
            aperture = self.get_aperture(function) if function in _INTEGRATION else None
            aperture_enabled = (
                self.get_aperture_enabled(function) if function in _INTEGRATION else None
            )
            autozero = (
                self.get_autozero(function)
                if function in _ZERO and (function is not F.TEMPERATURE or
                    (self._meter.measurement._active is not None and
                     self._meter.measurement._active.temperature_probe in (
                         TemperatureProbe.RTD_2W, TemperatureProbe.THERMISTOR_2W
                     )))
                else None
            )
            bandwidth = self.get_ac_bandwidth(function) if function in _AC_FILTER else None
            gate = self.get_gate_time(function) if function in _GATE else None
            impedance = self.get_input_impedance_auto() if function is F.DC_VOLTAGE else None
            offset = self.get_offset_compensated(function) if function in _OHMS else None
            return MetrologySettings(
                function=function,
                range_value=rng,
                autorange=autorange,
                resolution=resolution,
                nplc=nplc,
                aperture_s=aperture,
                aperture_enabled=aperture_enabled,
                autozero=autozero,
                ac_bandwidth_hz=bandwidth,
                gate_time_s=gate,
                dc_input_impedance_auto=impedance,
                offset_compensated=offset,
            )

    def read_with_settings(self):
        """Read once, recording actual settings before the READ? operation.

        This is an ordered host snapshot, not a physically atomic sampling of
        instrument state. External controllers must not modify the instrument
        during the call; transport locking only serializes this session.
        """
        with self._meter.session.operation_lock():
            active = self._meter.measurement._active
            if active is None:
                raise RuntimeError("configure a measurement before metadata read")
            snapshot = self.get_settings(active.function)
            reading = self._meter.measurement.read()
            return replace(reading, metrology=snapshot)
