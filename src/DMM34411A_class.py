"""Compatibility shim for the original source-checkout import path.

New code should use `from dmm34411a import DMM_34411A`.
"""

from dmm34411a import (
    DEFAULT_TIMEOUT_S,
    GLOBAL_TOUT,
    INSTRUMENT_VISA_ADDRESS,
    USER_REQUESTED_POINTS,
    DMM_34411A,
)

__all__ = [
    "DMM_34411A",
    "DEFAULT_TIMEOUT_S",
    "GLOBAL_TOUT",
    "INSTRUMENT_VISA_ADDRESS",
    "USER_REQUESTED_POINTS",
]
