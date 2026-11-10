"""Keysight/Agilent 34411A DMM driver using scpi-driver-core."""

from .acquisition import NONVOLATILE_MEMORY_POINTS, VOLATILE_MEMORY_POINTS
from .driver import (
    DEFAULT_TIMEOUT_S,
    DEFAULT_LAN_SOCKET_PORT,
    GLOBAL_TOUT,
    INSTRUMENT_VISA_ADDRESS,
    USER_REQUESTED_POINTS,
    DMM_34411A,
)

__version__ = "0.2.0"
__all__ = [
    "DMM_34411A",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_LAN_SOCKET_PORT",
    "GLOBAL_TOUT",
    "INSTRUMENT_VISA_ADDRESS",
    "USER_REQUESTED_POINTS",
    "NONVOLATILE_MEMORY_POINTS",
    "VOLATILE_MEMORY_POINTS",
    "__version__",
]
