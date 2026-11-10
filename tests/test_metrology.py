"""P1-03: 34411A metrology configuration, readback and negative/failure tests.

Uses scpi-driver-core scripted transport; no physical instrument.
"""
from __future__ import annotations

import math

import pytest

from dmm34411a import (
    DMM_34411A, MeasurementConfig, MeasurementFunction as F, TemperatureProbe,
    MetrologySettings,
)
from scpi_driver_core import ConfigurationError, UnsupportedOperationError, TransportTimeoutError
from scpi_driver_core.simulation import ScriptedReply, ScriptedScpiTransport


def sim():
    return ScriptedScpiTransport(unknown_command_error=None).on(
        "*IDN?", "Agilent Technologies,34411A,TEST123,1.0"
    )


@pytest.mark.parametrize(
    ("function", "path", "max_range"),
    [
        (F.DC_VOLTAGE, "VOLTage:DC", 1000),
        (F.AC_VOLTAGE, "VOLTage:AC", 750),
        (F.DC_CURRENT, "CURRent:DC", 3),
        (F.AC_CURRENT, "CURRent:AC", 3),
        (F.RESISTANCE_2W, "RESistance", 1e9),
        (F.RESISTANCE_4W, "FRESistance", 1e9),
        (F.CAPACITANCE, "CAPacitance", 0.01),
        (F.FREQUENCY, "FREQuency:VOLTage", 750),
        (F.PERIOD, "PERiod:VOLTage", 750),
    ],
)
def test_range_selection_and_numeric_readback(function, path, max_range):
    tr = sim().on(f"SENSe:{path}:RANGe?", f"{max_range:.9g}").on(
        f"SENSe:{path}:RANGe:AUTO?", "1"
    )
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_range(function, max_range)
        dmm.metrology.set_autorange(function, True)
        assert dmm.metrology.get_range(function) == pytest.approx(max_range)
        assert dmm.metrology.get_autorange(function) is True
    assert tr.history == [
        "*IDN?", f"SENSe:{path}:RANGe {max_range:.12g}",
        f"SENSe:{path}:RANGe:AUTO ON",
        f"SENSe:{path}:RANGe?", f"SENSe:{path}:RANGe:AUTO?"
    ]


def test_range_auto_then_manual_does_not_switch_measurement_function():
    tr = sim()
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_range(F.DC_VOLTAGE, "AUTO")
        dmm.metrology.set_range(F.DC_VOLTAGE, 10.0)
        dmm.metrology.set_range(F.AC_VOLTAGE, "MIN")
    assert tr.history == [
        "*IDN?", "SENSe:VOLTage:DC:RANGe:AUTO ON",
        "SENSe:VOLTage:DC:RANGe 10", "SENSe:VOLTage:AC:RANGe MIN"
    ]


@pytest.mark.parametrize("function", [
    F.DC_VOLTAGE, F.AC_VOLTAGE, F.DC_CURRENT, F.AC_CURRENT,
    F.RESISTANCE_2W, F.RESISTANCE_4W,
])
def test_resolution_set_query(function):
    from dmm34411a.metrology import _SENSE
    path = _SENSE[function]
    tr = sim().on(f"SENSe:{path}:RESolution?", "1.00000E-05")
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_resolution(function, 1e-5)
        dmm.metrology.set_resolution(function, "DEF")
        assert dmm.metrology.get_resolution(function) == pytest.approx(1e-5)
    assert tr.history == [
        "*IDN?", f"SENSe:{path}:RESolution 1e-05",
        f"SENSe:{path}:RESolution DEF", f"SENSe:{path}:RESolution?"
    ]


