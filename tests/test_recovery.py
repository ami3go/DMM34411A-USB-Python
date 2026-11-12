"""P0 uncertain-state quarantine, safe reconnect and operator reconciliation.

All scenarios use a scripted transport; not a real meter or hardware HIL.
"""

from __future__ import annotations

import pytest

from dmm34411a import (
    AcquisitionState, DMM_34411A, RecoveryRequiredError, RecoverySnapshot,
)
from scpi_driver_core import TransportTimeoutError
from scpi_driver_core.simulation import ScriptedReply, ScriptedScpiTransport


def sim(*, count=3, nvm=0, idn="Agilent,34411A,TEST,A.03.00"):
    state = {"count": count, "nvm": nvm, "idn": idn}
    tr = ScriptedScpiTransport(unknown_command_error=None)
    tr.on("*IDN?", lambda _: state["idn"])
    tr.on("*STB?", "0")
    tr.on("*OPC?", "1")
    tr.on("DATA:POINts? RDG_STORE", lambda _: str(state["count"]))
    tr.on("DATA:POINts? NVMEM", lambda _: str(state["nvm"]))
    return tr, state


def _make_uncertain_meter(tr):
    meter = DMM_34411A(transport=tr)
    meter.configure_volatile_acquisition(4, trigger_source="EXTERNAL")
    meter.start_acquisition()
    with pytest.raises(TimeoutError):
        meter.acquisition.wait_complete(
            timeout_s=0.005, poll_interval_s=0.001
        )
    assert meter.recovery.pending
    assert meter.acquisition.state is AcquisitionState.UNKNOWN
    return meter


def test_timeout_quarantine_survives_successful_abort_and_reopen():
    tr, _ = sim(count=0)
    meter = _make_uncertain_meter(tr)
    meter.abort_acquisition()
    assert meter.acquisition.state is AcquisitionState.ABORTED
    with pytest.raises(RecoveryRequiredError):
        meter.configure_volatile_acquisition(2)
    meter.close()
    assert meter.recovery.pending
    meter.open()
    with pytest.raises(RecoveryRequiredError):
        meter.configure_volatile_acquisition(2)
    snap = meter.inspect_recovery()
    assert isinstance(snap, RecoverySnapshot)
    assert snap.volatile_points == 0
    assert snap.nvm_points == 0
    assert snap.quarantined
    assert snap.idn_raw.endswith("A.03.00")
    with pytest.raises(PermissionError):
        meter.acknowledge_recovery(
            snap, operator="QA", confirm_idle=True
        )
    with pytest.raises(PermissionError):
        meter.acknowledge_recovery(
            snap, operator="QA", confirm_data_review=True
        )
    result = meter.acknowledge_recovery(
        snap, operator="QA", confirm_idle=True, confirm_data_review=True
    )
    assert result.operator == "QA"
    assert meter.recovery.pending is False
    assert meter.acquisition.state is AcquisitionState.IDLE
    assert meter.configure_volatile_acquisition(2) == 2
    meter.close()
    assert "*RST" not in tr.history and "*CLS" not in tr.history
    assert "DATA:DELete NVMEM" not in tr.history


def test_failed_initiate_never_replayed_during_recovery():
    tr, _ = sim(count=0)
    tr.on("INITiate", ScriptedReply(
        raises=TransportTimeoutError("late INIT reply"), disconnect=True
    ))
    meter = DMM_34411A(transport=tr)
    meter.configure_volatile_acquisition(4)
    with pytest.raises(TransportTimeoutError):
        meter.start_acquisition()
    assert meter.recovery.pending
    assert tr.history.count("INITiate") == 1
    snapshot = meter.inspect_recovery()  # faulted transport explicitly reopened; *IDN? only
    assert snapshot.quarantined
    assert snapshot.idn_raw.startswith("Agilent,34411A")
    assert tr.history.count("INITiate") == 1
    assert not any(x in tr.history for x in ("ABORt", "*RST", "*CLS"))
    meter.close()


def test_recovery_inspection_uses_non_consuming_queries_only():
    tr, _ = sim(count=8, nvm=6)
    meter = DMM_34411A(transport=tr)
    meter.recovery.mark_uncertain("test-only uncertain NVM")
    snap = meter.inspect_recovery()
    assert snap.volatile_points == 8 and snap.nvm_points == 6
    assert tr.history == [
        "*IDN?", "*IDN?", "*STB?",
        "DATA:POINts? RDG_STORE", "DATA:POINts? NVMEM"
    ]
    meter.close()
    assert "SYSTem:ERRor?" not in tr.history
    assert "*ESR?" not in tr.history
    assert "DATA:COPY NVMEM, RDG_STORE" not in tr.history


