"""34411A SCPI commands on the shared VISA transport and session stack.

Existing method names, including historical spelling mistakes, are retained.
Measurements return strings as they did in the original PyVISA wrapper.
"""

from __future__ import annotations

from types import TracebackType

from scpi_driver_core import ScpiClient, ScpiSession, UnsupportedOperationError
from scpi_driver_core.scpi import ScpiTextCodec
from scpi_driver_core.transport import SupportsDeviceClear, Transport, VisaTransport

# Historical defaults are retained for source-compatibility. Pass an actual
# discovered VISA address rather than relying on another bench's serial number.
INSTRUMENT_VISA_ADDRESS = "USB0::0x0957::0x0A07::MY48001027::0::INSTR"
USER_REQUESTED_POINTS = 1000  # Legacy scope example constant; unused by this DMM.
GLOBAL_TOUT = 10  # Historical milliseconds; no longer controls the session.
DEFAULT_TIMEOUT_S = 5.0


class DMM_34411A:
    """A small, synchronous 34411A driver backed by scpi-driver-core.

    Opening probes *IDN? but never sends reset, device clear, or *CLS.
    Use an injected core Transport for simulation or a custom VISA backend.

    Parameters
    ----------
    resource_name:
        VISA resource address. The historical address remains the default for
        compatibility, but selecting the actual instrument is recommended.
    timeout_s:
        Finite transport and client deadline, in *seconds*.
    transport:
        Optional already-constructed core transport; the driver owns its
        open/close lifecycle. When specified, resource_name only documents
        the default address and is not used to create another transport.
    auto_open:
        If True, open and probe immediately, as the old constructor did.
    """

    def __init__(
        self,
        resource_name: str = INSTRUMENT_VISA_ADDRESS,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: Transport | None = None,
        auto_open: bool = True,
    ) -> None:
        self.transport: Transport = (
            transport if transport is not None else VisaTransport(resource_name, timeout_s=timeout_s)
        )
        # USBTMC/VISA INSTR supports END-delimited reads, and the core selects
        # BACKEND_DEFINED_MESSAGE. The codec strips a trailing LF, if present.
        self.client = ScpiClient(
            self.transport,
            codec=ScpiTextCodec(response_terminator=b"\n"),
            timeout_s=timeout_s,
        )
        self.session = ScpiSession("dmm34411a", self.client)
        self.idn: str | None = None
        if auto_open:
            self.open()

    def open(self) -> None:
        """Open a session and verify communication with one non-destructive query."""
        if self.session.is_connected:
            return
        self.session.open()
        try:
            self.idn = self.cmd_query("*IDN?")
        except BaseException:
            # Do not leave an open resource after a failed initial probe.
            self.session.close()
            raise

    def conf_voltage_dc(self) -> None:
        self.cmd_write(":CONFigure:VOLTage:DC: AUTO")

    def conf_resistane_4wire(self) -> None:
        self.cmd_write(":CONFigure:FRESistance AUTO, MIN")

    def conf_resistane_2wire(self) -> None:
        self.cmd_write(":CONFigure:RESistance AUTO, MIN")

    def conf_current_dc(self) -> None:
        self.cmd_write(":CONFigure:CURRent:DC: AUTO")

    def cmd_write(self, txt_cmd: str) -> None:
        self.client.write(txt_cmd)

    def cmd_query(self, txt_cmd: str) -> str:
        # Retain the legacy string result; remove only line termination.
        return self.client.query(txt_cmd).rstrip("\r\n")

    def cmd_read(self) -> str:
        return self.cmd_query("READ?")

    def measure_voltage(self) -> str:
        return self.cmd_query("MEASure:VOLTage:DC? AUTO")

    def measure_resistnce_4wire(self) -> str:
        return self.cmd_query("MEASure:FRESistance? AUTO")

    def measure_resistnce_2wire(self) -> str:
        return self.cmd_query("MEASure:RESistance? AUTO")

    def measure_current_dc(self) -> str:
        return self.cmd_query("MEASure:CURRent:DC? AUTO ,MAX")

    def device_clear(self) -> None:
        """Explicit VISA device clear; may abort an ongoing measurement."""
        if not isinstance(self.transport, SupportsDeviceClear):
            raise UnsupportedOperationError("selected transport does not support device clear")
        self.transport.device_clear()

    def close(self) -> None:
        """Release the connection without issuing an implicit device clear."""
        try:
            self.session.close()
        finally:
            self.idn = None

    def __enter__(self) -> DMM_34411A:
        if not self.session.is_connected:
            self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
