"""34411A primary/secondary display controls (not measurement commands)."""

from __future__ import annotations

from scpi_driver_core import ConfigurationError


def _window(number: int) -> str:
    if type(number) is not int or number not in (1, 2):
        raise ConfigurationError("display window must be integer 1 or 2")
    return f"DISPlay:WINDow{number}"


class DisplayController:
    """Explicit display text/state actions; no automatic front-panel changes."""

    def __init__(self, meter: object) -> None:
        self._meter = meter

    @property
    def _client(self):
        return self._meter.client

    def set_enabled(self, window: int, enabled: bool) -> None:
        prefix = _window(window)
        if type(enabled) is not bool:
            raise ConfigurationError("enabled must be bool")
        self._client.write(f"{prefix}:STATe {'ON' if enabled else 'OFF'}")

    def get_enabled(self, window: int) -> bool:
        prefix = _window(window)
        raw = self._client.query(f"{prefix}:STATe?").strip().upper()
        if raw not in ("0", "1", "ON", "OFF"):
            raise ValueError(f"unrecognized display state: {raw!r}")
        return raw in ("1", "ON")

    def set_text(self, window: int, message: str) -> None:
        prefix = _window(window)
        # Restrict SCPI quoting and characters: portable ASCII display subset,
        # deliberately conservative max length, not hardware capacity claim.
        if (not isinstance(message, str) or len(message) < 1 or len(message) > 12 or
                any(not (c.isascii() and (c.isalnum() or c in " _-."))
                    for c in message)):
            raise ConfigurationError("display text must be 1–12 ASCII letters, digits, spaces, _-.")
        self._client.write(f'{prefix}:TEXT "{message}"')

    def get_text(self, window: int) -> str:
        return self._client.query(f"{_window(window)}:TEXT?").strip().strip('"')

    def clear_text(self, window: int) -> None:
        self._client.write(f"{_window(window)}:TEXT:CLEar")

    def get_secondary_feed(self) -> str:
        """Read feed without assuming firmware-specific feed enumeration."""
        return self._client.query("DISPlay:WINDow2:TEXT:FEED?").strip().strip('"')

    def beep(self) -> None:
        """Explicit front-panel beep; never called on construction/open."""
        self._client.write("SYSTem:BEEPer:IMMediate")

    def get_beeper_enabled(self) -> bool:
        raw = self._client.query("SYSTem:BEEPer:STATe?").strip().upper()
        if raw not in ("0", "1", "ON", "OFF"):
            raise ValueError(f"invalid beeper state {raw!r}")
        return raw in ("1", "ON")

    def set_beeper_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ConfigurationError("enabled must be bool")
        self._client.write(f"SYSTem:BEEPer:STATe {'ON' if enabled else 'OFF'}")
