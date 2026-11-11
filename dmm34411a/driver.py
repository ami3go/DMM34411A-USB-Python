"""34411A SCPI commands on the shared VISA transport and session stack.

Existing method names, including historical spelling mistakes, are retained.
Measurements return strings as they did in the original PyVISA wrapper.
"""

from __future__ import annotations

from types import TracebackType
from typing import Literal

from scpi_driver_core.exceptions import ConfigurationError

from scpi_driver_core import ScpiClient, ScpiSession, UnsupportedOperationError
from dmm34411a.acquisition import (
    AcquisitionController,
    AcquisitionState,
    AcquisitionProgress,
    ACQUISITION_TIMEOUT_S,
    READBACK_TIMEOUT_S,
    VOLATILE_MEMORY_POINTS,
    NONVOLATILE_MEMORY_POINTS,
)
from dmm34411a.measurement import MeasurementController
from dmm34411a.metrology import MetrologyController
from dmm34411a.calculation import MathController
from dmm34411a.storage import InstrumentStateController
from dmm34411a.display import DisplayController
from dmm34411a.status import StatusController, ScpiError, ErrorDrain, DiagnosticSnapshot
from dmm34411a.transfer import (
    ReadingTransferController, BinaryCapture, ExportReceipt,
)
from dmm34411a.models import MeasurementConfig, MeasurementFunction, MeasurementResult, TemperatureProbe
from scpi_driver_core.scpi import ScpiTextCodec
from scpi_driver_core.transport import SupportsDeviceClear, TcpTransport, Transport, VisaTransport

# Historical defaults are retained for source-compatibility. Pass an actual
# discovered VISA address rather than relying on another bench's serial number.
INSTRUMENT_VISA_ADDRESS = "USB0::0x0957::0x0A07::MY48001027::0::INSTR"
USER_REQUESTED_POINTS = 1000  # Legacy scope example constant; unused by this DMM.
GLOBAL_TOUT = 10  # Historical milliseconds; no longer controls the session.
DEFAULT_TIMEOUT_S = 5.0
DEFAULT_LAN_SOCKET_PORT = 5025


