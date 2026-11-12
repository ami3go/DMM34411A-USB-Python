"""34411A measurement configuration and one-shot readout via scpi-driver-core.

No automatic measurements, instrument resets, or current-mode switching occur
during construction or connection. Configuring a mode is always explicit.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from scpi_driver_core import ConfigurationError

from .models import MeasurementConfig, MeasurementFunction, MeasurementResult, TemperatureProbe

# 34410A/34411A Command Quick Reference 9018-61141, Config/Measure sections.
_COMMANDS: dict[MeasurementFunction, tuple[str, str, str]] = {
    MeasurementFunction.DC_VOLTAGE: ("CONFigure:VOLTage:DC", "MEASure:VOLTage:DC?", "V"),
    MeasurementFunction.AC_VOLTAGE: ("CONFigure:VOLTage:AC", "MEASure:VOLTage:AC?", "V"),
    MeasurementFunction.DC_CURRENT: ("CONFigure:CURRent:DC", "MEASure:CURRent:DC?", "A"),
    MeasurementFunction.AC_CURRENT: ("CONFigure:CURRent:AC", "MEASure:CURRent:AC?", "A"),
    MeasurementFunction.RESISTANCE_2W: ("CONFigure:RESistance", "MEASure:RESistance?", "ohm"),
    MeasurementFunction.RESISTANCE_4W: ("CONFigure:FRESistance", "MEASure:FRESistance?", "ohm"),
    MeasurementFunction.FREQUENCY: ("CONFigure:FREQuency", "MEASure:FREQuency?", "Hz"),
    MeasurementFunction.PERIOD: ("CONFigure:PERiod", "MEASure:PERiod?", "s"),
    MeasurementFunction.CAPACITANCE: ("CONFigure:CAPacitance", "MEASure:CAPacitance?", "F"),
    MeasurementFunction.CONTINUITY: ("CONFigure:CONTinuity", "MEASure:CONTinuity?", "ohm"),
    MeasurementFunction.DIODE: ("CONFigure:DIODe", "MEASure:DIODe?", "V"),
    MeasurementFunction.TEMPERATURE: ("CONFigure:TEMPerature", "MEASure:TEMPerature?", ""),
}
_NO_ARGUMENTS = {MeasurementFunction.CONTINUITY, MeasurementFunction.DIODE}
_NO_AUTO_RANGE = {MeasurementFunction.FREQUENCY, MeasurementFunction.PERIOD}
_TEMP_UNITS = {"C": "degC", "CEL": "degC", "F": "degF", "FAR": "degF", "K": "K"}


def _build_command(config: MeasurementConfig, *, query: bool) -> str:
    """Validate all inputs *before* sending a single SCPI program message."""
    if not isinstance(config, MeasurementConfig) or not isinstance(
        config.function, MeasurementFunction
    ):
        raise ConfigurationError("config requires a MeasurementConfig and MeasurementFunction")
    function = config.function
    command = _COMMANDS[function][1 if query else 0]
    if function is MeasurementFunction.TEMPERATURE:
        if config.range_spec is not None or config.resolution is not None:
            raise ConfigurationError("temperature range/resolution controls require P1-03")
        if not isinstance(config.temperature_probe, TemperatureProbe):
            raise ConfigurationError("temperature_probe must specify RTD_2W, RTD_4W or THERMISTOR_2W")
        # The 34411A quick reference permits FRTD, RTD or THERmistor, with
        # DEFault sensor type. Probe coefficients belong to the metrology PR.
        return f"{command} {config.temperature_probe.value},DEF"
    if config.temperature_probe is not None:
        raise ConfigurationError("temperature_probe is allowed only for temperature measurements")
    if function in _NO_ARGUMENTS:
        if config.range_spec is not None or config.resolution is not None:
            raise ConfigurationError("continuity and diode use fixed range and resolution")
        return command
    range_spec = config.range_spec
    resolution = config.resolution
    if range_spec is not None:
        if not isinstance(range_spec, str) or range_spec not in ("AUTO", "MIN", "MAX", "DEF"):
            raise ConfigurationError("range_spec accepts only AUTO, MIN, MAX or DEF in v0.3.0")
        if function in _NO_AUTO_RANGE and range_spec == "AUTO":
            raise ConfigurationError("frequency and period do not accept AUTO as a range parameter")
    if resolution is not None:
        if not isinstance(resolution, str) or resolution not in ("MIN", "MAX", "DEF"):
            raise ConfigurationError("resolution accepts only MIN, MAX or DEF in v0.3.0")
        if range_spec is None:
            raise ConfigurationError("resolution requires an explicit range_spec")
    if range_spec is not None:
        command += f" {range_spec}"
        if resolution is not None:
            command += f",{resolution}"
    return command


def _decode(function: MeasurementFunction, raw: str, unit: str) -> MeasurementResult:
    stripped = raw.strip()
    if not stripped or "," in stripped:
        raise ValueError(f"expected one reading for {function.value}, got {raw!r}")
    try:
        value = float(stripped)
    except ValueError as exc:
        raise ValueError(f"invalid {function.value} reading {raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"nonfinite {function.value} reading {raw!r}")
    # The 34410A/11A User Guide documents +/-9.9E37 for overload.
    is_overrange = abs(value) >= 9.9e37
    return MeasurementResult(
        function=function,
        value=None if is_overrange else value,
        unit=unit,
        raw=raw,
        measured_at_utc=datetime.now(timezone.utc),
        is_overrange=is_overrange,
    )


class MeasurementController:
    """Model-specific commands, sharing the parent meter's core session."""

    def __init__(self, meter: object) -> None:
        self._meter = meter
        self._active: MeasurementConfig | None = None
        self._generation: int | None = None

    def invalidate(self) -> None:
        """Forget a local cached function after external configuration or close."""
        self._active = None
        self._generation = None

    def configure(self, config: MeasurementConfig) -> None:
        command = _build_command(config, query=False)
        with self._meter.session.operation_lock():
            self.invalidate()
            self._meter.acquisition.invalidate_external_io()
            self._meter.client.write(command)
            self._active = config
            self._generation = self._meter.session.generation

    def get_configuration_raw(self) -> str:
        """Query the instrument directly; this does not trust cached state."""
        return self._meter.client.query("CONFigure?").strip()

    def get_identity(self) -> str:
        return self._meter.client.query("*IDN?").strip()

    def _unit(self, config: MeasurementConfig) -> str:
        if config.function is not MeasurementFunction.TEMPERATURE:
            return _COMMANDS[config.function][2]
        reply = self._meter.client.query("UNIT:TEMPerature?").strip().upper()
        try:
            return _TEMP_UNITS[reply]
        except KeyError as exc:
            raise ValueError(f"unexpected temperature unit {reply!r}") from exc

    def read(self) -> MeasurementResult:
        """Read only a previously explicitly configured function.

        Raw client access may change the instrument state without invalidating
        the cache. Applications mixing direct SCPI should query the instrument
        and call configure() again before using read().
        """
        with self._meter.session.operation_lock():
            config = self._active
            if config is None or self._generation != self._meter.session.generation:
                raise RuntimeError("configure a measurement before calling read()")
            unit = self._unit(config)
            raw = self._meter.client.query("READ?").strip()
            return _decode(config.function, raw, unit)

    def measure(self, config: MeasurementConfig) -> MeasurementResult:
        """Explicit one-shot MEASure? (may change instrument configuration)."""
        command = _build_command(config, query=True)
        with self._meter.session.operation_lock():
            self.invalidate()
            self._meter.acquisition.invalidate_external_io()
            unit = self._unit(config)
            raw = self._meter.client.query(command).strip()
            return _decode(config.function, raw, unit)
