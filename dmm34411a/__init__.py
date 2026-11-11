"""Keysight/Agilent 34411A DMM driver using scpi-driver-core."""

from .acquisition import NONVOLATILE_MEMORY_POINTS, VOLATILE_MEMORY_POINTS
from .models import MeasurementConfig, MeasurementFunction, MeasurementResult, TemperatureProbe
from .metrology import MetrologyController, MetrologySnapshot
from .calculation import MathController, MathMode, Statistics, Limits
from .storage import InstrumentStateController, StoredState
from .display import DisplayController
from .status import StatusController, ScpiError, ErrorDrain, StatusBank, DiagnosticSnapshot
from .driver import (
    DEFAULT_TIMEOUT_S,
    DEFAULT_LAN_SOCKET_PORT,
    GLOBAL_TOUT,
    INSTRUMENT_VISA_ADDRESS,
    USER_REQUESTED_POINTS,
    DMM_34411A,
)

__version__ = "0.6.0"
__all__ = [
    "DMM_34411A",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_LAN_SOCKET_PORT",
    "GLOBAL_TOUT",
    "INSTRUMENT_VISA_ADDRESS",
    "USER_REQUESTED_POINTS",
    "NONVOLATILE_MEMORY_POINTS",
    "VOLATILE_MEMORY_POINTS",
    "MeasurementConfig",
    "MeasurementFunction",
    "MeasurementResult",
    "TemperatureProbe",
    "MetrologyController",
    "MetrologySnapshot",
    "MathController",
    "MathMode",
    "InstrumentStateController",
    "StoredState",
    "DisplayController",
    "StatusController",
    "ScpiError",
    "ErrorDrain",
    "StatusBank",
    "DiagnosticSnapshot",
    "Statistics",
    "Limits",
    "__version__",
]
