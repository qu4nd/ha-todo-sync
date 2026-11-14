"""Tests for retry and empty-list confirmation policies."""

import pytest

from custom_components.todo_sync.policy import (
    EmptyListGuard,
    calculate_retry_delay,
    select_retry_trigger,
)


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(1, 30), (2, 60), (3, 120), (4, 240), (5, 300), (10, 300)],
)
def test_retry_delay_uses_bounded_exponential_backoff(attempt, expected):
    assert calculate_retry_delay(attempt, 30, 300) == expected


@pytest.mark.parametrize("attempt", [0, -1])
def test_retry_delay_rejects_non_positive_attempt(attempt):
    with pytest.raises(ValueError, match="one-based"):
        calculate_retry_delay(attempt, 30, 300)


@pytest.mark.parametrize(
    ("pending", "current", "expected"),
    [
        ("todo.b", "todo.a", "todo.b"),
        (None, "todo.a", "todo.a"),
        (None, None, None),
    ],
)
def test_retry_trigger_prefers_newer_pending_change(pending, current, expected):
    assert select_retry_trigger(pending, current) == expected


def test_empty_list_guard_requires_full_confirmation_window():
    guard = EmptyListGuard()
    suspects = frozenset({"todo.a"})

    assert guard.evaluate(suspects, 100.0, 360) == (True, 360.0)
    assert guard.evaluate(suspects, 459.0, 360) == (True, 1.0)
    assert guard.evaluate(suspects, 460.0, 360) == (False, 0.0)


def test_empty_list_guard_restarts_when_suspects_change():
    guard = EmptyListGuard()
    first = frozenset({"todo.a"})
    second = frozenset({"todo.a", "todo.b"})

    assert guard.evaluate(first, 100.0, 360)[0] is True
    assert guard.evaluate(second, 200.0, 360)[0] is True

    assert guard.suspect == (second, 200.0)


def test_empty_list_guard_resets_when_no_suspects_remain():
    guard = EmptyListGuard()
    suspects = frozenset({"todo.a"})

    guard.evaluate(suspects, 100.0, 360)
    assert guard.evaluate(frozenset(), 200.0, 360) == (False, 0.0)

    assert guard.suspect is None
