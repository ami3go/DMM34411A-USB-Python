"""Small PyVISA driver for the Keysight/Agilent 34411A DMM."""

import time
from contextlib import contextmanager

try:
    import pyvisa  # PyVISA documentation: https://pyvisa.readthedocs.io/
except ImportError:  # Allow tests and applications to inject a resource manager.
    pyvisa = None


INSTRUMENT_VISA_ADDRESS = "USB0::0x0957::0x0A07::MY48001027::0::INSTR"

# VISA timeouts are milliseconds. Ten milliseconds, used by the original
# driver, is too short for normal instrument I/O.
GLOBAL_TOUT = 10_000
ACQUISITION_TOUT = 60_000
READBACK_TOUT = 60_000

# The 34411A has two different reading stores. RDG_STORE is a one-million
# reading volatile FIFO. NVMEM is a 50,000-reading non-volatile data-log store.
VOLATILE_MEMORY_POINTS = 1_000_000
NONVOLATILE_MEMORY_POINTS = 50_000


class DMM_34411A:
    """Control a 34411A over VISA.

    ``resource_manager`` is injectable so applications and tests can provide a
    configured or mocked VISA backend. With no injected manager, PyVISA is
    loaded normally.
    """

    def __init__(
        self,
        visa_address=INSTRUMENT_VISA_ADDRESS,
        resource_manager=None,
        timeout_ms=GLOBAL_TOUT,
    ):
        if resource_manager is None:
            if pyvisa is None:
                raise ModuleNotFoundError(
                    "PyVISA is required unless resource_manager is supplied"
                )
            resource_manager = pyvisa.ResourceManager()

        self.rm = resource_manager
        self.app = self.rm.open_resource(visa_address)
        self.app.timeout = self._validate_timeout_ms(timeout_ms)
        self.app.clear()

        self._acquisition_target = None
        self._data_log_target = None
        self._sample_interval_seconds = None

        identity = str(self.app.query("*IDN?")).strip()
        print(f": Connected to: {identity}")

    def conf_voltage_dc(self):
        self.app.write(":CONFigure:VOLTage:DC AUTO")

    def conf_resistane_4wire(self):
        self.app.write(":CONFigure:FRESistance AUTO, MIN")

    def conf_resistane_2wire(self):
        self.app.write(":CONFigure:RESistance AUTO, MIN")

    def conf_current_dc(self):
        self.app.write(":CONFigure:CURRent:DC AUTO")

    def cmd_write(self, txt_cmd):
        return self.app.write(txt_cmd)

    def cmd_query(self, txt_cmd):
        return self.app.query(txt_cmd)

    def cmd_read(self):
        return self.cmd_query("READ?")

    def measure_voltage(self):
        return self.app.query("MEASure:VOLTage:DC? AUTO")

    def measure_resistnce_4wire(self):
        return self.app.query("MEASure:FRESistance? AUTO")

    def measure_resistnce_2wire(self):
        return self.app.query("MEASure:RESistance? AUTO")

    def measure_current_dc(self):
        return self.app.query("MEASure:CURRent:DC? AUTO, MAX")

    # Volatile acquisition (RDG_STORE, up to 1,000,000 readings)

    def configure_volatile_acquisition(
        self,
        points,
        sample_interval_seconds=None,
        trigger_source="IMMEDIATE",
        trigger_delay_seconds=None,
    ):
        """Configure an acquisition into the volatile RDG_STORE FIFO."""
        points = self._validate_points(points, VOLATILE_MEMORY_POINTS, "volatile")
        self._configure_acquisition(
            points,
            sample_interval_seconds,
            trigger_source,
            trigger_delay_seconds,
        )
        self._acquisition_target = points
        self._data_log_target = None
        return points

    def start_acquisition(self):
        """Start the previously configured volatile acquisition."""
        if self._acquisition_target is None:
            raise RuntimeError("configure an acquisition before starting it")
        self.app.write("INITiate")

    def volatile_point_count(self):
        """Return the number of readings currently held in RDG_STORE."""
        return self._query_point_count("DATA:POINts? RDG_STORE")

    def volatile_acquisition_progress(self):
        """Return an acquisition progress dictionary."""
        if self._acquisition_target is None:
            raise RuntimeError("no acquisition has been configured")
        acquired = self.volatile_point_count()
        return {
            "acquired": acquired,
            "target": self._acquisition_target,
            "complete": acquired >= self._acquisition_target,
        }

    def read_volatile_readings(
        self, erase=False, max_points=None, timeout_ms=READBACK_TOUT
    ):
        """Read RDG_STORE as floats, optionally erasing readings as they are read.

        ``FETCh?`` leaves readings in volatile memory. ``R?`` removes the
        returned readings. If ``max_points`` is supplied, ``erase`` must be
        true because only ``R?`` accepts a maximum count.
        """
        if max_points is not None:
            max_points = self._validate_points(
                max_points, VOLATILE_MEMORY_POINTS, "volatile"
            )
            if not erase:
                raise ValueError("max_points requires erase=True")
            command = f"R? {max_points}"
        else:
            command = "R?" if erase else "FETCh?"
        return self._query_ascii_values(command, timeout_ms)

    # Persistent data logging (NVMEM, up to 50,000 readings)

    def configure_data_log(
        self,
        points,
        sample_interval_seconds=None,
        trigger_source="IMMEDIATE",
        trigger_delay_seconds=None,
    ):
        """Configure readings that will be persisted in NVMEM.

        Remote logging first fills volatile RDG_STORE. Once complete,
        :meth:`save_data_log` copies those readings to non-volatile memory.
        The persistent store is limited to 50,000 readings.
        """
        points = self._validate_points(
            points, NONVOLATILE_MEMORY_POINTS, "non-volatile"
        )
        self._configure_acquisition(
            points,
            sample_interval_seconds,
            trigger_source,
            trigger_delay_seconds,
        )
        self._acquisition_target = points
        self._data_log_target = points
        return points

    def start_data_log(self, clear_existing=True):
        """Start a configured data log.

        By default, any older persistent log is deleted before acquisition so
        that a later point-count check cannot mistake old data for the new log.
        """
        if self._data_log_target is None:
            raise RuntimeError("configure a data log before starting it")
        if clear_existing:
            self.delete_data_log()
        self.start_acquisition()

    def data_log_progress(self):
        """Return ``acquired``, ``target``, and ``complete`` for the active log."""
        if self._data_log_target is None:
            raise RuntimeError("no data log has been configured")
        acquired = self.volatile_point_count()
        return {
            "acquired": acquired,
            "target": self._data_log_target,
            "complete": acquired >= self._data_log_target,
        }

    def wait_for_data_log(
        self,
        timeout_seconds=None,
        poll_interval_seconds=0.1,
        save=True,
    ):
        """Wait for acquisition to finish and optionally persist it to NVMEM."""
        if self._data_log_target is None:
            raise RuntimeError("no data log has been configured")
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be non-negative")
        if timeout_seconds is None:
            acquisition_time = (
                self._sample_interval_seconds * self._data_log_target
                if self._sample_interval_seconds is not None
                else 0
            )
            timeout_seconds = acquisition_time + (ACQUISITION_TOUT / 1000.0)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        deadline = time.monotonic() + timeout_seconds
        while True:
            progress = self.data_log_progress()
            if progress["complete"]:
                if save:
                    return self.save_data_log(timeout_ms=int(timeout_seconds * 1000))
                return progress["acquired"]
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "data log timed out at {}/{} readings".format(
                        progress["acquired"], progress["target"]
                    )
                )
            time.sleep(poll_interval_seconds)

    def save_data_log(self, timeout_ms=ACQUISITION_TOUT):
        """Copy the completed RDG_STORE acquisition into persistent NVMEM."""
        if self._data_log_target is None:
            raise RuntimeError("no data log has been configured")
        acquired = self.volatile_point_count()
        if acquired < self._data_log_target:
            raise RuntimeError(
                f"data log is incomplete ({acquired}/{self._data_log_target} readings)"
            )

        # Ensure the last reading and subsequent copy finish before checking.
        self._query_with_timeout("*OPC?", timeout_ms)
        self.app.write("DATA:COPY NVMEM, RDG_STORE")
        self._query_with_timeout("*OPC?", timeout_ms)
        saved = self.nonvolatile_point_count()
        if saved != self._data_log_target:
            raise RuntimeError(
                f"expected {self._data_log_target} readings in NVMEM, found {saved}"
            )
        return saved

    def nonvolatile_point_count(self):
        """Return the number of readings stored persistently in NVMEM."""
        return self._query_point_count("DATA:POINts? NVMEM")

    def read_data_log(self, timeout_ms=READBACK_TOUT):
        """Return all persistent NVMEM readings as a list of floats."""
        return self._query_ascii_values("DATA:DATA? NVMEM", timeout_ms)

    def delete_data_log(self):
        """Delete every reading in non-volatile NVMEM."""
        self.app.write("DATA:DELete NVMEM")

    def abort_acquisition(self):
        """Abort the active acquisition without changing saved NVMEM data."""
        self.app.write("ABORt")

    def _configure_acquisition(
        self,
        points,
        sample_interval_seconds,
        trigger_source,
        trigger_delay_seconds,
    ):
        source = self._normalize_trigger_source(trigger_source)
        interval = self._validate_seconds(
            sample_interval_seconds, "sample_interval_seconds", allow_none=True
        )
        delay = self._validate_seconds(
            trigger_delay_seconds, "trigger_delay_seconds", allow_none=True
        )

        self.app.write(f"SAMPle:COUNt {points}")
        self.app.write("TRIGger:COUNt 1")
        self.app.write(f"TRIGger:SOURce {source}")
        if interval is None:
            self.app.write("SAMPle:SOURce AUTO")
        else:
            self.app.write("SAMPle:SOURce TIMer")
            self.app.write(f"SAMPle:TIMer {self._format_number(interval)}")
        if delay is None:
            self.app.write("TRIGger:DELay:AUTO ON")
        else:
            self.app.write("TRIGger:DELay:AUTO OFF")
            self.app.write(f"TRIGger:DELay {self._format_number(delay)}")
        self._sample_interval_seconds = interval

    @staticmethod
    def _validate_points(points, maximum, memory_name):
        if isinstance(points, bool) or not isinstance(points, int):
            raise TypeError("points must be an integer")
        if not 1 <= points <= maximum:
            raise ValueError(
                f"{memory_name} memory supports between 1 and {maximum} points"
            )
        return points

    @staticmethod
    def _validate_seconds(value, name, allow_none=False):
        if value is None and allow_none:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a number")
        value = float(value)
        if not 0 <= value <= 3600:
            raise ValueError(f"{name} must be between 0 and 3600 seconds")
        return value

    @staticmethod
    def _validate_timeout_ms(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("timeout_ms must be a number")
        if value <= 0:
            raise ValueError("timeout_ms must be greater than zero")
        return int(value)

    @staticmethod
    def _normalize_trigger_source(source):
        normalized = str(source).strip().upper()
        aliases = {
            "IMM": "IMMediate",
            "IMMEDIATE": "IMMediate",
            "EXT": "EXTernal",
            "EXTERNAL": "EXTernal",
            "BUS": "BUS",
        }
        try:
            return aliases[normalized]
        except KeyError:
            raise ValueError("trigger_source must be IMMEDIATE, EXTERNAL, or BUS")

    @staticmethod
    def _format_number(value):
        return f"{value:.12g}"

    def _query_point_count(self, command):
        response = str(self.app.query(command)).strip()
        value = float(response)
        if not value.is_integer() or value < 0:
            raise ValueError(f"unexpected point-count response: {response!r}")
        return int(value)

    def _query_with_timeout(self, command, timeout_ms):
        with self._temporary_timeout(timeout_ms):
            return self.app.query(command)

    def _query_ascii_values(self, command, timeout_ms):
        timeout_ms = self._validate_timeout_ms(timeout_ms)
        # DATA and FETCH responses follow FORMat. Force ASCII so callers always
        # receive a predictable list of Python floats.
        self.app.write("FORMat:DATA ASCii")
        with self._temporary_timeout(timeout_ms):
            query_ascii_values = getattr(self.app, "query_ascii_values", None)
            if query_ascii_values is not None:
                return list(query_ascii_values(command))
            response = str(self.app.query(command)).strip()
        if not response:
            return []
        return [float(item) for item in response.split(",")]

    @contextmanager
    def _temporary_timeout(self, timeout_ms):
        timeout_ms = self._validate_timeout_ms(timeout_ms)
        previous_timeout = self.app.timeout
        self.app.timeout = timeout_ms
        try:
            yield
        finally:
            self.app.timeout = previous_timeout

    def close(self):
        self.app.clear()
        self.app.close()
