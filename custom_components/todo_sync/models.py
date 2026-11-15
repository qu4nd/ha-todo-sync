"""Explicit data models for normalized to-do item identity and provider data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import NotRequired, TypedDict


def _normalize(value: str) -> str:
    """Normalize text consistently before comparing item identity."""
    return value.strip().casefold()


@dataclass(frozen=True, slots=True)
class ItemKey:
    """Stable cross-provider identity; provider-local UIDs are deliberately excluded."""

    name: str
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize(self.name))
        object.__setattr__(self, "description", _normalize(self.description))

    @property
    def storage_key(self) -> str:
        """Keep the existing JSON key format for persisted snapshots and pending writes."""
        return json.dumps(
            [self.name, self.description], ensure_ascii=False, separators=(",", ":")
        )

    @classmethod
    def from_storage_key(cls, value: str) -> ItemKey:
        """Restore an identity from the stable key format used by the storage layer."""
        parts = json.loads(value)
        if (
            not isinstance(parts, list)
            or len(parts) != 2
            or not all(isinstance(part, str) for part in parts)
        ):
            raise ValueError("Invalid stored to-do item identity")
        return cls(parts[0], parts[1])


class TodoItem(TypedDict):
    """Parsed provider item; title and UID retain provider-specific addressing details."""

    title: str
    name: str
    status: str
    description: str
    uid: NotRequired[str]
