"""Tests for normalized to-do item identity and storage compatibility."""

from custom_components.todo_sync.models import ItemKey


def test_item_key_normalizes_name_and_description():
    assert ItemKey("  MILK  ", "  3 ") == ItemKey("milk", "3")


def test_item_key_keeps_different_descriptions_independent():
    assert ItemKey("Pizza", "4 Käse") != ItemKey("Pizza", "4 Stagioni")


def test_item_key_storage_format_is_backward_compatible():
    key = ItemKey(" Milk ", " 3 ")

    assert key.storage_key == '["milk","3"]'
    assert ItemKey.from_storage_key(key.storage_key) == key


def test_item_key_storage_format_handles_json_special_characters():
    key = ItemKey('Milk "oat"', "1,5 l \\ carton")

    assert ItemKey.from_storage_key(key.storage_key) == key