def _validate_lan_host(host: str) -> str:
    """Reject malformed hostnames and embedded VISA resource syntax."""
    if not isinstance(host, str) or not host or len(host) > 253:
        raise ConfigurationError("host must be an IPv4 address or DNS hostname")
    parts = host.split(".")
    if any(
        not part
        or len(part) > 63
        or not part[0].isascii()
        or not part[0].isalnum()
        or not part[-1].isascii()
        or not part[-1].isalnum()
        or any(not (c.isascii() and (c.isalnum() or c == "-")) for c in part)
        for part in parts
    ):
        raise ConfigurationError("host must be an IPv4 address or DNS hostname, not a URL or VISA resource")
    return host



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
    Ethernet:
        Use from_ethernet() for VXI-11/VISA LAN or direct SCPI TCP sockets.
        A complete TCPIP0::...::inst0::INSTR address also works with
        the regular resource_name argument.
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
            codec=ScpiTextCodec(response_terminator=b"\n", maximum_response_size=8 * 1024 * 1024),
            timeout_s=timeout_s,
        )
        self.session = ScpiSession("dmm34411a", self.client)
        self.idn: str | None = None
        self.acquisition = AcquisitionController(self)
        self.measurement = MeasurementController(self)
        self.metrology = MetrologyController(self)
        self.math = MathController(self)
        self.storage = InstrumentStateController(self)
        self.display = DisplayController(self)
        self.status = StatusController(self)
        self.transfer = ReadingTransferController(self)
        if auto_open:
            self.open()

    @classmethod
    def from_ethernet(
        cls,
        host: str,
        *,
        protocol: Literal["vxi11", "socket"] = "vxi11",
        port: int | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        connect_timeout_s: float | None = None,
        auto_open: bool = True,
    ) -> DMM_34411A:
        """Create a 34411A Ethernet session using shared core transports.

        VXI-11: VISA LAN instrument, requires a VXI-11-capable VISA backend.
        Socket: direct raw SCPI over TCP, default port 5025, without VISA.
        Open only probes *IDN? and does not clear/reset the instrument.
        """
        address = _validate_lan_host(host)
        if protocol not in ("vxi11", "socket"):
            raise ConfigurationError("protocol must be 'vxi11' or 'socket'")
        if protocol == "vxi11":
            if port is not None or connect_timeout_s is not None:
                raise ConfigurationError(
                    "port and connect_timeout_s apply only to raw socket connections"
                )
            selected: Transport = VisaTransport(
                f"TCPIP0::{address}::inst0::INSTR", timeout_s=timeout_s
            )
        else:
            if port is None:
                port = DEFAULT_LAN_SOCKET_PORT
            if type(port) is not int or not (1 <= port <= 65535):
                raise ConfigurationError("socket port must be an integer between 1 and 65535")
            selected = TcpTransport(
                address,
                port,
                timeout_s=timeout_s,
                connect_timeout_s=timeout_s if connect_timeout_s is None else connect_timeout_s,
            )
        return cls(transport=selected, timeout_s=timeout_s, auto_open=auto_open)

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
        # External SCPI may change the instrument's configured measurement mode.
        self.measurement.invalidate()
        self.acquisition.invalidate_external_io()
        self.client.write(txt_cmd)

    def cmd_query(self, txt_cmd: str) -> str:
        # Raw queries can include MEASure? which reconfigures the instrument.
        self.measurement.invalidate()
        # A raw query can itself trigger, read or reconfigure the meter.
        if txt_cmd.strip().upper() != "*IDN?":
            self.acquisition.invalidate_external_io()
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


    # -- v0.3.0 typed measurement interface -------------------------------

    def configure_dc_voltage(self) -> None:
        """Explicitly configure the meter for dc voltage."""
        self.measurement.configure(MeasurementConfig(MeasurementFunction.DC_VOLTAGE))

    def measure_dc_voltage(self) -> MeasurementResult:
        """Explicit one-shot dc voltage measurement."""
        return self.measurement.measure(MeasurementConfig(MeasurementFunction.DC_VOLTAGE))

    def configure_ac_voltage(self) -> None:
        """Explicitly configure the meter for ac voltage."""
        self.measurement.configure(MeasurementConfig(MeasurementFunction.AC_VOLTAGE))

    def measure_ac_voltage(self) -> MeasurementResult:
        """Explicit one-shot ac voltage measurement."""
        return self.measurement.measure(MeasurementConfig(MeasurementFunction.AC_VOLTAGE))

    def configure_dc_current(self) -> None:
        """Explicitly configure the meter for dc current."""
        self.measurement.configure(MeasurementConfig(MeasurementFunction.DC_CURRENT))

    def measure_dc_current(self) -> MeasurementResult:
        """Explicit one-shot dc current measurement."""
        return self.measurement.measure(MeasurementConfig(MeasurementFunction.DC_CURRENT))

    def configure_ac_current(self) -> None:
        """Explicitly configure the meter for ac current."""
        self.measurement.configure(MeasurementConfig(MeasurementFunction.AC_CURRENT))

    def measure_ac_current(self) -> MeasurementResult:
        """Explicit one-shot ac current measurement."""
        return self.measurement.measure(MeasurementConfig(MeasurementFunction.AC_CURRENT))

    def configure_resistance_2wire(self) -> None:
        """Explicitly configure the meter for resistance 2wire."""
        self.measurement.configure(MeasurementConfig(MeasurementFunction.RESISTANCE_2W))

    def measure_resistance_2wire(self) -> MeasurementResult:
        """Explicit one-shot resistance 2wire measurement."""
        return self.measurement.measure(MeasurementConfig(MeasurementFunction.RESISTANCE_2W))

    def configure_resistance_4wire(self) -> None:
        """Explicitly configure the meter for resistance 4wire."""
        self.measurement.configure(MeasurementConfig(MeasurementFunction.RESISTANCE_4W))

    def measure_resistance_4wire(self) -> MeasurementResult:
        """Explicit one-shot resistance 4wire measurement."""
        return self.measurement.measure(MeasurementConfig(MeasurementFunction.RESISTANCE_4W))

    def configure_frequency(self) -> None:
        """Explicitly configure the meter for frequency."""
        self.measurement.configure(MeasurementConfig(MeasurementFunction.FREQUENCY))

    def measure_frequency(self) -> MeasurementResult:
        """Explicit one-shot frequency measurement."""
        return self.measurement.measure(MeasurementConfig(MeasurementFunction.FREQUENCY))

    def configure_period(self) -> None:
        """Explicitly configure the meter for period."""
        self.measurement.configure(MeasurementConfig(MeasurementFunction.PERIOD))

    def measure_period(self) -> MeasurementResult:
        """Explicit one-shot period measurement."""
        return self.measurement.measure(MeasurementConfig(MeasurementFunction.PERIOD))

    def configure_capacitance(self) -> None:
        """Explicitly configure the meter for capacitance."""
        self.measurement.configure(MeasurementConfig(MeasurementFunction.CAPACITANCE))

    def measure_capacitance(self) -> MeasurementResult:
        """Explicit one-shot capacitance measurement."""
        return self.measurement.measure(MeasurementConfig(MeasurementFunction.CAPACITANCE))

    def configure_continuity(self) -> None:
        """Explicitly configure the meter for continuity."""
        self.measurement.configure(MeasurementConfig(MeasurementFunction.CONTINUITY))

    def measure_continuity(self) -> MeasurementResult:
        """Explicit one-shot continuity measurement."""
        return self.measurement.measure(MeasurementConfig(MeasurementFunction.CONTINUITY))

    def configure_diode(self) -> None:
        """Explicitly configure the meter for diode."""
        self.measurement.configure(MeasurementConfig(MeasurementFunction.DIODE))

    def measure_diode(self) -> MeasurementResult:
        """Explicit one-shot diode measurement."""
        return self.measurement.measure(MeasurementConfig(MeasurementFunction.DIODE))

    def configure_temperature(self, probe: TemperatureProbe) -> None:
        """Configure RTD 2-wire, RTD 4-wire or 2-wire thermistor."""
        self.measurement.configure(
            MeasurementConfig(MeasurementFunction.TEMPERATURE, temperature_probe=probe)
        )

    def measure_temperature(self, probe: TemperatureProbe) -> MeasurementResult:
        """One-shot temperature measurement with instrument-selected unit."""
        return self.measurement.measure(
            MeasurementConfig(MeasurementFunction.TEMPERATURE, temperature_probe=probe)
        )

    # -- Keysight 34411A reading memory and finite acquisition -------------

    def configure_volatile_acquisition(
        self, points: int, sample_interval_seconds: float | None = None,
        trigger_source: str = "IMMEDIATE", trigger_delay_seconds: float | None = None,
        *, trigger_count: int = 1, pretrigger_count: int = 0,
        trigger_level: float | None = None, trigger_slope: str = "POS",
    ) -> int:
        return self.acquisition.configure(
            points, sample_interval_seconds=sample_interval_seconds,
            trigger_source=trigger_source, trigger_delay_seconds=trigger_delay_seconds,
            trigger_count=trigger_count, pretrigger_count=pretrigger_count,
            trigger_level=trigger_level, trigger_slope=trigger_slope,
        )

    def configure_data_log(
        self, points: int, sample_interval_seconds: float | None = None,
        trigger_source: str = "IMMEDIATE", trigger_delay_seconds: float | None = None,
        *, trigger_count: int = 1, pretrigger_count: int = 0,
        trigger_level: float | None = None, trigger_slope: str = "POS",
    ) -> int:
        return self.acquisition.configure(
            points, sample_interval_seconds=sample_interval_seconds,
            trigger_source=trigger_source, trigger_delay_seconds=trigger_delay_seconds,
            persist=True, trigger_count=trigger_count,
            pretrigger_count=pretrigger_count,
            trigger_level=trigger_level, trigger_slope=trigger_slope,
        )

    def start_acquisition(self) -> None:
        self.acquisition.initiate()

    def start_data_log(self, clear_existing: bool = False) -> None:
        """Start logging without silently erasing any existing NVM readings."""
        self.acquisition.initiate(log=True, clear_existing=clear_existing)

    def volatile_point_count(self) -> int:
        return self.acquisition.volatile_count()

    def nonvolatile_point_count(self) -> int:
        return self.acquisition.nvm_count()

    def volatile_acquisition_progress(self) -> dict[str, int | bool]:
        return self.acquisition.progress()

    def data_log_progress(self) -> dict[str, int | bool]:
        return self.acquisition.progress()

    def wait_for_data_log(
        self, timeout_seconds: float | None = None,
        poll_interval_seconds: float = 0.1, save: bool = True,
    ) -> int:
        if self.acquisition._log_target is None:
            raise RuntimeError("configure a data log before waiting")
        count = self.acquisition.wait_complete(
            timeout_s=timeout_seconds, poll_interval_s=poll_interval_seconds
        )
        if save:
            return self.acquisition.copy_to_nvm()
        return count

    def save_data_log(self, timeout_ms: float = ACQUISITION_TIMEOUT_S * 1000) -> int:
        return self.acquisition.copy_to_nvm(timeout_s=timeout_ms / 1000.0)

    def read_data_log(self, timeout_ms: float = READBACK_TIMEOUT_S * 1000) -> list[float]:
        return self.acquisition.read_nvm(timeout_s=timeout_ms / 1000.0)

    def delete_data_log(self, *, confirm: bool = False) -> None:
        self.acquisition.delete_nvm(confirm=confirm)

    def read_volatile_readings(
        self, erase: bool = False, max_points: int | None = None,
        timeout_ms: float = READBACK_TIMEOUT_S * 1000,
    ) -> list[float]:
        return self.acquisition.read_volatile(
            erase=erase, max_points=max_points, timeout_s=timeout_ms / 1000.0
        )

    def abort_acquisition(self) -> None:
        self.acquisition.abort()

    def stop_acquisition(self) -> AcquisitionProgress:
        """Operator-controlled ABORt and partial sample-count observation."""
        return self.acquisition.abort_and_snapshot()

    def acquisition_progress_snapshot(self) -> AcquisitionProgress:
        """Local lifecycle plus one instrument point-count observation."""
        return self.acquisition.progress_snapshot()

    def set_level_trigger(self, level: float, slope: str = "POS") -> None:
        """Set 34411A internal crossing trigger for an explicit compatible mode."""
        self.acquisition.set_level_trigger(level, slope=slope)

    def set_trigger_output_slope(self, slope: str) -> None:
        """Configure trigger output polarity; do not connect before HIL approval."""
        self.acquisition.set_trigger_output_slope(slope)

    def send_bus_trigger(self) -> None:
        self.acquisition.send_bus_trigger()

    # -- v0.6.0 SCPI diagnostics (read-to-clear actions are explicit) -----

    def get_error(self) -> ScpiError:
        """Consume and return one instrument SCPI error, preserving raw text."""
        return self.status.get_error()

    def drain_errors(self, max_errors: int = 32) -> ErrorDrain:
        """Explicitly consume at most max_errors errors, never silently *CLS."""
        return self.status.drain_errors(max_errors=max_errors)

    def diagnostics_snapshot(
        self, *, include_memory: bool = False, include_system: bool = True
    ) -> DiagnosticSnapshot:
        """Read non-destructive condition/status registers; no event/error reads."""
        return self.status.snapshot(
            include_memory=include_memory, include_system=include_system
        )

    # -- v0.8.0 binary readout and atomic host export ----------------------

    def fetch_volatile_binary(
        self, *, precision_bits: int = 32, timeout_s: float = 120.0
    ) -> BinaryCapture:
        """Non-destructive raw IEEE binary FETCh? (up to 1M readings)."""
        return self.transfer.fetch_volatile_binary(
            precision_bits=precision_bits, timeout_s=timeout_s
        )

    def export_volatile_bundle(
        self, directory, *, destructive: bool = False,
        max_points: int | None = None, precision_bits: int = 32,
        chunk_size: int = 10_000, timeout_s: float = 120.0,
    ) -> ExportReceipt:
        """Atomically publish readings.csv and metadata.json under new directory."""
        return self.transfer.export_volatile_bundle(
            directory, destructive=destructive, max_points=max_points,
            precision_bits=precision_bits, chunk_size=chunk_size,
            timeout_s=timeout_s,
        )

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
            self.acquisition.reset_on_close()
            self.measurement.invalidate()

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
