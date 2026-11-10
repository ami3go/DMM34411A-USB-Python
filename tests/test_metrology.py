"""P1-03 34411A metrology controls: table-driven SCPI and safety regression."""

from __future__ import annotations

import math

import pytest

from dmm34411a import DMM_34411A, MeasurementFunction as F
from dmm34411a.metrology import MetrologyController, MetrologySnapshot
from scpi_driver_core import ConfigurationError, UnsupportedOperationError
from scpi_driver_core.simulation import ScriptedScpiTransport


IDN = "Agilent Technologies,34411A,TEST123,1.0"


def fake(idn: str = IDN) -> ScriptedScpiTransport:
    return ScriptedScpiTransport(unknown_command_error=None).on("*IDN?", idn)


@pytest.mark.parametrize(
    "function,prefix,range_value",
    [
        (F.DC_VOLTAGE, "SENSe:VOLTage:DC", 10),
        (F.AC_VOLTAGE, "SENSe:VOLTage:AC", 100),
        (F.DC_CURRENT, "SENSe:CURRent:DC", 0.1),
        (F.AC_CURRENT, "SENSe:CURRent:AC", 1),
        (F.RESISTANCE_2W, "SENSe:RESistance", 1000),
        (F.RESISTANCE_4W, "SENSe:FRESistance", 10000),
        (F.CAPACITANCE, "SENSe:CAPacitance", 1e-8),
    ],
)
def test_range_autorange_getters_and_effective_range(function, prefix, range_value):
    tr = fake().on(prefix + ":RANGe?", str(range_value)).on(
        prefix + ":RANGe:AUTO?", "1"
    )
    with DMM_34411A(transport=tr) as dmm:
        m = dmm.metrology
        m.set_range(function, range_value)
        m.set_range(function, "AUTO")
        m.set_autorange(function, True)
        assert m.get_autorange(function) is True
        assert m.get_range(function) == pytest.approx(range_value)
    assert tr.history == [
        "*IDN?", f"{prefix}:RANGe {range_value:g}",
        f"{prefix}:RANGe AUTO", f"{prefix}:RANGe:AUTO ON",
        f"{prefix}:RANGe:AUTO?", f"{prefix}:RANGe?"
    ]


@pytest.mark.parametrize(
    "function,value",
    [
        (F.DC_VOLTAGE, 0.001), (F.DC_VOLTAGE, 1001),
        (F.AC_VOLTAGE, 1000), (F.DC_CURRENT, 10), (F.RESISTANCE_2W, 1e10),
        (F.CAPACITANCE, 1), (F.CAPACITANCE, -1),
        (F.AC_CURRENT, float("nan")), (F.AC_CURRENT, float("inf")),
        (F.DC_VOLTAGE, True), (F.DC_VOLTAGE, "DEFAULT"),
        (F.DC_VOLTAGE, "1000;*RST"),
        (F.DC_VOLTAGE, object()), (F.DC_VOLTAGE, 10**400),
    ],
)
def test_invalid_range_rejected_without_hardware_write(function, value):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.metrology.set_range(function, value)
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize(
    "function", [F.CONTINUITY, F.DIODE, F.TEMPERATURE]
)
def test_range_is_not_a_generic_command_for_any_function(function):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.set_range(function, 1)
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.get_range(function)
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.set_autorange(function, True)
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize(
    "function,prefix", [
        (F.AC_VOLTAGE, "SENSe:VOLTage:AC"),
        (F.DC_VOLTAGE, "SENSe:VOLTage:DC"),
        (F.AC_CURRENT, "SENSe:CURRent:AC"),
        (F.DC_CURRENT, "SENSe:CURRent:DC"),
        (F.RESISTANCE_2W, "SENSe:RESistance"),
        (F.RESISTANCE_4W, "SENSe:FRESistance"),
    ]
)
def test_resolution_numeric_symbolic_and_live_query(function, prefix):
    tr = fake().on(prefix + ":RESolution?", "1.0E-6")
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_resolution(function, "MIN")
        dmm.metrology.set_resolution(function, 1e-6)
        assert dmm.metrology.get_resolution(function) == pytest.approx(1e-6)
    assert tr.history == [
        "*IDN?", prefix + ":RESolution MIN",
        prefix + ":RESolution 1e-06", prefix + ":RESolution?",
    ]