@pytest.mark.parametrize(
    ("function", "path"),
    [
        (F.DC_VOLTAGE, "VOLTage:DC"),
        (F.DC_CURRENT, "CURRent:DC"),
        (F.RESISTANCE_2W, "RESistance"),
        (F.RESISTANCE_4W, "FRESistance"),
        (F.TEMPERATURE, "TEMPerature"),
    ],
)
def test_nplc_and_aperture_are_explicitly_mutually_exclusive(function, path):
    tr = sim().on(f"SENSe:{path}:NPLC?", "1").on(
        f"SENSe:{path}:APERture?", "0.000020"
    ).on(f"SENSe:{path}:APERture:ENABled?", "1")
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_nplc(function, 0.001)
        assert dmm.metrology.get_nplc(function) == 1.0
        dmm.metrology.set_aperture(function, 20e-6)
        assert dmm.metrology.get_aperture(function) == pytest.approx(20e-6)
        assert dmm.metrology.get_aperture_enabled(function) is True
        dmm.metrology.set_aperture_enabled(function, False)
    assert tr.history == [
        "*IDN?", f"SENSe:{path}:NPLC 0.001",
        f"SENSe:{path}:APERture:ENABled OFF",
        f"SENSe:{path}:NPLC?",
        f"SENSe:{path}:APERture 2e-05",
        f"SENSe:{path}:APERture:ENABled ON",
        f"SENSe:{path}:APERture?", f"SENSe:{path}:APERture:ENABled?",
        f"SENSe:{path}:APERture:ENABled OFF",
    ]


@pytest.mark.parametrize("function", [F.AC_VOLTAGE, F.AC_CURRENT, F.FREQUENCY, F.PERIOD])
def test_ac_filter_uses_documented_scpi_paths(function):
    path = "CURRent:AC" if function is F.AC_CURRENT else "VOLTage:AC"
    tr = sim().on(f"SENSe:{path}:BANDwidth?", "20")
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_ac_bandwidth(function, 3)
        assert dmm.metrology.get_ac_bandwidth(function) == 20
    assert tr.history == ["*IDN?", f"SENSe:{path}:BANDwidth 3",
                          f"SENSe:{path}:BANDwidth?"]


@pytest.mark.parametrize("function", [F.FREQUENCY, F.PERIOD])
def test_gate_times_and_readback(function):
    path = "FREQuency" if function is F.FREQUENCY else "PERiod"
    tr = sim().on(f"SENSe:{path}:APERture?", "1.0E-2")
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_gate_time(function, 0.01)
        assert dmm.metrology.get_gate_time(function) == pytest.approx(0.01)
    assert tr.history == ["*IDN?", f"SENSe:{path}:APERture 0.01",
                          f"SENSe:{path}:APERture?"]


def test_dc_input_impedance_and_autozero():
    tr = sim().on("SENSe:VOLTage:DC:IMPedance:AUTO?", "1").on(
        "SENSe:VOLTage:DC:ZERO:AUTO?", "0"
    )
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_input_impedance_auto(True)
        assert dmm.metrology.get_input_impedance_auto() is True
        dmm.metrology.set_autozero(F.DC_VOLTAGE, "ONCE")
        assert dmm.metrology.get_autozero(F.DC_VOLTAGE) is False
    assert tr.history == [
        "*IDN?", "SENSe:VOLTage:DC:IMPedance:AUTO ON",
        "SENSe:VOLTage:DC:IMPedance:AUTO?",
        "SENSe:VOLTage:DC:ZERO:AUTO ONCE",
        "SENSe:VOLTage:DC:ZERO:AUTO?",
    ]


def test_2wire_temperature_autozero_requires_explicit_probe_configuration():
    tr = sim()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.set_autozero(F.TEMPERATURE, False)
        dmm.configure_temperature(TemperatureProbe.RTD_4W)
        with pytest.raises(UnsupportedOperationError):
            dmm.metrology.set_autozero(F.TEMPERATURE, False)
        dmm.configure_temperature(TemperatureProbe.RTD_2W)
        dmm.metrology.set_autozero(F.TEMPERATURE, True)
    assert tr.history == [
        "*IDN?", "CONFigure:TEMPerature FRTD,DEF",
        "CONFigure:TEMPerature RTD,DEF", "SENSe:TEMPerature:ZERO:AUTO ON"
    ]


