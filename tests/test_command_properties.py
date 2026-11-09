"""Property tests at the concrete driver's SCPI entry points."""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from dmm34411a import DMM_34411A
from scpi_driver_core import ConfigurationError
from scpi_driver_core.simulation import ScriptedScpiTransport

IDN = "Agilent Technologies,34411A,SIM0001,1.0"
_SCPI_CHARACTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:?"


@pytest.mark.property
@settings(max_examples=40, deadline=None)
@given(command=st.text(alphabet=_SCPI_CHARACTERS, min_size=1, max_size=40))
def test_command_passthrough_keeps_one_message(command: str) -> None:
    transport = ScriptedScpiTransport(unknown_command_error=None).on("*IDN?", IDN)
    with DMM_34411A(transport=transport) as meter:
        meter.cmd_write(command)
    assert transport.history == ["*IDN?", command]


@pytest.mark.property
@settings(max_examples=40, deadline=None)
@given(
    before=st.text(alphabet=_SCPI_CHARACTERS, min_size=1, max_size=20),
    after=st.text(alphabet=_SCPI_CHARACTERS, min_size=1, max_size=20),
    separator=st.sampled_from(["\r", "\n", "\r\n"]),
)
def test_embedded_line_break_is_rejected_without_communication(
    before: str, after: str, separator: str
) -> None:
    transport = ScriptedScpiTransport(unknown_command_error=None).on("*IDN?", IDN)
    with DMM_34411A(transport=transport) as meter:
        with pytest.raises(ConfigurationError):
            meter.cmd_write(before + separator + after)
    assert transport.history == ["*IDN?"]