@pytest.mark.parametrize("function", [F.CAPACITANCE, F.DIODE, F.FREQUENCY])
def test_resolution_restricted(function):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.set_resolution(function, "MIN")
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize(
    "value", [0, 0.003, 0.025, 0.19, 101, -2, float("nan"), True, "NPLC"]
)
def test_invalid_nplc_rejected_without_instrument_writes(value):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.metrology.set_nplc(F.DC_VOLTAGE, value)
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize("nplc", [0.001, 0.002, 0.006, 0.02, 0.06, 0.2, 1, 2, 10, 100])
def test_34411a_fast_and_standard_nplc_choices(nplc):
    tr = fake().on("SENSe:VOLTage:DC:NPLC?", str(nplc))
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_nplc(F.DC_VOLTAGE, nplc)
        assert dmm.metrology.get_nplc(F.DC_VOLTAGE) == pytest.approx(nplc)
    assert tr.history == ["*IDN?", f"SENSe:VOLTage:DC:NPLC {nplc:g}",
                          "SENSe:VOLTage:DC:APERture:ENABled OFF",
                          "SENSe:VOLTage:DC:NPLC?"]


def test_34411a_only_fast_nplc_and_short_aperture_not_used_on_34410a():
    tr = fake("Agilent Technologies,34410A,TEST123,1.0")
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.set_nplc(F.DC_VOLTAGE, 0.001)
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.set_aperture(F.DC_VOLTAGE, 2e-5)
        dmm.metrology.set_nplc(F.DC_VOLTAGE, 0.006)
        dmm.metrology.set_aperture(F.DC_VOLTAGE, 0.0001)
    assert tr.history == ["*IDN?", "SENSe:VOLTage:DC:NPLC 0.006",
                          "SENSe:VOLTage:DC:APERture:ENABled OFF",
                          "SENSe:VOLTage:DC:APERture 0.0001",
                          "SENSe:VOLTage:DC:APERture:ENABled ON"]


@pytest.mark.parametrize("function,prefix", [
    (F.DC_VOLTAGE, "SENSe:VOLTage:DC"), (F.DC_CURRENT, "SENSe:CURRent:DC"),
    (F.RESISTANCE_2W, "SENSe:RESistance"),
    (F.RESISTANCE_4W, "SENSe:FRESistance"), (F.TEMPERATURE, "SENSe:TEMPerature")
])
def test_nplc_aperture_mode_selection_is_explicit(function, prefix):
    enable_token = "ENABle" if function is F.RESISTANCE_4W else "ENABled"
    tr = fake().on(prefix + ":APERture?", "0.001").on(
        f"{prefix}:APERture:{enable_token}?", "1"
    ).on(prefix + ":NPLC?", "1")
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_aperture(function, 0.001)
        dmm.metrology.set_aperture_enabled(function, True)
        assert dmm.metrology.get_aperture_enabled(function)
        assert dmm.metrology.get_aperture(function) == .001
        dmm.metrology.set_nplc(function, "DEF")
        assert dmm.metrology.get_nplc(function) == 1
    assert tr.history == [
        "*IDN?", prefix + ":APERture 0.001",
        f"{prefix}:APERture:{enable_token} ON",
        f"{prefix}:APERture:{enable_token} ON",
        f"{prefix}:APERture:{enable_token}?",
        prefix + ":APERture?", prefix + ":NPLC DEF",
        f"{prefix}:APERture:{enable_token} OFF", prefix + ":NPLC?",
    ]