@pytest.mark.parametrize("function,path", [
    (F.RESISTANCE_2W, "RESistance"),
    (F.RESISTANCE_4W, "FRESistance"),
])
def test_offset_compensation_requires_low_fixed_range(function, path):
    tr = sim().on(f"SENSe:{path}:RANGe:AUTO?", "0").on(
        f"SENSe:{path}:RANGe?", "1E3"
    ).on(f"SENSe:{path}:OCOMpensated?", "1")
    with DMM_34411A(transport=tr) as dmm:
        dmm.metrology.set_offset_compensated(function, True)
        assert dmm.metrology.get_offset_compensated(function) is True
        dmm.metrology.set_offset_compensated(function, False)
    assert tr.history == [
        "*IDN?", f"SENSe:{path}:RANGe:AUTO?", f"SENSe:{path}:RANGe?",
        f"SENSe:{path}:OCOMpensated ON",
        f"SENSe:{path}:OCOMpensated?", f"SENSe:{path}:OCOMpensated OFF"
    ]


def test_offset_compensation_rejects_autorange_without_write():
    tr = sim().on("SENSe:RESistance:RANGe:AUTO?", "1")
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.metrology.set_offset_compensated(F.RESISTANCE_2W, True)
    assert tr.history == ["*IDN?", "SENSe:RESistance:RANGe:AUTO?"]


def test_live_setting_snapshot_and_result_metadata():
    tr = sim().on("SENSe:VOLTage:AC:RANGe?", "10.0").on(
        "SENSe:VOLTage:AC:RANGe:AUTO?", "0"
    ).on("SENSe:VOLTage:AC:RESolution?", "0.0001").on(
        "SENSe:VOLTage:AC:BANDwidth?", "20"
    ).on("READ?", "1.2345")
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_ac_voltage()
        settings = dmm.metrology.get_settings(F.AC_VOLTAGE)
        assert isinstance(settings, MetrologySettings)
        assert settings.range_value == 10
        assert settings.autorange is False
        assert settings.ac_bandwidth_hz == 20
        assert settings.nplc is None
        typed = dmm.metrology.read_with_settings()
        assert typed.value == pytest.approx(1.2345)
        assert typed.metrology == settings
        assert typed.unit == "V"
    assert tr.history.count("READ?") == 1
    assert "MEASure:VOLTage:AC?" not in tr.history


