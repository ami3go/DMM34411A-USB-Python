"""P0-01 / P1-02: missing 34411A measurement families and typed safety."""

from datetime import timezone

import pytest

from dmm34411a import (
    DMM_34411A,
    MeasurementConfig,
    MeasurementFunction as F,
    TemperatureProbe,
)
from scpi_driver_core import ConfigurationError, TransportTimeoutError
from scpi_driver_core.simulation import ScriptedReply, ScriptedScpiTransport


def dmm_transport():
    return ScriptedScpiTransport(unknown_command_error=None).on(
        "*IDN?", "Agilent Technologies,34411A,TEST123,1.0"
    )


@pytest.mark.parametrize(
    ("function", "conf", "meas", "unit"),
    [
        (F.DC_VOLTAGE, "CONFigure:VOLTage:DC", "MEASure:VOLTage:DC?", "V"),
        (F.AC_VOLTAGE, "CONFigure:VOLTage:AC", "MEASure:VOLTage:AC?", "V"),
        (F.DC_CURRENT, "CONFigure:CURRent:DC", "MEASure:CURRent:DC?", "A"),
        (F.AC_CURRENT, "CONFigure:CURRent:AC", "MEASure:CURRent:AC?", "A"),
        (F.RESISTANCE_2W, "CONFigure:RESistance", "MEASure:RESistance?", "ohm"),
        (F.RESISTANCE_4W, "CONFigure:FRESistance", "MEASure:FRESistance?", "ohm"),
        (F.FREQUENCY, "CONFigure:FREQuency", "MEASure:FREQuency?", "Hz"),
        (F.PERIOD, "CONFigure:PERiod", "MEASure:PERiod?", "s"),
        (F.CAPACITANCE, "CONFigure:CAPacitance", "MEASure:CAPacitance?", "F"),
        (F.CONTINUITY, "CONFigure:CONTinuity", "MEASure:CONTinuity?", "ohm"),
        (F.DIODE, "CONFigure:DIODe", "MEASure:DIODe?", "V"),
    ],
)
def test_all_non_temperature_modes_have_configure_and_measure(function, conf, meas, unit):
    tr = dmm_transport().on(meas, "+1.234000E+00").on("READ?", "+2.345000E+00")
    with DMM_34411A(transport=tr) as dmm:
        config = MeasurementConfig(function)
        dmm.measurement.configure(config)
        result = dmm.measurement.read()
        assert result.function is function
        assert result.unit == unit
        assert result.value == pytest.approx(2.345)
        assert result.measured_at_utc.tzinfo is timezone.utc
        one_shot = dmm.measurement.measure(config)
        assert one_shot.value == pytest.approx(1.234)
        assert one_shot.raw == "+1.234000E+00"
        with pytest.raises(RuntimeError):
            dmm.measurement.read()
    assert tr.history == ["*IDN?", conf, "READ?", meas]


@pytest.mark.parametrize(
    ("probe", "token"),
    [
        (TemperatureProbe.RTD_2W, "RTD"),
        (TemperatureProbe.RTD_4W, "FRTD"),
        (TemperatureProbe.THERMISTOR_2W, "THERmistor"),
    ],
)
def test_temperature_probe_and_instrument_units(probe, token):
    conf = f"CONFigure:TEMPerature {token},DEF"
    meas = f"MEASure:TEMPerature? {token},DEF"
    tr = dmm_transport().on("UNIT:TEMPerature?", "C").on(
        "READ?", "+2.600000E+01"
    ).on(meas, "+2.500000E+01")
    with DMM_34411A(transport=tr) as dmm:
        config = MeasurementConfig(F.TEMPERATURE, temperature_probe=probe)
        dmm.measurement.configure(config)
        reading = dmm.measurement.read()
        assert reading.unit == "degC"
        assert reading.value == 26
        assert dmm.measurement.measure(config).value == 25
    assert tr.history == ["*IDN?", conf, "UNIT:TEMPerature?", "READ?",
                          "UNIT:TEMPerature?", meas]


