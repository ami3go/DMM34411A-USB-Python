"""Keysight/Agilent 34411A DMM driver using scpi-driver-core."""

from .driver import (
    DEFAULT_TIMEOUT_S,
    DEFAULT_LAN_SOCKET_PORT,
    GLOBAL_TOUT,
    INSTRUMENT_VISA_ADDRESS,
    USER_REQUESTED_POINTS,
    DMM_34411A,
)

__version__ = "0.1.2"
__all__ = [
    "DMM_34411A",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_LAN_SOCKET_PORT",
    "GLOBAL_TOUT",
    "INSTRUMENT_VISA_ADDRESS",
    "USER_REQUESTED_POINTS",
    "__version__",
]