@pytest.mark.parametrize(
    ("call", "err"),
    [
        (lambda m: m.set_range(F.TEMPERATURE, 1), UnsupportedOperationError),
        (lambda m: m.set_range(F.DIODE, 1), UnsupportedOperationError),
        (lambda m: m.set_range(F.DC_VOLTAGE, True), ConfigurationError),
        (lambda m: m.set_range(F.DC_VOLTAGE, "AUTO\n*RST"), ConfigurationError),
        (lambda m: m.set_range(F.DC_VOLTAGE, float("inf")), ConfigurationError),
        (lambda m: m.set_range(F.DC_VOLTAGE, -5), ConfigurationError),
        (lambda m: m.set_range(F.AC_VOLTAGE, 1000), ConfigurationError),
        (lambda m: m.set_range(F.DC_CURRENT, 4), ConfigurationError),
        (lambda m: m.set_autorange(F.CAPACITANCE, "ON"), ConfigurationError),
        (lambda m: m.set_resolution(F.CAPACITANCE, 0.1), UnsupportedOperationError),
        (lambda m: m.set_resolution(F.RESISTANCE_2W, math.nan), ConfigurationError),
        (lambda m: m.set_resolution(F.AC_VOLTAGE, "MIN\n*CLS"), ConfigurationError),
        (lambda m: m.set_nplc(F.AC_CURRENT, 1), UnsupportedOperationError),
        (lambda m: m.set_nplc(F.DC_CURRENT, 0.0011), ConfigurationError),
        (lambda m: m.set_nplc(F.DC_VOLTAGE, True), ConfigurationError),
        (lambda m: m.set_aperture(F.AC_VOLTAGE, 0.1), UnsupportedOperationError),
        (lambda m: m.set_aperture(F.DC_VOLTAGE, 19.9e-6), ConfigurationError),
        (lambda m: m.set_aperture(F.DC_VOLTAGE, 1.1), ConfigurationError),
        (lambda m: m.set_aperture_enabled(F.DC_VOLTAGE, "ON"), ConfigurationError),
        (lambda m: m.set_autozero(F.RESISTANCE_4W, False), UnsupportedOperationError),
        (lambda m: m.set_autozero(F.DC_CURRENT, "BAD"), ConfigurationError),
        (lambda m: m.set_ac_bandwidth(F.DC_VOLTAGE, 20), UnsupportedOperationError),
        (lambda m: m.set_ac_bandwidth(F.AC_VOLTAGE, 19), ConfigurationError),
        (lambda m: m.set_gate_time(F.AC_VOLTAGE, 0.1), UnsupportedOperationError),
        (lambda m: m.set_gate_time(F.FREQUENCY, 0.0005), ConfigurationError),
        (lambda m: m.set_input_impedance_auto(1), ConfigurationError),
        (lambda m: m.set_offset_compensated(F.AC_VOLTAGE, True), UnsupportedOperationError),
        (lambda m: m.set_offset_compensated(F.RESISTANCE_2W, "ON"), ConfigurationError),
        (lambda m: m.get_settings(F.CONTINUITY), UnsupportedOperationError),
    ],
)
def test_invalid_or_unsupported_setting_sends_no_scpi_mutation(call, err):
    tr = sim()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(err):
            call(dmm.metrology)
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize(("command","raw"), [
    ("SENSe:VOLTage:DC:RANGe?", "nan"),
    ("SENSe:VOLTage:DC:RANGe?", "invalid"),
    ("SENSe:VOLTage:DC:RANGe?", ""),
])
def test_malformed_range_response_does_not_coerce_to_valid(command, raw):
    tr = sim().on(command, raw)
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ValueError):
            dmm.metrology.get_range(F.DC_VOLTAGE)


@pytest.mark.parametrize("raw", ["ON", "2", "", "nan", "1;*RST"])
def test_status_parsing_rejects_malformed_autorange(raw):
    tr = sim().on("SENSe:VOLTage:DC:RANGe:AUTO?", raw)
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ValueError):
            dmm.metrology.get_autorange(F.DC_VOLTAGE)


def test_single_failed_setting_not_replayed_after_timeout():
    tr = sim().on(
        "SENSe:VOLTage:DC:RANGe 10",
        ScriptedReply(raises=TransportTimeoutError("uncertain"), disconnect=True),
    )
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(TransportTimeoutError):
            dmm.metrology.set_range(F.DC_VOLTAGE, 10)
    assert tr.history.count("SENSe:VOLTage:DC:RANGe 10") == 1


def test_meter_existing_legacy_and_nvm_interfaces_still_accessible():
    tr = sim().on("MEASure:VOLTage:DC? AUTO", "1.2").on(
        "DATA:POINts? NVMEM", "0"
    )
    with DMM_34411A(transport=tr) as dmm:
        assert dmm.measure_voltage() == "1.2"
        assert dmm.nonvolatile_point_count() == 0
        dmm.metrology.set_range(F.DC_VOLTAGE, "MIN")
    assert tr.history == [
        "*IDN?", "MEASure:VOLTage:DC? AUTO",
        "DATA:POINts? NVMEM", "SENSe:VOLTage:DC:RANGe MIN"
    ]