@pytest.mark.parametrize(
    "config",
    [
        MeasurementConfig("ac_voltage"),
        MeasurementConfig(F.TEMPERATURE),
        MeasurementConfig(F.TEMPERATURE, temperature_probe="FRTD"),
        MeasurementConfig(F.TEMPERATURE, temperature_probe=TemperatureProbe.RTD_2W,
                          range_spec="AUTO"),
        MeasurementConfig(F.VOLTAGE_DC if hasattr(F, "VOLTAGE_DC") else F.DC_VOLTAGE,
                          temperature_probe=TemperatureProbe.RTD_2W),
        MeasurementConfig(F.CONTINUITY, range_spec="AUTO"),
        MeasurementConfig(F.DIODE, resolution="MIN"),
        MeasurementConfig(F.FREQUENCY, range_spec="AUTO"),
        MeasurementConfig(F.PERIOD, range_spec="AUTO"),
        MeasurementConfig(F.AC_CURRENT, range_spec="any"),
        MeasurementConfig(F.AC_CURRENT, range_spec="AUTO\n*RST"),
        MeasurementConfig(F.AC_VOLTAGE, range_spec=3.5),
        MeasurementConfig(F.DC_VOLTAGE, resolution="MIN"),
        MeasurementConfig(F.DC_VOLTAGE, range_spec="AUTO", resolution=0.1),
    ],
)
def test_invalid_config_fails_before_any_configuration_write(config):
    tr = dmm_transport()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.measurement.configure(config)
        with pytest.raises(ConfigurationError):
            dmm.measurement.measure(config)
    assert tr.history == ["*IDN?"]


def test_symbolic_range_resolution_and_frequency_range():
    tr = dmm_transport().on("MEASure:VOLTage:AC? AUTO,MIN", "2.4")
    with DMM_34411A(transport=tr) as dmm:
        c = MeasurementConfig(F.AC_VOLTAGE, range_spec="AUTO", resolution="MIN")
        assert dmm.measurement.measure(c).value == 2.4
        dmm.measurement.configure(MeasurementConfig(F.FREQUENCY, range_spec="DEF"))
    assert tr.history == ["*IDN?", "MEASure:VOLTage:AC? AUTO,MIN", "CONFigure:FREQuency DEF"]


@pytest.mark.parametrize(("value", "over"), [
    ("9.90000000E+37", True), ("-9.90000000E+37", True), ("0.0", False)
])
def test_overload_is_not_exposed_as_valid_numeric_reading(value, over):
    tr = dmm_transport().on("MEASure:CAPacitance?", value)
    with DMM_34411A(transport=tr) as dmm:
        result = dmm.measurement.measure(MeasurementConfig(F.CAPACITANCE))
    assert result.is_overrange is over
    assert result.value is None if over else result.value == 0


@pytest.mark.parametrize("raw", ["NaN", "Inf", "not-a-reading", "", "1,2"])
def test_malformed_one_shot_reply_is_rejected_without_retry(raw):
    tr = dmm_transport().on("MEASure:PERiod?", raw)
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ValueError):
            dmm.measurement.measure(MeasurementConfig(F.PERIOD))
    assert tr.history.count("MEASure:PERiod?") == 1


def test_raw_driver_scpi_invalidates_cached_measurement_mode():
    tr = dmm_transport().on("CONFigure:VOLTage:AC")
    with DMM_34411A(transport=tr) as dmm:
        dmm.measurement.configure(MeasurementConfig(F.FREQUENCY))
        dmm.cmd_write("CONFigure:VOLTage:AC")
        with pytest.raises(RuntimeError):
            dmm.measurement.read()
    assert tr.history == ["*IDN?", "CONFigure:FREQuency", "CONFigure:VOLTage:AC"]


def test_close_reopen_invalidates_cached_state():
    tr = dmm_transport()
    dmm = DMM_34411A(transport=tr)
    dmm.measurement.configure(MeasurementConfig(F.AC_VOLTAGE))
    dmm.close()
    dmm.open()
    with pytest.raises(RuntimeError):
        dmm.measurement.read()
    dmm.close()


def test_readback_queries_do_not_reset_instrument_or_clear_errors():
    tr = dmm_transport().on("CONFigure?", '"VOLT:DC AUTO"')
    with DMM_34411A(transport=tr) as dmm:
        assert dmm.measurement.get_configuration_raw() == '"VOLT:DC AUTO"'
        assert "34411A" in dmm.measurement.get_identity()
    assert tr.history == ["*IDN?", "CONFigure?", "*IDN?"]


def test_temperature_unit_unknown_is_not_mislabeled():
    tr = dmm_transport().on("UNIT:TEMPerature?", "UNKNOWN")
    with DMM_34411A(transport=tr) as dmm:
        config = MeasurementConfig(F.TEMPERATURE,
                                   temperature_probe=TemperatureProbe.RTD_4W)
        with pytest.raises(ValueError):
            dmm.measurement.measure(config)
    assert "MEASure:TEMPerature?" not in tr.history


def test_one_shot_timeout_not_retried():
    tr = dmm_transport().on("MEASure:VOLTage:AC?", ScriptedReply(
        raises=TransportTimeoutError("offline timeout"), disconnect=True
    ))
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(TransportTimeoutError):
            dmm.measurement.measure(MeasurementConfig(F.AC_VOLTAGE))
    assert tr.history.count("MEASure:VOLTage:AC?") == 1