@pytest.mark.parametrize("value", [0, -1, 0.000019, 1.0001, math.inf, math.nan, False])
def test_aperture_out_of_bounds(value):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.metrology.set_aperture(F.DC_VOLTAGE, value)
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize("function", [F.AC_VOLTAGE, F.AC_CURRENT, F.FREQUENCY, F.DIODE])
def test_nplc_not_supported_for_non_integrating_functions(function):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.set_nplc(function, 1)
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize("state,token", [(True, "ON"), (False, "OFF"), ("ONCE", "ONCE")])
def test_autozero_dc_and_once(state, token):
    tr = fake().on("SENSe:VOLTage:DC:ZERO:AUTO?", "1")
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_autozero(F.DC_VOLTAGE, state)
        assert dmm.metrology.get_autozero(F.DC_VOLTAGE) is True
    assert tr.history == ["*IDN?", "SENSe:VOLTage:DC:ZERO:AUTO " + token,
                          "SENSe:VOLTage:DC:ZERO:AUTO?"]


def test_4wire_autozero_not_independently_switchable():
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.set_autozero(F.RESISTANCE_4W, False)
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.get_autozero(F.RESISTANCE_4W)
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize("function", [F.AC_VOLTAGE, F.AC_CURRENT])
@pytest.mark.parametrize("hz", [3, 20, 200])
def test_ac_filter(function, hz):
    prefix = "VOLTage:AC" if function is F.AC_VOLTAGE else "CURRent:AC"
    tr = fake().on(f"SENSe:{prefix}:BANDwidth?", str(hz))
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_ac_bandwidth(function, hz)
        assert dmm.metrology.get_ac_bandwidth(function) == hz
    assert tr.history == ["*IDN?", f"SENSe:{prefix}:BANDwidth {hz}",
                          f"SENSe:{prefix}:BANDwidth?"]


@pytest.mark.parametrize("hz", [0, 10, 199, 200.5, True, math.nan, "3;*RST"])
def test_invalid_ac_bandwidth_no_write(hz):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.metrology.set_ac_bandwidth(F.AC_VOLTAGE, hz)
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize("function,prefix", [
    (F.FREQUENCY, "SENSe:FREQuency"),
    (F.PERIOD, "SENSe:PERiod"),
])
@pytest.mark.parametrize("seconds", [0.001, 0.01, 0.1, 1.0])
def test_gate_time(function, prefix, seconds):
    tr = fake().on(prefix + ":APERture?", str(seconds))
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_gate_time(function, seconds)
        assert dmm.metrology.get_gate_time(function) == seconds
    assert tr.history == ["*IDN?", f"{prefix}:APERture {seconds:g}",
                          prefix + ":APERture?"]


@pytest.mark.parametrize("seconds", [0, 0.005, 0.5, 2, None, False, "1s"])
def test_invalid_gate_seconds_no_write(seconds):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.metrology.set_gate_time(F.FREQUENCY, seconds)
    assert tr.history == ["*IDN?"]


def test_input_impedance_and_temperature_units():
    tr = fake().on("SENSe:VOLTage:DC:IMPedance:AUTO?", "1").on(
        "UNIT:TEMPerature?", "F"
    )
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_input_impedance_auto(True)
        assert dmm.metrology.get_input_impedance_auto()
        dmm.metrology.set_temperature_unit("F")
        assert dmm.metrology.get_temperature_unit() == "F"
    assert tr.history == [
        "*IDN?", "SENSe:VOLTage:DC:IMPedance:AUTO ON",
        "SENSe:VOLTage:DC:IMPedance:AUTO?",
        "UNIT:TEMPerature F", "UNIT:TEMPerature?",
    ]


@pytest.mark.parametrize("bad_unit", ["C;", "C\n*RST", "Kelvin", True, 1, ""])
def test_bad_temperature_unit_rejected(bad_unit):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.metrology.set_temperature_unit(bad_unit)
    assert tr.history == ["*IDN?"]


def test_offset_compensation_fixed_low_range_check():
    tr = fake().on("SENSe:RESistance:RANGe:AUTO?", "0").on(
        "SENSe:RESistance:RANGe?", "1000"
    ).on("SENSe:RESistance:OCOMpensated?", "1")
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_offset_compensation(F.RESISTANCE_2W, True)
        assert dmm.metrology.get_offset_compensation(F.RESISTANCE_2W)
        dmm.metrology.set_offset_compensation(F.RESISTANCE_2W, False)
    assert tr.history == [
        "*IDN?", "SENSe:RESistance:RANGe:AUTO?",
        "SENSe:RESistance:RANGe?", "SENSe:RESistance:OCOMpensated ON",
        "SENSe:RESistance:OCOMpensated?", "SENSe:RESistance:OCOMpensated OFF",
    ]


