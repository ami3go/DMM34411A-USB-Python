"""Opt-in physical LAN identity smoke test, without changing DMM settings."""

import os

import pytest

from dmm34411a import DMM_34411A

pytestmark = pytest.mark.hardware


def test_real_ethernet_identity_only():
    host = os.getenv("DMM34411A_LAN_HOST")
    if not host:
        pytest.skip("explicit DMM34411A_LAN_HOST and bench authorization required")
    protocol = os.getenv("DMM34411A_LAN_PROTOCOL", "vxi11")
    with DMM_34411A.from_ethernet(host, protocol=protocol, timeout_s=5.0) as dmm:
        assert dmm.idn is not None
        assert "34411A" in dmm.idn.upper()
