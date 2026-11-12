"""P0 guarded, read-only reconciliation after uncertain 34411A I/O.

A fault, ambiguous non-idempotent write, incomplete destructive transfer,
or interrupted capture must not be converted into a clean acquisition by
close/reopen. This quarantine persists in the driver object until an
operator explicitly inspects current buffers and acknowledges their state.

No recovery method issues *RST, *CLS, *ESR?, ABORt, DATA:COPY,
DATA:REMove?, DATA:DELete, VISA clear, or any automatic replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


class RecoveryRequiredError(RuntimeError):
    """An uncertain instrument state requires explicit operator review."""


@dataclass(frozen=True)
class RecoverySnapshot:
    observed_at_utc: datetime
    session_generation: int
    idn_raw: str
    status_byte: int
    volatile_points: int
    nvm_points: int
    quarantined: bool
    reason: str | None


@dataclass(frozen=True)
class RecoveryAcknowledgement:
    operator: str
    acknowledged_at_utc: datetime
    inspected_generation: int
    instrument_idn: str
    volatile_points: int
    nvm_points: int


class RecoveryController:
    """No-I/O uncertainty latch, read-only inspections and manual release."""

    def __init__(self, meter: object) -> None:
        self._meter = meter
        self._reason: str | None = None
        self._identity_at_failure: str | None = None
        self._last_snapshot: RecoverySnapshot | None = None
        self._last_acknowledgement: RecoveryAcknowledgement | None = None

    @property
    def pending(self) -> bool:
        return self._reason is not None

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def last_acknowledgement(self) -> RecoveryAcknowledgement | None:
        return self._last_acknowledgement

    def mark_uncertain(self, reason: str) -> None:
        """Latch uncertainty WITHOUT issuing any instrument command."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("uncertainty reason must be nonempty")
        if self._reason is None:
            self._reason = reason
            self._identity_at_failure = self._meter.idn
        self._last_snapshot = None

    def require_reconciled(self, purpose: str) -> None:
        if self._reason is not None:
            raise RecoveryRequiredError(
                f"{purpose} denied: unresolved instrument state "
                f"({self._reason}); inspect and explicitly acknowledge recovery"
            )

    def inspect(self) -> RecoverySnapshot:
        """Read-only evidence: identity, IEEE status byte and both counts.

        The sample is host-sequential, not instrument-atomic. It consumes
        neither IEEE event registers nor SCPI error queue entries.
        """
        with self._meter.session.operation_lock():
            if not self._meter.session.is_connected:
                raise RecoveryRequiredError(
                    "instrument disconnected; explicitly reopen before inspection"
                )
            identity = self._meter.client.query("*IDN?").strip()
            parts = [part.strip() for part in identity.split(",")]
            if len(parts) != 4 or parts[1].upper() != "34411A":
                raise RecoveryRequiredError(
                    f"recovery probe did not identify a 34411A: {identity!r}"
                )
            if self._identity_at_failure is not None and identity != self._identity_at_failure:
                raise RecoveryRequiredError(
                    "instrument identity/firmware differs from pre-fault record; "
                    "refusing to clear uncertainty"
                )
            status = self._meter.status.status_byte()
            volatile_count = self._meter.acquisition.volatile_count()
            nvm_count = self._meter.acquisition.nvm_count()
            snapshot = RecoverySnapshot(
                observed_at_utc=datetime.now(timezone.utc),
                session_generation=self._meter.session.generation,
                idn_raw=identity,
                status_byte=status,
                volatile_points=volatile_count,
                nvm_points=nvm_count,
                quarantined=self.pending,
                reason=self._reason,
            )
            self._last_snapshot = snapshot
            return snapshot

    def acknowledge(
        self, snapshot: RecoverySnapshot, *, operator: str,
        confirm_idle: bool = False, confirm_data_review: bool = False,
    ) -> RecoveryAcknowledgement:
        """Explicitly release a previously observed quarantine, without I/O writes.

        The operator attests the 34411A is not acquiring and that existing
        volatile/NVM contents have been reviewed/preserved. Both counts
        and the exact IDN are re-read under the lock before releasing.
        """
        if type(confirm_idle) is not bool or confirm_idle is not True:
            raise PermissionError("confirm_idle=True is required for recovery")
        if type(confirm_data_review) is not bool or confirm_data_review is not True:
            raise PermissionError("confirm_data_review=True is required for recovery")
        if not isinstance(operator, str) or not 1 <= len(operator.strip()) <= 200:
            raise ValueError("operator identifier (1..200 chars) is required")
        with self._meter.session.operation_lock():
            self.require_reconciled_snapshot(snapshot)
            if not self._meter.session.is_connected:
                raise RecoveryRequiredError("cannot acknowledge a disconnected instrument")
            if snapshot.session_generation != self._meter.session.generation:
                raise RecoveryRequiredError(
                    "session generation changed since inspection; re-inspect instrument"
                )
            observed_idn = self._meter.client.query("*IDN?").strip()
            if observed_idn != snapshot.idn_raw:
                raise RecoveryRequiredError("instrument identity changed since inspection")
            now_vol = self._meter.acquisition.volatile_count()
            now_nvm = self._meter.acquisition.nvm_count()
            if now_vol != snapshot.volatile_points or now_nvm != snapshot.nvm_points:
                self._last_snapshot = None
                raise RecoveryRequiredError(
                    "memory counts changed since inspection; re-inspect without writing"
                )
            ack = RecoveryAcknowledgement(
                operator=operator.strip(),
                acknowledged_at_utc=datetime.now(timezone.utc),
                inspected_generation=snapshot.session_generation,
                instrument_idn=observed_idn,
                volatile_points=now_vol, nvm_points=now_nvm,
            )
            # No SCPI write/abort/clear. Local run configuration is deliberately
            # discarded: the next acquisition must be configured explicitly.
            self._meter.acquisition.reset_on_close()
            self._meter.measurement.invalidate()
            self._last_acknowledgement = ack
            self._last_snapshot = None
            self._identity_at_failure = None
            self._reason = None
            return ack

    def require_reconciled_snapshot(self, snapshot: RecoverySnapshot) -> None:
        if self._reason is None:
            raise RecoveryRequiredError("there is no uncertain operation to acknowledge")
        if snapshot is not self._last_snapshot:
            raise RecoveryRequiredError(
                "recovery snapshot is stale or not from the current inspection"
            )
