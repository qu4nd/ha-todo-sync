"""Tests for Home Assistant entity metadata and public state contracts."""

import json
from pathlib import Path
from unittest.mock import Mock

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.todo_sync.button import SyncNowButton
from custom_components.todo_sync.const import CONF_LIST_A, CONF_LIST_B, DOMAIN
from custom_components.todo_sync.sensor import SyncStatusSensor
from custom_components.todo_sync.status import SyncState


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="To-do Sync",
        data={CONF_LIST_A: "todo.a", CONF_LIST_B: "todo.b"},
    )


def test_status_sensor_declares_enum_contract_and_diagnostic_category():
    syncer = Mock(status="idle", status_attributes={})

    sensor = SyncStatusSensor(_entry(), syncer)

    assert sensor.device_class is SensorDeviceClass.ENUM
    assert sensor.options == [state.value for state in SyncState]
    assert sensor.native_value == "idle"
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.should_poll is False


def test_sensor_and_button_share_stable_service_device_metadata():
    entry = _entry()
    syncer = Mock(status="idle", status_attributes={})

    sensor = SyncStatusSensor(entry, syncer)
    button = SyncNowButton(entry, syncer)

    assert sensor.unique_id == f"{entry.entry_id}_sync_status"
    assert button.unique_id == f"{entry.entry_id}_sync_now"
    assert sensor.device_info == button.device_info
    assert sensor.device_info["identifiers"] == {(DOMAIN, entry.entry_id)}
    assert sensor.device_info["name"] == entry.title
    assert sensor.device_info["entry_type"] is DeviceEntryType.SERVICE


def test_translations_cover_every_enum_state_in_both_languages():
    translation_dir = (
        Path(__file__).parents[1]
        / "custom_components"
        / DOMAIN
        / "translations"
    )
    expected_states = {state.value for state in SyncState}

    for language in ("en", "de"):
        translations = json.loads(
            (translation_dir / f"{language}.json").read_text(encoding="utf-8")
        )
        translated_states = set(
            translations["entity"]["sensor"]["sync_status"]["state"]
        )
        assert translated_states == expected_states
