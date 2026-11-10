"""P2-07 Keysight 34411A math, stats, dB/dBm, limits and function null."""

import math
import pytest

from dmm34411a import DMM_34411A, MeasurementFunction as F
from dmm34411a.calculation import MathController, MathMode, Limits, Statistics
from scpi_driver_core import ConfigurationError, UnsupportedOperationError
from scpi_driver_core.simulation import ScriptedScpiTransport


def fake(*, mode="NULL", enabled="0"):
    return (ScriptedScpiTransport(unknown_command_error=None)
            .on("*IDN?", "Agilent Technologies,34411A,TEST123,1.0")
            .on("CALCulate:STATe?", enabled)
            .on("CALCulate:FUNCtion?", mode))


def test_enable_statistics_explicitly_after_mode_setup():
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_dc_voltage()
        dmm.math.enable_statistics()
    assert tr.history == [
        "*IDN?", "CONFigure:VOLTage:DC", "CALCulate:STATe?",
        "CALCulate:FUNCtion?", "CALCulate:FUNCtion AVERage",
        "CALCulate:STATe ON",
    ]


def test_repeat_enable_stats_does_not_clear_accumulated_data():
    tr = fake(mode="AVER", enabled="1")
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_dc_voltage()
        dmm.math.enable_statistics()
    assert tr.history == ["*IDN?", "CONFigure:VOLTage:DC",
                          "CALCulate:STATe?", "CALCulate:FUNCtion?"]


def test_math_exclusive_conflict_preserves_current_mode():
    tr = fake(mode="DB", enabled="1")
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_dc_voltage()
        with pytest.raises(FileExistsError):
            dmm.math.enable_statistics()
        with pytest.raises(FileExistsError):
            dmm.math.configure_limits(0, 10)
        dmm.math.enable_statistics(replace=True)
    assert tr.history[-2:] == ["CALCulate:FUNCtion AVERage", "CALCulate:STATe ON"]
    assert "CALCulate:LIMit:LOWer 0" not in tr.history


def test_statistics_readback_typed_and_ordered():
    tr = (fake(mode="AVERage", enabled="1")
          .on("CALCulate:AVERage:COUNt?", "3")
          .on("CALCulate:AVERage:AVERage?", "2.0")
          .on("CALCulate:AVERage:MINimum?", "1.0")
          .on("CALCulate:AVERage:MAXimum?", "3.0")
          .on("CALCulate:AVERage:SDEViation?", "1")
          .on("CALCulate:AVERage:PTPeak?", "2"))
    with DMM_34411A(transport=tr) as dmm:
        result = dmm.math.read_statistics()
    assert result == Statistics(3, 2, 1, 3, 1, 2)
    assert tr.history == [
        "*IDN?", "CALCulate:STATe?", "CALCulate:FUNCtion?",
        "CALCulate:AVERage:COUNt?", "CALCulate:AVERage:AVERage?",
        "CALCulate:AVERage:MINimum?", "CALCulate:AVERage:MAXimum?",
        "CALCulate:AVERage:SDEViation?", "CALCulate:AVERage:PTPeak?"
    ]


def test_zero_statistics_count_has_no_fake_values():
    tr = fake(mode="AVER", enabled="1").on("CALCulate:AVERage:COUNt?", "0")
    with DMM_34411A(transport=tr) as dmm:
        assert dmm.math.read_statistics() == Statistics(count=0)
    assert "CALCulate:AVERage:AVERage?" not in tr.history


def test_clear_statistics_requires_opt_in_and_active_mode():
    tr = fake(mode="AVER", enabled="1")
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(PermissionError):
            dmm.math.clear_statistics()
        dmm.math.clear_statistics(confirm=True)
    assert tr.history == ["*IDN?", "CALCulate:STATe?",
                          "CALCulate:FUNCtion?", "CALCulate:AVERage:CLEar"]


def test_db_configuration_requires_voltage_and_valid_reference():
    tr = fake().on("CALCulate:DB:REFerence?", "2")
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_ac_voltage()
        dmm.math.configure_db(2.0)
        assert dmm.math.get_db_reference() == 2.0
    assert tr.history == [
        "*IDN?", "CONFigure:VOLTage:AC", "CALCulate:STATe?",
        "CALCulate:FUNCtion?", "CALCulate:DB:REFerence 2",
        "CALCulate:FUNCtion DB", "CALCulate:STATe ON",
        "CALCulate:DB:REFerence?",
    ]


def test_dbm_resistor_bounded_to_documented_values():
    tr = fake().on("CALCulate:DBM:REFerence?", "600")
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_dc_voltage()
        dmm.math.configure_dbm(600)
        assert dmm.math.get_dbm_reference() == 600
    assert "CALCulate:DBM:REFerence 600" in tr.history
    assert "CALCulate:FUNCtion DBM" in tr.history


