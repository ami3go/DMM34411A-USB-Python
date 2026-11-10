"""Safe 34411A nonvolatile *instrument configuration* state slots.

These are separate from RDG_STORE/NVMEM reading memory. State 0 is reserved for
power-down configuration and is intentionally read-only. All writes and recalls
to slots 1-4 are explicit, confirmation-gated where destructive/disruptive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from scpi_driver_core import ConfigurationError


@dataclass(frozen=True)
class StoredState:
    slot: int
    valid: bool
    name: str | None = None


def _slot(slot: int, *, read_only: bool = False) -> int:
    if type(slot) is not int or not (0 if read_only else 1) <= slot <= 4:
        raise ConfigurationError("state slot must be 1–4 (or 0–4 for read-only queries)")
    return slot


def _bool(raw: str, name: str) -> bool:
    if raw.strip().upper() in ("1", "ON"):
        return True
    if raw.strip().upper() in ("0", "OFF"):
        return False
    raise ValueError(f"invalid {name}: {raw!r}")


class InstrumentStateController:
    """Nonvolatile instrument configuration slots, distinct from reading NVM."""

    def __init__(self, meter: object) -> None:
        self._meter = meter

    @property
    def _client(self):
        return self._meter.client

    def slot_valid(self, slot: int) -> bool:
        s = _slot(slot, read_only=True)
        return _bool(self._client.query(f"MEMory:STATe:VALid? {s}"), "state valid")

    def slot_name(self, slot: int) -> str:
        s = _slot(slot, read_only=True)
        return self._client.query(f"MEMory:STATe:NAME? {s}").strip().strip('"')

    def get_state(self, slot: int) -> StoredState:
        s = _slot(slot, read_only=True)
        with self._meter.session.operation_lock():
            valid = self.slot_valid(s)
            return StoredState(s, valid, self.slot_name(s) if valid else None)

    def list_states(self) -> tuple[StoredState, ...]:
        """Return the four user slots; reserved power-down slot 0 is excluded."""
        with self._meter.session.operation_lock():
            return tuple(self.get_state(i) for i in range(1, 5))

    def catalog_raw(self) -> str:
        """Return instrument catalog without guessing its firmware CSV layout."""
        return self._client.query("MEMory:STATe:CATalog?").strip()

    def save_state(self, slot: int, *, overwrite: bool = False,
                   confirm: bool = False) -> None:
        s = _slot(slot)
        if type(overwrite) is not bool or type(confirm) is not bool:
            raise ConfigurationError("overwrite and confirm must be bool")
        with self._meter.session.operation_lock():
            occupied = self.slot_valid(s)
            if occupied and not (overwrite and confirm):
                raise FileExistsError("state occupied; overwrite=True and confirm=True required")
            # *SAV changes nonvolatile instrument configuration storage.
            # Never automatically retry after ambiguous communication failure.
            self._client.write(f"*SAV {s}")
            if not self.slot_valid(s):
                raise RuntimeError("instrument did not confirm saved state")

    def recall_state(self, slot: int, *, confirm: bool = False) -> None:
        s = _slot(slot)
        if confirm is not True:
            raise PermissionError("state recall changes live configuration; confirm=True required")
        with self._meter.session.operation_lock():
            if not self.slot_valid(s):
                raise FileNotFoundError(f"state slot {s} does not contain a stored configuration")
            # Even on a timeout the instrument might have changed functions.
            self._meter.measurement.invalidate()
            self._meter.acquisition.reset_on_close()
            self._client.write(f"*RCL {s}")

    def delete_state(self, slot: int, *, confirm: bool = False) -> None:
        s = _slot(slot)
        if confirm is not True:
            raise PermissionError("deleting a stored state requires confirm=True")
        with self._meter.session.operation_lock():
            if not self.slot_valid(s):
                raise FileNotFoundError(f"state slot {s} is empty")
            self._client.write(f"MEMory:STATe:DELete {s}")
            if self.slot_valid(s):
                raise RuntimeError("instrument did not confirm state deletion")

    def rename_state(self, slot: int, name: str) -> None:
        s = _slot(slot)
        # Keep names conservative and injection-proof: A-Z initial character,
        # then A-Z, 0-9 or underscore, at most 12 characters.
        if not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,11}", name):
            raise ConfigurationError("state name: 1-12 uppercase A-Z/0-9/_; first A-Z")
        with self._meter.session.operation_lock():
            if not self.slot_valid(s):
                raise FileNotFoundError(f"state slot {s} is empty")
            self._client.write(f"MEMory:STATe:NAME {s},{name}")
            if self.slot_name(s) != name:
                raise RuntimeError("instrument did not confirm new state name")

    def get_power_on_state(self) -> tuple[bool, int]:
        with self._meter.session.operation_lock():
            active = _bool(self._client.query("MEMory:STATe:RECall:AUTO?"), "power-on recall")
            raw = self._client.query("MEMory:STATe:RECall:SELect?").strip()
            try:
                selected = int(raw)
            except ValueError as exc:
                raise ValueError(f"invalid power-on slot: {raw!r}") from exc
            _slot(selected, read_only=True)
            return active, selected

    def set_power_on_recall(
        self, enabled: bool, slot: int | None = None, *, confirm: bool = False,
    ) -> None:
        if type(enabled) is not bool:
            raise ConfigurationError("enabled must be bool")
        if confirm is not True:
            raise PermissionError("changing future power-on behavior requires confirm=True")
        if enabled:
            s = _slot(slot)
        elif slot is not None:
            raise ConfigurationError("slot must be omitted when disabling power-on recall")
        with self._meter.session.operation_lock():
            if enabled:
                if not self.slot_valid(s):
                    raise FileNotFoundError("selected power-on state does not exist")
                self._client.write(f"MEMory:STATe:RECall:SELect {s}")
            self._client.write(f"MEMory:STATe:RECall:AUTO {'ON' if enabled else 'OFF'}")