def test_changed_nvm_count_refuses_stale_acknowledgement():
    tr, state = sim(count=3, nvm=2)
    with DMM_34411A(transport=tr) as meter:
        meter.recovery.mark_uncertain("NVM changed")
        snap = meter.inspect_recovery()
        state["nvm"] = 3
        with pytest.raises(RecoveryRequiredError, match="counts changed"):
            meter.acknowledge_recovery(
                snap, operator="QA", confirm_idle=True, confirm_data_review=True
            )
        assert meter.recovery.pending
        with pytest.raises(RecoveryRequiredError):
            meter.configure_data_log(3)
        fresh = meter.inspect_recovery()
        ack = meter.acknowledge_recovery(
            fresh, operator="QA", confirm_idle=True, confirm_data_review=True
        )
        assert ack.nvm_points == 3
        assert not meter.recovery.pending
    assert "DATA:DELete NVMEM" not in tr.history


def test_identity_mismatch_after_reconnect_never_releases_quarantine():
    tr, state = sim(count=0)
    meter = DMM_34411A(transport=tr)
    meter.recovery.mark_uncertain("lost transport")
    meter.close()
    state["idn"] = "Agilent,34411A,OTHER,A.03.00"
    meter.open()
    with pytest.raises(RecoveryRequiredError, match="identity"):
        meter.inspect_recovery()
    assert meter.recovery.pending
    with pytest.raises(RecoveryRequiredError):
        meter.configure_volatile_acquisition(2)
    meter.close()


def test_failed_nvm_copy_is_quarantined_and_not_replayed_after_reopen():
    tr, _ = sim(count=3, nvm=0)
    tr.on("DATA:COPY NVMEM, RDG_STORE", ScriptedReply(
        raises=TransportTimeoutError("COPY may have executed"), disconnect=True
    ))
    meter = DMM_34411A(transport=tr)
    meter.configure_data_log(3)
    meter.start_data_log()
    assert meter.acquisition.wait_complete(timeout_s=3) == 3
    with pytest.raises(TransportTimeoutError):
        meter.save_data_log()
    assert tr.history.count("DATA:COPY NVMEM, RDG_STORE") == 1
    assert meter.recovery.pending
    meter.close()
    meter.open()
    with pytest.raises(RecoveryRequiredError):
        meter.configure_data_log(3)
    with pytest.raises(RecoveryRequiredError):
        meter.delete_data_log(confirm=True)
    snap = meter.inspect_recovery()
    assert snap.nvm_points == 0  # count alone cannot prove no COPY occurred
    meter.acknowledge_recovery(
        snap, operator="QA", confirm_idle=True, confirm_data_review=True
    )
    assert tr.history.count("DATA:COPY NVMEM, RDG_STORE") == 1
    meter.close()


def test_delete_timeout_is_not_replayed_and_blocks_new_destructive_reads():
    tr, _ = sim(nvm=3)
    tr.on("DATA:DELete NVMEM", ScriptedReply(
        raises=TransportTimeoutError("DELETE outcome unknown"), disconnect=True
    ))
    meter = DMM_34411A(transport=tr)
    with pytest.raises(TransportTimeoutError):
        meter.delete_data_log(confirm=True)
    assert meter.recovery.pending
    assert tr.history.count("DATA:DELete NVMEM") == 1
    meter.close()
    meter.open()
    with pytest.raises(RecoveryRequiredError):
        meter.delete_data_log(confirm=True)
    assert tr.history.count("DATA:DELete NVMEM") == 1
    meter.close()


def test_explicit_operator_acknowledgement_rejects_invalid_identifiers():
    tr, _ = sim(count=0)
    with DMM_34411A(transport=tr) as meter:
        meter.recovery.mark_uncertain("needs operator")
        snap = meter.inspect_recovery()
        for invalid in ("", " ", 123, "x" * 201):
            with pytest.raises(ValueError):
                meter.acknowledge_recovery(
                    snap, operator=invalid, confirm_idle=True,
                    confirm_data_review=True
                )
        assert meter.recovery.pending


def test_read_only_snapshot_must_be_current_same_object_and_generation():
    tr, _ = sim(count=0)
    with DMM_34411A(transport=tr) as meter:
        meter.recovery.mark_uncertain("unknown")
        a = meter.inspect_recovery()
        b = meter.inspect_recovery()
        with pytest.raises(RecoveryRequiredError, match="stale"):
            meter.acknowledge_recovery(
                a, operator="QA", confirm_idle=True, confirm_data_review=True
            )
        assert b is not a
        meter.acknowledge_recovery(
            b, operator="QA", confirm_idle=True, confirm_data_review=True
        )
        with pytest.raises(RecoveryRequiredError):
            meter.acknowledge_recovery(
                b, operator="QA", confirm_idle=True, confirm_data_review=True
            )


def test_pending_recovery_blocks_typed_mode_and_state_writes():
    tr, _ = sim(count=0)
    with DMM_34411A(transport=tr) as meter:
        meter.recovery.mark_uncertain("possibly armed")
        before = list(tr.history)
        with pytest.raises(RecoveryRequiredError):
            meter.configure_dc_voltage()
        with pytest.raises(RecoveryRequiredError):
            meter.configure_data_log(3)
        with pytest.raises(RecoveryRequiredError):
            meter.storage.save_state(1)
        with pytest.raises(RecoveryRequiredError):
            meter.status.self_test(confirm=True)
        assert tr.history == before
