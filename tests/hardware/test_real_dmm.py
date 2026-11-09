"""Explicit opt-in 34411A HIL smoke test; never run in default CI.

Operator must identify the bench resource, confirm safe DUT wiring and select
the test manually. Current-input testing is deliberately *not* automated here.
"""

from __future__ import annotations

import os

import pytest

from dmm34411a import DMM_34411A

pytestmark = pytest.mark.hardware


def test_usb_identity_and_voltage() -> None:
    address = os.environ.get("DMM34411A_VISA_ADDRESS")
    if not address:
        pytest.skip("Set DMM34411A_VISA_ADDRESS after bench authorization")
    with DMM_34411A(resource_name=address, timeout_s=10.0) as meter:
        assert meter.idn is not None
        assert "34411A" in meter.idn.upper()
        meter.conf_voltage_dc()
        # Physical value and accuracy require a traceable voltage reference.
        reading = float(meter.measure_voltage())
        assert abs(reading) < 1e100
