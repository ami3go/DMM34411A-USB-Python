"""Typed measurement models for the Keysight/Agilent 34411A.

Host timestamps describe when software received data, never instrument sample time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .metrology import MetrologySnapshot


class MeasurementFunction(str, Enum):
    DC_VOLTAGE = "dc_voltage"
    AC_VOLTAGE = "ac_voltage"
    DC_CURRENT = "dc_current"
    AC_CURRENT = "ac_current"
    RESISTANCE_2W = "resistance_2w"
    RESISTANCE_4W = "resistance_4w"
    FREQUENCY = "frequency"
    PERIOD = "period"
    CAPACITANCE = "capacitance"
    CONTINUITY = "continuity"
    DIODE = "diode"
    TEMPERATURE = "temperature"


class TemperatureProbe(str, Enum):
    RTD_2W = "RTD"
    RTD_4W = "FRTD"
    THERMISTOR_2W = "THERmistor"


@dataclass(frozen=True)
class MeasurementConfig:
    """Explicit selection of a measurement mode.

    Only symbolic range/resolution selectors are supported in v0.3.0;
    numerical ranges, digits, probe coefficients and NPLC belong to P1-03.
    """

    function: MeasurementFunction
    range_spec: str | None = None
    resolution: str | None = None
    temperature_probe: TemperatureProbe | None = None


@dataclass(frozen=True)
class MeasurementResult:
    """One decoded reading with original text and host receipt time."""

    function: MeasurementFunction
    value: float | None
    unit: str
    raw: str
    measured_at_utc: datetime
    is_overrange: bool
    metrology: MetrologySnapshot | None = None
