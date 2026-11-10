"""Keysight/Agilent 34411A DMM driver using scpi-driver-core."""

from .acquisition import NONVOLATILE_MEMORY_POINTS, VOLATILE_MEMORY_POINTS
from .models import MeasurementConfig, MeasurementFunction, MeasurementResult, TemperatureProbe
from .driver import (
    DEFAULT_TIMEOUT_S,
    DEFAULT_LAN_SOCKET_PORT,
    GLOBAL_TOUT,
    INSTRUMENT_VISA_ADDRESS,
    USER_REQUESTED_POINTS,
    DMM_34411A,
)

__version__ = "0.3.0"
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
    "__version__",
]
