"""Pure retry and empty-list confirmation policies for synchronization."""

from __future__ import annotations

from dataclasses import dataclass

RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 300
# Longer than the slowest source poll (Alexa: 300 s).
CONFIRM_SECONDS = 360


def calculate_retry_delay(attempt: int, base_delay: int, max_delay: int) -> int:
    """Return the bounded exponential delay for a one-based retry attempt."""
    if attempt < 1:
        raise ValueError("Retry attempts must be one-based and positive")
    return min(base_delay * 2 ** (attempt - 1), max_delay)


def select_retry_trigger(
    pending_trigger: str | None, current_trigger: str | None
) -> str | None:
    """Prefer a newer pending change while retaining the failed run's trigger."""
    return pending_trigger or current_trigger


@dataclass(slots=True)
class EmptyListGuard:
    """Track whether an empty-list result has remained stable long enough."""

    suspect: tuple[frozenset[str], float] | None = None

    def evaluate(
        self,
        suspects: frozenset[str],
        now: float,
        confirmation_seconds: int,
    ) -> tuple[bool, float]:
        """Return whether to hold back and how much confirmation time remains."""
        if not suspects:
            self.suspect = None
            return False, 0.0

        if self.suspect is None or self.suspect[0] != suspects:
            self.suspect = (suspects, now)

        remaining = confirmation_seconds - (now - self.suspect[1])
        return remaining > 0, max(0.0, remaining)