def test_limit_configuration_and_host_comparison():
    tr = (fake().on("CALCulate:LIMit:LOWer?", "-1")
          .on("CALCulate:LIMit:UPPer?", "2"))
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_dc_voltage()
        dmm.math.configure_limits(-1, 2)
        assert dmm.math.get_limits() == Limits(-1, 2)
        assert dmm.math.evaluate_limits(1.2) is True
        assert dmm.math.evaluate_limits(2.3) is False
    assert "CALCulate:LIMit:LOWer -1" in tr.history
    assert "CALCulate:LIMit:UPPer 2" in tr.history
    assert "CALCulate:FUNCtion LIMit" in tr.history
    assert not any(q.startswith(("MEASure?", "*RST", "*CLS")) for q in tr.history)


@pytest.mark.parametrize("function,path", [
    (F.DC_VOLTAGE, "VOLTage:DC"),
    (F.AC_VOLTAGE, "VOLTage:AC"),
    (F.DC_CURRENT, "CURRent:DC"),
    (F.AC_CURRENT, "CURRent:AC"),
    (F.RESISTANCE_2W, "RESistance"),
    (F.RESISTANCE_4W, "FRESistance"),
    (F.FREQUENCY, "FREQuency"),
    (F.PERIOD, "PERiod"),
    (F.CAPACITANCE, "CAPacitance"),
    (F.TEMPERATURE, "TEMPerature"),
])
def test_null_per_function_does_not_select_deprecated_calc_null(function, path):
    tr = (fake().on(f"SENSe:{path}:NULL:VALue?", "0.25")
          .on(f"SENSe:{path}:NULL:STATe?", "1"))
    with DMM_34411A(transport=tr) as dmm:
        dmm.math.set_null(function, 0.25)
        assert dmm.math.get_null(function) == (0.25, True)
    assert tr.history == [
        "*IDN?", f"SENSe:{path}:NULL:VALue 0.25",
        f"SENSe:{path}:NULL:STATe ON",
        f"SENSe:{path}:NULL:VALue?", f"SENSe:{path}:NULL:STATe?",
    ]
    assert not any(s.startswith("CALCulate:FUNCtion") for s in tr.history)


@pytest.mark.parametrize("call,kind", [
    (lambda c: c.configure_db(0), ConfigurationError),
    (lambda c: c.configure_db(float("nan")), ConfigurationError),
    (lambda c: c.configure_db(-1), ConfigurationError),
    (lambda c: c.configure_db("1;*RST"), ConfigurationError),
    (lambda c: c.configure_dbm(601), ConfigurationError),
    (lambda c: c.configure_dbm(True), ConfigurationError),
    (lambda c: c.configure_limits(1, 1), ConfigurationError),
    (lambda c: c.configure_limits(2, 1), ConfigurationError),
    (lambda c: c.configure_limits(float("inf"), 3), ConfigurationError),
    (lambda c: c.configure_limits(-2, True), ConfigurationError),
    (lambda c: c.set_null(F.DIODE, 0), UnsupportedOperationError),
    (lambda c: c.set_null(F.CONTINUITY, 0), UnsupportedOperationError),
    (lambda c: c.set_null(F.DC_VOLTAGE, "0;*CLS"), ConfigurationError),
    (lambda c: c.set_null(F.DC_VOLTAGE, 0, enabled="ON"), ConfigurationError),
    (lambda c: c.enable_statistics(replace="ON"), ConfigurationError),
])
def test_invalid_inputs_no_math_or_null_write(call,kind):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_dc_voltage()
        with pytest.raises(kind):
            call(dmm.math)
    assert not any(s.endswith((":STATe ON", ":STATe OFF")) or
                   s.startswith(("CALCulate:LIMit:LOWer ", "CALCulate:FUNCtion ",
                                 "CALCulate:DB:REFerence ", "CALCulate:DBM:REFerence ",
                                 "SENSe:VOLTage:DC:NULL:VALue "))
                   for s in tr.history)


def test_unconfigured_math_cannot_change_externally_selected_current_or_diode():
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(RuntimeError):
            dmm.math.enable_statistics()
        dmm.configure_diode()
        with pytest.raises(UnsupportedOperationError):
            dmm.math.configure_limits(-1, 1)
        with pytest.raises(UnsupportedOperationError):
            dmm.math.configure_db(1.0)
    assert tr.history == ["*IDN?", "CONFigure:DIODe"]


def test_malformed_readbacks_raise_without_retry():
    tr = (fake(mode="AVER", enabled="1")
          .on("CALCulate:AVERage:COUNt?", "nan"))
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ValueError):
            dmm.math.read_statistics()
    assert tr.history.count("CALCulate:AVERage:COUNt?") == 1


def test_disabled_state_and_malformed_mode_block_statistic_read():
    tr = fake(mode="NULL", enabled="0")
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(RuntimeError):
            dmm.math.read_statistics()
    assert tr.history == ["*IDN?", "CALCulate:STATe?"]


def test_disable_does_not_reconfigure_or_reset():
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        dmm.math.disable()
    assert tr.history == ["*IDN?", "CALCulate:STATe OFF"]