@pytest.mark.parametrize("autorange,range_value", [("1", "100"), ("0", "100000")])
def test_offset_compensation_unsafe_range_does_not_send_write(autorange, range_value):
    tr = fake().on("SENSe:RESistance:RANGe:AUTO?", autorange).on(
        "SENSe:RESistance:RANGe?", range_value
    )
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.metrology.set_offset_compensation(F.RESISTANCE_2W, True)
    assert "SENSe:RESistance:OCOMpensated ON" not in tr.history


def test_snapshot_reads_instrument_and_does_not_assume_cache():
    tr = (fake()
          .on("SENSe:VOLTage:DC:RANGe?", "10.0")
          .on("SENSe:VOLTage:DC:RANGe:AUTO?", "0")
          .on("SENSe:VOLTage:DC:RESolution?", "0.00001")
          .on("SENSe:VOLTage:DC:NPLC?", "10")
          .on("SENSe:VOLTage:DC:APERture?", "0.01")
          .on("SENSe:VOLTage:DC:APERture:ENABled?", "0")
          .on("SENSe:VOLTage:DC:ZERO:AUTO?", "1")
          .on("SENSe:VOLTage:DC:IMPedance:AUTO?", "0"))
    with DMM_34411A(transport=tr) as dmm:
        s = dmm.metrology.snapshot(F.DC_VOLTAGE)
        assert isinstance(s, MetrologySnapshot)
        assert s.function is F.DC_VOLTAGE
        assert s.range_value == 10
        assert s.autorange is False
        assert s.nplc == 10
        assert s.aperture_seconds == 0.01
        assert s.aperture_enabled is False
        assert s.autozero is True
        assert s.input_impedance_auto is False
        assert s.ac_bandwidth_hz is None
    assert len(tr.history) == 9
    assert not any(c.startswith(("CONFigure", "DATA:DELete", "MEASure", "*RST")) for c in tr.history)


@pytest.mark.parametrize("response", ["nan", "inf", "-inf", "n/a", "1,2"])
def test_malformed_numeric_query_not_accepted(response):
    tr = fake().on("SENSe:VOLTage:AC:RANGe?", response)
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ValueError):
            dmm.metrology.get_range(F.AC_VOLTAGE)


@pytest.mark.parametrize("response", ["1.5", "xyz", "", "2", "-1"])
def test_malformed_flag_query_not_accepted(response):
    tr = fake().on("SENSe:VOLTage:AC:RANGe:AUTO?", response)
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ValueError):
            dmm.metrology.get_autorange(F.AC_VOLTAGE)


def test_metrology_does_not_change_active_measurement_or_nvm_state():
    tr = fake().on("READ?", "1.5").on("DATA:POINts? NVMEM", "7")
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_dc_voltage()
        dmm.metrology.set_nplc(F.DC_VOLTAGE, 1)
        dmm.metrology.set_input_impedance_auto(False)
        assert dmm.measurement.read().value == 1.5
        assert dmm.nonvolatile_point_count() == 7
    assert tr.history == [
        "*IDN?", "CONFigure:VOLTage:DC", "SENSe:VOLTage:DC:NPLC 1",
        "SENSe:VOLTage:DC:APERture:ENABled OFF",
        "SENSe:VOLTage:DC:IMPedance:AUTO OFF", "READ?", "DATA:POINts? NVMEM",
    ]



