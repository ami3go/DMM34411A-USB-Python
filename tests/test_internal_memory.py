import unittest

from src.DMM34411A_class import (
    DMM_34411A,
    GLOBAL_TOUT,
    NONVOLATILE_MEMORY_POINTS,
    VOLATILE_MEMORY_POINTS,
)


class FakeInstrument:
    def __init__(self):
        self.timeout = None
        self.writes = []
        self.queries = []
        self.ascii_queries = []
        self.clears = 0
        self.closed = False
        self.volatile_counts = [0]
        self.nonvolatile_count = 0
        self.ascii_values = {}
        self.query_timeouts = []

    def clear(self):
        self.clears += 1

    def close(self):
        self.closed = True

    def write(self, command):
        self.writes.append(command)
        if command == "DATA:DELete NVMEM":
            self.nonvolatile_count = 0
        elif command == "DATA:COPY NVMEM, RDG_STORE":
            self.nonvolatile_count = self.volatile_counts[-1]

    def query(self, command):
        self.queries.append(command)
        self.query_timeouts.append((command, self.timeout))
        if command == "*IDN?":
            return "Keysight Technologies,34411A,MY123,2.35\n"
        if command == "DATA:POINts? RDG_STORE":
            if len(self.volatile_counts) > 1:
                return str(self.volatile_counts.pop(0))
            return str(self.volatile_counts[0])
        if command == "DATA:POINts? NVMEM":
            return str(self.nonvolatile_count)
        if command == "*OPC?":
            return "1"
        return "0"

    def query_ascii_values(self, command):
        self.ascii_queries.append((command, self.timeout))
        return self.ascii_values.get(command, [])


class FakeResourceManager:
    def __init__(self, instrument):
        self.instrument = instrument
        self.addresses = []

    def open_resource(self, address):
        self.addresses.append(address)
        return self.instrument


class InternalMemoryTests(unittest.TestCase):
    def setUp(self):
        self.instrument = FakeInstrument()
        self.rm = FakeResourceManager(self.instrument)
        self.dmm = DMM_34411A(visa_address="USB::TEST", resource_manager=self.rm)

    def tearDown(self):
        if not self.instrument.closed:
            self.dmm.close()

    def test_constructor_uses_injected_visa_manager_and_sane_timeout(self):
        self.assertEqual(self.rm.addresses, ["USB::TEST"])
        self.assertEqual(self.instrument.timeout, GLOBAL_TOUT)
        self.assertEqual(self.instrument.clears, 1)

    def test_configure_data_log_writes_timer_and_trigger_commands(self):
        result = self.dmm.configure_data_log(
            50_000,
            sample_interval_seconds=0.02,
            trigger_source="external",
            trigger_delay_seconds=0.5,
        )

        self.assertEqual(result, NONVOLATILE_MEMORY_POINTS)
        self.assertEqual(
            self.instrument.writes,
            [
                "SAMPle:COUNt 50000",
                "TRIGger:COUNt 1",
                "TRIGger:SOURce EXTernal",
                "SAMPle:SOURce TIMer",
                "SAMPle:TIMer 0.02",
                "TRIGger:DELay:AUTO OFF",
                "TRIGger:DELay 0.5",
            ],
        )

    def test_data_log_rejects_more_than_50000_points(self):
        with self.assertRaisesRegex(ValueError, "50000"):
            self.dmm.configure_data_log(50_001)
        with self.assertRaises(TypeError):
            self.dmm.configure_data_log(True)
        with self.assertRaises(TypeError):
            self.dmm.configure_data_log(10.0)

    def test_volatile_acquisition_allows_one_million_points(self):
        result = self.dmm.configure_volatile_acquisition(
            VOLATILE_MEMORY_POINTS, trigger_source="bus"
        )
        self.assertEqual(result, 1_000_000)
        self.assertIn("SAMPle:COUNt 1000000", self.instrument.writes)
        self.assertIn("TRIGger:SOURce BUS", self.instrument.writes)

        with self.assertRaisesRegex(ValueError, "1000000"):
            self.dmm.configure_volatile_acquisition(1_000_001)

    def test_start_monitor_save_and_read_persistent_log(self):
        self.dmm.configure_data_log(3)
        self.instrument.nonvolatile_count = 17
        self.instrument.volatile_counts = [0, 2, 3]
        self.instrument.ascii_values["DATA:DATA? NVMEM"] = [1.0, 2.0, 3.0]

        self.dmm.start_data_log()
        saved = self.dmm.wait_for_data_log(timeout_seconds=2, poll_interval_seconds=0)
        readings = self.dmm.read_data_log(timeout_ms=12_345)

        self.assertEqual(saved, 3)
        self.assertEqual(readings, [1.0, 2.0, 3.0])
        self.assertIn("DATA:DELete NVMEM", self.instrument.writes)
        self.assertIn("INITiate", self.instrument.writes)
        self.assertIn("DATA:COPY NVMEM, RDG_STORE", self.instrument.writes)
        self.assertEqual(
            self.instrument.ascii_queries[-1],
            ("DATA:DATA? NVMEM", 12_345),
        )
        self.assertEqual(self.instrument.timeout, GLOBAL_TOUT)

    def test_progress_reports_target_and_completion(self):
        self.dmm.configure_data_log(10)
        self.instrument.volatile_counts = [4, 10]

        self.assertEqual(
            self.dmm.data_log_progress(),
            {"acquired": 4, "target": 10, "complete": False},
        )
        self.assertEqual(
            self.dmm.data_log_progress(),
            {"acquired": 10, "target": 10, "complete": True},
        )

    def test_save_rejects_incomplete_acquisition(self):
        self.dmm.configure_data_log(5)
        self.instrument.volatile_counts = [4]

        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.dmm.save_data_log()
        self.assertNotIn("DATA:COPY NVMEM, RDG_STORE", self.instrument.writes)

    def test_volatile_read_can_preserve_or_erase_data(self):
        self.instrument.ascii_values["FETCh?"] = [1.25, 2.5]
        self.instrument.ascii_values["R? 2"] = [1.25, 2.5]

        self.assertEqual(self.dmm.read_volatile_readings(), [1.25, 2.5])
        self.assertEqual(
            self.dmm.read_volatile_readings(erase=True, max_points=2),
            [1.25, 2.5],
        )
        with self.assertRaisesRegex(ValueError, "erase=True"):
            self.dmm.read_volatile_readings(max_points=2)

    def test_close_closes_instrument(self):
        self.dmm.close()
        self.assertTrue(self.instrument.closed)
        self.assertEqual(self.instrument.clears, 2)


if __name__ == "__main__":
    unittest.main()
