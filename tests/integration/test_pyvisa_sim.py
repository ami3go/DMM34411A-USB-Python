"""Actual driver -> core -> VisaTransport -> PyVISA -> simulator path."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmm34411a import DMM_34411A
from scpi_driver_core.transport import TransportState, VisaTransport

pytestmark = [pytest.mark.integration, pytest.mark.visa_sim]
ADDRESS = "USB0::0x0957::0x0A07::MY48001027::0::INSTR"
DEFINITION = Path(__file__).with_name("fixtures") / "pyvisa_sim.yaml"


def test_usb_simulator_measurements_and_configuration() -> None:
    transport = VisaTransport(
        ADDRESS,
        timeout_s=2.0,
        visa_library=f"{DEFINITION.resolve()}@sim",
    )
    with DMM_34411A(transport=transport, timeout_s=2.0) as meter:
        assert "34411A" in meter.idn
        meter.conf_voltage_dc()
        assert meter.cmd_read() == "1.234500E+00"
        assert meter.measure_voltage() == "1.234500E+00"
        assert meter.client.query_float("READ?") == pytest.approx(1.2345)
        meter.conf_resistane_4wire()
        assert meter.measure_resistnce_4wire() == "123.000"
        meter.conf_resistane_2wire()
        assert meter.measure_resistnce_2wire() == "123.000"
        meter.conf_current_dc()
        assert meter.measure_current_dc() == "0.100000"
    assert transport.state is TransportState.CLOSED
