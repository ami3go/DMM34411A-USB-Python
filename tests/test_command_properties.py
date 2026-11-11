"""Property tests at the concrete driver's SCPI entry points."""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from dmm34411a import DMM_34411A
from scpi_driver_core import ConfigurationError
from scpi_driver_core.simulation import ScriptedScpiTransport

IDN = "Agilent Technologies,34411A,SIM0001,1.0"
_SCPI_CHARACTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:?"
# A SCPI program header cannot be a bare colon or start with a digit.
# The scripted core intentionally strips a leading root-path colon.
_VALID_SCPI_HEADER = st.from_regex(
    r"[A-Z][A-Z0-9]{0,7}(?::[A-Z][A-Z0-9]{0,7}){0,2}\??",
    fullmatch=True,
)


@pytest.mark.property
@settings(max_examples=40, deadline=None)
@given(command=_VALID_SCPI_HEADER)
def test_command_passthrough_keeps_one_message(command: str) -> None:
    transport = ScriptedScpiTransport(unknown_command_error=None).on("*IDN?", IDN)
    with DMM_34411A(transport=transport) as meter:
        meter.cmd_write(command)
    assert transport.history == ["*IDN?", command]


def test_explicit_root_colon_is_normalized_by_scripted_core() -> None:
    transport = ScriptedScpiTransport(unknown_command_error=None).on("*IDN?", IDN)
    with DMM_34411A(transport=transport) as meter:
        meter.cmd_write(":SENSe:VOLTage:DC:RANGe 10")
    assert transport.history == ["*IDN?", "SENSe:VOLTage:DC:RANGe 10"]


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
