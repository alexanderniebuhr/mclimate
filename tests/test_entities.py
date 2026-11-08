"""Test the Vicki sensors, binary sensors, switch and diagnostics."""

from datetime import UTC, datetime

from lorawan_connection import DeviceDescriptor, StatusEvent
from lorawan_connection.mock import MockConnection
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.mclimate_lorawan.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import entity_id_for, send_uplink

pytestmark = pytest.mark.usefixtures("setup_integration")


async def test_sensors(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A keep-alive updates every enabled sensor."""
    humidity = entity_id_for(hass, "sensor", descriptor, "humidity")
    assert hass.states.get(humidity).state == STATE_UNKNOWN

    await send_uplink(hass, mock_connection, descriptor)

    for key, value in (
        ("temperature", "22.53"),
        ("humidity", "46.88"),
        ("valve_openness", "17"),
        ("battery_voltage", "3.5"),
    ):
        entity_id = entity_id_for(hass, "sensor", descriptor, key)
        assert hass.states.get(entity_id).state == value


async def test_disabled_by_default(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    descriptor: DeviceDescriptor,
) -> None:
    """Rarely needed entities start disabled."""
    for platform, key in (
        ("sensor", "battery"),
        ("sensor", "motor_position"),
        ("sensor", "motor_range"),
        ("binary_sensor", "high_motor_consumption"),
        ("binary_sensor", "low_motor_consumption"),
    ):
        entry = entity_registry.async_get(
            entity_id_for(hass, platform, descriptor, key)
        )
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_binary_sensors(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Status flags are mapped to their entities."""
    await send_uplink(hass, mock_connection, descriptor, "81149c78fa2c01f8a2")

    assert hass.states.get("binary_sensor.living_room_open_window").state == STATE_ON
    assert hass.states.get("binary_sensor.living_room_battery_low").state == STATE_ON
    assert (
        hass.states.get("binary_sensor.living_room_attached_to_backplate").state
        == STATE_ON
    )
    assert hass.states.get("binary_sensor.living_room_anti_freeze").state == STATE_OFF


@pytest.mark.parametrize(
    ("action", "payload", "state"),
    [("turn_on", "0701", STATE_ON), ("turn_off", "0700", STATE_OFF)],
)
async def test_child_lock(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
    action: str,
    payload: str,
    state: str,
) -> None:
    """The switch queues the command and shows the requested state."""
    await hass.services.async_call(
        "switch",
        action,
        {ATTR_ENTITY_ID: "switch.living_room_child_lock"},
        blocking=True,
    )
    assert list(mock_connection.downlinks.values())[-1].data == bytes.fromhex(payload)
    assert hass.states.get("switch.living_room_child_lock").state == state


async def test_child_lock_settles_on_reported_value(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """The reported state wins after a matching keep-alive."""
    await send_uplink(hass, mock_connection, descriptor)
    assert hass.states.get("switch.living_room_child_lock").state == STATE_ON

    await hass.services.async_call(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: "switch.living_room_child_lock"},
        blocking=True,
    )
    await send_uplink(hass, mock_connection, descriptor, "81149c78fa2c01f020")
    assert hass.states.get("switch.living_room_child_lock").state == STATE_OFF

    await send_uplink(hass, mock_connection, descriptor)
    assert hass.states.get("switch.living_room_child_lock").state == STATE_ON


async def test_status_event_does_not_break_entities(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A LoRaWAN status report is handled by the device base class."""
    mock_connection.emit(
        StatusEvent(
            descriptor=descriptor,
            received_at=datetime.now(UTC),
            margin=7,
            battery_level_unavailable=False,
            battery_level=80,
        )
    )
    await hass.async_block_till_done()
    assert hass.states.get("climate.living_room").state == STATE_UNKNOWN


async def test_diagnostics(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Identifying details are redacted."""
    await send_uplink(hass, mock_connection, descriptor)

    result = await async_get_config_entry_diagnostics(hass, config_entry)

    [device] = result["devices"]
    assert device["descriptor"]["dev_eui"] == "**REDACTED**"
    assert device["descriptor"]["name"] == "**REDACTED**"
    assert device["keep_alive"]["humidity"] == 46.88
    assert device["target_temperature"] == 20
