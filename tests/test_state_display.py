"""P2-08: persistent instrument-state and display control, offline-only."""

import pytest

from dmm34411a import DMM_34411A
from dmm34411a.storage import StoredState
from scpi_driver_core import ConfigurationError
from scpi_driver_core.simulation import ScriptedScpiTransport


def fake():
    return ScriptedScpiTransport(unknown_command_error=None).on(
        "*IDN?", "Agilent Technologies,34411A,SIM,1.0"
    )


def stateful(valid=False, name="STATE_1"):
    state = {"valid": valid, "name": name}
    tr = (fake()
          .on("MEMory:STATe:VALid? 1", lambda _: "1" if state["valid"] else "0")
          .on("MEMory:STATe:NAME? 1", lambda _: state["name"])
          .on("*SAV 1", lambda _: state.update(valid=True))
          .on("MEMory:STATe:DELete 1", lambda _: state.update(valid=False, name="STATE_1"))
          .on("MEMory:STATe:NAME 1,CAL_STD",
              lambda _: state.update(name="CAL_STD")))
    return tr, state


def test_state_zero_reserved_no_mutating_commands():
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        for op in (
            lambda: dmm.storage.save_state(0),
            lambda: dmm.storage.recall_state(0, confirm=True),
            lambda: dmm.storage.delete_state(0, confirm=True),
            lambda: dmm.storage.rename_state(0, "SAFE"),
        ):
            with pytest.raises(ConfigurationError):
                op()
    assert tr.history == ["*IDN?"]


def test_empty_state_can_be_saved_and_verified_without_reset():
    tr, state = stateful()
    with DMM_34411A(transport=tr) as dmm:
        dmm.storage.save_state(1)
        assert dmm.storage.get_state(1) == StoredState(1, True, "STATE_1")
    assert state["valid"] is True
    assert tr.history == [
        "*IDN?", "MEMory:STATe:VALid? 1", "*SAV 1",
        "MEMory:STATe:VALid? 1", "MEMory:STATe:VALid? 1",
        "MEMory:STATe:NAME? 1"
    ]


def test_existing_state_needs_overwrite_and_confirmation():
    tr, state = stateful(valid=True)
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(FileExistsError):
            dmm.storage.save_state(1)
        with pytest.raises(FileExistsError):
            dmm.storage.save_state(1, overwrite=True)
        with pytest.raises(FileExistsError):
            dmm.storage.save_state(1, confirm=True)
        dmm.storage.save_state(1, overwrite=True, confirm=True)
    assert tr.history.count("*SAV 1") == 1
    assert state["valid"] is True


def test_recall_requires_confirm_and_invalidates_typed_measurement_cache():
    tr, _ = stateful(valid=True)
    with DMM_34411A(transport=tr) as dmm:
        dmm.configure_dc_voltage()
        with pytest.raises(PermissionError):
            dmm.storage.recall_state(1)
        dmm.storage.recall_state(1, confirm=True)
        with pytest.raises(RuntimeError):
            dmm.measurement.read()
    assert "*RCL 1" in tr.history
    assert tr.history.count("*RCL 1") == 1


def test_recall_empty_slot_has_no_effect():
    tr, _ = stateful(valid=False)
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(FileNotFoundError):
            dmm.storage.recall_state(1, confirm=True)
    assert "*RCL 1" not in tr.history


def test_delete_requires_explicit_confirmation_and_verifies_invalid():
    tr, state = stateful(valid=True)
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(PermissionError):
            dmm.storage.delete_state(1)
        dmm.storage.delete_state(1, confirm=True)
        assert dmm.storage.get_state(1) == StoredState(1, False)
    assert state["valid"] is False
    assert tr.history.count("MEMory:STATe:DELete 1") == 1


def test_rename_restricted_ascii_and_readback_verified():
    tr, state = stateful(valid=True)
    with DMM_34411A(transport=tr) as dmm:
        dmm.storage.rename_state(1, "CAL_STD")
        assert dmm.storage.slot_name(1) == "CAL_STD"
    assert state["name"] == "CAL_STD"


@pytest.mark.parametrize("name", [
    "", "12 CHAR NAME", "1START", "aLower", "HAS-DASH", "HAS SPACE",
    "BAD;*RST", 'BAD"NAME', "BAD\n*RST", "0123456789ABC",
])
def test_rename_invalid_before_instrument_commands(name):
    tr, _ = stateful(valid=True)
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.storage.rename_state(1, name)
    assert tr.history == ["*IDN?"]