@pytest.mark.parametrize(("function","path"), [
    (F.FREQUENCY, "SENSe:FREQuency:VOLTage:RANGe"),
    (F.PERIOD, "SENSe:PERiod:VOLTage:RANGe"),
])
def test_frequency_period_input_range_is_voltage_not_hz(function, path):
    tr = fake().on(path + "?", "10").on(path + ":AUTO?", "1")
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_range(function, 10)
        dmm.metrology.set_range(function, "AUTO")
        dmm.metrology.set_autorange(function, True)
        assert dmm.metrology.get_range(function) == 10
        assert dmm.metrology.get_autorange(function) is True
    assert tr.history == [
        "*IDN?", path + " 10", path + ":AUTO ON",
        path + ":AUTO ON", path + "?", path + ":AUTO?"
    ]


@pytest.mark.parametrize("function", [F.FREQUENCY, F.PERIOD])
def test_frequency_period_use_ac_voltage_filter(function):
    tr = fake().on("SENSe:VOLTage:AC:BANDwidth?", "20")
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_ac_bandwidth(function, 3)
        assert dmm.metrology.get_ac_bandwidth(function) == 20
    assert tr.history == [
        "*IDN?", "SENSe:VOLTage:AC:BANDwidth 3",
        "SENSe:VOLTage:AC:BANDwidth?"
    ]


def test_four_wire_temperature_autozero_can_never_be_disabled():
    from dmm34411a import TemperatureProbe
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.set_autozero(F.TEMPERATURE, False)
        dmm.configure_temperature(TemperatureProbe.RTD_4W)
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.set_autozero(F.TEMPERATURE, False)
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.get_autozero(F.TEMPERATURE)
        snapshot = dmm.metrology.snapshot
        # No implicit temperature autozero query on 4-wire sensor.
        assert snapshot is not None
    assert tr.history == ["*IDN?", "CONFigure:TEMPerature FRTD,DEF"]


def test_two_wire_temperature_autozero_requires_known_config():
    from dmm34411a import TemperatureProbe
    tr = fake().on("SENSe:TEMPerature:ZERO:AUTO?", "1")
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_temperature(TemperatureProbe.RTD_2W)
        dmm.metrology.set_autozero(F.TEMPERATURE, "ONCE")
        assert dmm.metrology.get_autozero(F.TEMPERATURE)
    assert tr.history == [
        "*IDN?", "CONFigure:TEMPerature RTD,DEF",
        "SENSe:TEMPerature:ZERO:AUTO ONCE",
        "SENSe:TEMPerature:ZERO:AUTO?"
    ]


def test_frequency_period_snapshot_has_input_amplitude_and_filter():
    tr = (fake()
          .on("SENSe:FREQuency:VOLTage:RANGe?", "10")
          .on("SENSe:FREQuency:VOLTage:RANGe:AUTO?", "0")
          .on("SENSe:FREQuency:APERture?", "0.01")
          .on("SENSe:VOLTage:AC:BANDwidth?", "20"))
    with DMM_34411A(transport=tr) as dmm:
        result = dmm.metrology.snapshot(F.FREQUENCY)
        assert result.range_value == 10
        assert result.autorange is False
        assert result.gate_time_seconds == 0.01
        assert result.ac_bandwidth_hz == 20


def test_read_with_settings_attaches_instrument_values_to_typed_reading():
    tr = (fake()
          .on("SENSe:VOLTage:AC:RANGe?", "10")
          .on("SENSe:VOLTage:AC:RANGe:AUTO?", "0")
          .on("SENSe:VOLTage:AC:RESolution?", "1.0e-4")
          .on("SENSe:VOLTage:AC:BANDwidth?", "20")
          .on("READ?", "1.250000E+00"))
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_ac_voltage()
        result = dmm.metrology.read_with_settings()
        assert result.value == 1.25
        assert result.metrology is not None
        assert result.metrology.function is F.AC_VOLTAGE
        assert result.metrology.range_value == 10
        assert result.metrology.ac_bandwidth_hz == 20
        assert result.unit == "V"
    assert tr.history.count("READ?") == 1
    assert not any(x.startswith(("MEASure:", "*RST", "DATA:DELete")) for x in tr.history)


def test_read_with_settings_requires_explicit_config():
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(RuntimeError):
            dmm.metrology.read_with_settings()
    assert tr.history == ["*IDN?"]
