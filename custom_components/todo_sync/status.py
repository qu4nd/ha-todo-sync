"""Synchronization status model and backwards-compatible serialization."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class SyncState(str, Enum):
    """Stable public states exposed by the synchronization status sensor."""

    IDLE = "idle"
    SYNCING = "syncing"
    WAITING = "waiting"
    HELD_BACK = "held_back"
    SUCCESS = "success"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SyncStatus:
    """Runtime and persisted status for one synchronization pair.

    State transitions are driven by the sync workflow. Status data is derived from
    existing run results and local Home Assistant entity states; this model never
    performs provider reads or service calls.
    """

    state: SyncState = SyncState.IDLE
    last_success: str | None = None
    last_error: str | None = None
    synced_items: int = 0
    last_error_type: str | None = None
    waiting_entity: str | None = None
    waiting_state: str | None = None

    @classmethod
    def from_dict(cls, data: object) -> SyncStatus:
        """Restore the current or legacy dictionary-based storage representation."""
        if not isinstance(data, dict):
            return cls()

        try:
            state = SyncState(data.get("state", SyncState.IDLE))
        except (TypeError, ValueError):
            state = SyncState.IDLE

        synced_items = data.get("synced_items", 0)
        if (
            not isinstance(synced_items, int)
            or isinstance(synced_items, bool)
            or synced_items < 0
        ):
            synced_items = 0

        def optional_string(key: str) -> str | None:
            """Ignore malformed optional text fields in persisted status data."""
            value = data.get(key)
            return value if isinstance(value, str) else None

        return cls(
            state=state,
            last_success=optional_string("last_success"),
            last_error=optional_string("last_error"),
            synced_items=synced_items,
            last_error_type=optional_string("last_error_type"),
            waiting_entity=optional_string("waiting_entity"),
            waiting_state=optional_string("waiting_state"),
        )

    def to_dict(self) -> dict:
        """Return the backwards-compatible JSON storage and sensor representation."""
        return {
            "state": self.state.value,
            "last_success": self.last_success,
            "last_error": self.last_error,
            "synced_items": self.synced_items,
            "last_error_type": self.last_error_type,
            "waiting_entity": self.waiting_entity,
            "waiting_state": self.waiting_state,
        }

    @property
    def attributes(self) -> dict:
        """Return sensor attributes without the state already exposed as its value."""
        data = self.to_dict()
        data.pop("state")
        return data

    def updated(self, state: SyncState | str, **attributes) -> SyncStatus:
        """Create a new status snapshot while validating the state and field names."""
        return replace(self, state=SyncState(state), **attributes)