def test_state_listing_safe_queries_only():
    tr = fake()
    for slot in range(1, 5):
        tr.on(f"MEMory:STATe:VALid? {slot}", "1" if slot == 2 else "0")
    tr.on("MEMory:STATe:NAME? 2", "STATE_2")
    tr.on("MEMory:STATe:CATalog?", '"STATE_2"')
    with DMM_34411A(transport=tr) as dmm:
        items = dmm.storage.list_states()
        assert len(items) == 4
        assert items[1] == StoredState(2, True, "STATE_2")
        assert dmm.storage.catalog_raw() == '"STATE_2"'
    assert all(not x.startswith(("*SAV", "*RCL", "MEMory:STATe:DELete ")) for x in tr.history)


def test_power_on_recall_opt_in_and_readback():
    tr = (fake()
          .on("MEMory:STATe:VALid? 2", "1")
          .on("MEMory:STATe:RECall:AUTO?", "1")
          .on("MEMory:STATe:RECall:SELect?", "2"))
    with DMM_34411A(transport=tr) as dmm:
        assert dmm.storage.get_power_on_state() == (True, 2)
        with pytest.raises(PermissionError):
            dmm.storage.set_power_on_recall(True, 2)
        dmm.storage.set_power_on_recall(True, 2, confirm=True)
        dmm.storage.set_power_on_recall(False, confirm=True)
    assert tr.history[-3:] == [
        "MEMory:STATe:RECall:SELect 2",
        "MEMory:STATe:RECall:AUTO ON",
        "MEMory:STATe:RECall:AUTO OFF"
    ]


@pytest.mark.parametrize("slot", [True, -1, 0, 5, 1.0, "1"])
def test_bad_mutating_slot_validation_without_io(slot):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.storage.save_state(slot)
    assert tr.history == ["*IDN?"]


@pytest.mark.parametrize("window", [0, 3, 1.0, True, "2"])
def test_display_invalid_window_without_scpi(window):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.display.get_enabled(window)
        with pytest.raises(ConfigurationError):
            dmm.display.set_text(window, "OK")
    assert tr.history == ["*IDN?"]


def test_display_primary_secondary_text_and_enable_roundtrip():
    tr = (fake()
          .on("DISPlay:WINDow1:STATe?", "1")
          .on("DISPlay:WINDow2:TEXT?", '"TEST READY"')
          .on("DISPlay:WINDow2:TEXT:FEED?", '"SAMPLE"'))
    with DMM_34411A(transport=tr) as dmm:
        dmm.display.set_text(2, "TEST READY")
        assert dmm.display.get_text(2) == "TEST READY"
        dmm.display.set_enabled(1, True)
        assert dmm.display.get_enabled(1) is True
        assert dmm.display.get_secondary_feed() == "SAMPLE"
        dmm.display.clear_text(2)
    assert tr.history == [
        "*IDN?", 'DISPlay:WINDow2:TEXT "TEST READY"',
        "DISPlay:WINDow2:TEXT?", "DISPlay:WINDow1:STATe ON",
        "DISPlay:WINDow1:STATe?", "DISPlay:WINDow2:TEXT:FEED?",
        "DISPlay:WINDow2:TEXT:CLEar"
    ]


@pytest.mark.parametrize("message", ["", "x"*13, 'evil"*RST', "x\n*CLS", "ą", 3, None])
def test_display_text_rejects_invalid_and_injection(message):
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        with pytest.raises(ConfigurationError):
            dmm.display.set_text(1, message)
    assert tr.history == ["*IDN?"]


def test_beep_and_beeper_setting_are_explicit():
    tr = fake().on("SYSTem:BEEPer:STATe?", "0")
    with DMM_34411A(transport=tr) as dmm:
        dmm.display.beep()
        dmm.display.set_beeper_enabled(False)
        assert dmm.display.get_beeper_enabled() is False
    assert tr.history == [
        "*IDN?", "SYSTem:BEEPer:IMMediate",
        "SYSTem:BEEPer:STATe OFF",
        "SYSTem:BEEPer:STATe?"
    ]


def test_open_and_close_do_not_modify_states_or_display():
    tr = fake()
    with DMM_34411A(transport=tr) as dmm:
        assert dmm.storage is not None and dmm.display is not None
    assert tr.history == ["*IDN?"]
