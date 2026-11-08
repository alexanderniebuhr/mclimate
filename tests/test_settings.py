"""Test device settings, valve control and the room sensor."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from lorawan_connection import DeviceDescriptor
from lorawan_connection.mock import MockConnection
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.mclimate_lorawan.vicki import CommandRejected, Vicki
from homeassistant.components.climate import HVACMode
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError

from .conftest import KEEP_ALIVE, entity_id_for, send_uplink

pytestmark = pytest.mark.usefixtures(
    "entity_registry_enabled_by_default", "setup_integration"
)

CLIMATE = "climate.living_room"
ROOM_SENSOR = "sensor.room"


def last_data(connection: MockConnection) -> str:
    """Return the most recent downlink."""
    return list(connection.downlinks.values())[-1].data.hex()


def model(config_entry: MockConfigEntry) -> Vicki:
    """Return the device model."""
    return next(iter(config_entry.runtime_data.coordinators.values())).data


async def set_number(
    hass: HomeAssistant, descriptor: DeviceDescriptor, key: str, value: float
) -> None:
    """Call the set_value action of a number entity."""
    await hass.services.async_call(
        "number",
        "set_value",
        {
            ATTR_ENTITY_ID: entity_id_for(hass, "number", descriptor, key),
            "value": value,
        },
        blocking=True,
    )


async def select(
    hass: HomeAssistant, descriptor: DeviceDescriptor, key: str, option: str
) -> None:
    """Call the select_option action of a select entity."""
    await hass.services.async_call(
        "select",
        "select_option",
        {
            ATTR_ENTITY_ID: entity_id_for(hass, "select", descriptor, key),
            "option": option,
        },
        blocking=True,
    )


def link_room_sensor(
    hass: HomeAssistant, config_entry: MockConfigEntry, descriptor: DeviceDescriptor
) -> None:
    """Link a room temperature sensor to the device."""
    hass.config_entries.async_update_entry(
        config_entry, options={"room_sensors": {descriptor.dev_eui: ROOM_SENSOR}}
    )


async def test_settings_are_requested_once_firmware_is_known(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """The first batch follows the firmware report."""
    await send_uplink(hass, mock_connection, descriptor, f"042350{KEEP_ALIVE}")

    request = bytes.fromhex(last_data(mock_connection))
    assert request[0] == 0x12
    assert len(request) > 1


async def test_next_batch_follows_an_answer(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """An answer lets the next questions go out without waiting."""
    await send_uplink(hass, mock_connection, descriptor, f"042350{KEEP_ALIVE}")
    assert len(mock_connection.downlinks) == 1

    await send_uplink(hass, mock_connection, descriptor, f"1209{KEEP_ALIVE}")

    assert len(mock_connection.downlinks) == 2


async def test_no_requests_for_unsupported_firmware(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Older devices are left alone."""
    await send_uplink(hass, mock_connection, descriptor, f"042342{KEEP_ALIVE}")
    assert not mock_connection.downlinks

    await send_uplink(hass, mock_connection, descriptor, "011D5A78FA2C01F080")
    assert not mock_connection.downlinks


async def test_number_reads_back_what_the_device_applied(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A setting is written, read back, and corrected by the response."""
    entity_id = entity_id_for(hass, "number", descriptor, "keep_alive_period")
    await send_uplink(hass, mock_connection, descriptor, f"120a{KEEP_ALIVE}")
    assert float(hass.states.get(entity_id).state) == 10

    await set_number(hass, descriptor, "keep_alive_period", 15)

    assert last_data(mock_connection) == "020f12"
    assert float(hass.states.get(entity_id).state) == 15

    await send_uplink(hass, mock_connection, descriptor, f"120a{KEEP_ALIVE}")
    assert float(hass.states.get(entity_id).state) == 10


async def test_switch_writes_the_whole_group(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Changing one value keeps the others in its group."""
    entity_id = entity_id_for(hass, "switch", descriptor, "window_detection")
    await send_uplink(hass, mock_connection, descriptor, f"4601020f{KEEP_ALIVE}")
    assert hass.states.get(entity_id).state == STATE_ON

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )

    assert last_data(mock_connection) == "4500020f46"
    assert hass.states.get(entity_id).state == STATE_OFF

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert last_data(mock_connection) == "4501020f46"


async def test_group_must_be_loaded_first(
    hass: HomeAssistant, descriptor: DeviceDescriptor
) -> None:
    """Do not overwrite values the device has not reported."""
    with pytest.raises(ServiceValidationError) as err:
        await set_number(hass, descriptor, "target_temperature_min", 16)
    assert err.value.translation_key == "setting_not_loaded"


async def test_invalid_combination_is_refused(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Refuse values the device would silently ignore."""
    await send_uplink(hass, mock_connection, descriptor, f"15051e{KEEP_ALIVE}")
    count = len(mock_connection.downlinks)

    with pytest.raises(ServiceValidationError) as err:
        await set_number(hass, descriptor, "target_temperature_min", 30)

    assert err.value.translation_key == "invalid_target_limits"
    assert len(mock_connection.downlinks) == count


async def test_operating_mode(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """The operating mode is written and read back."""
    await select(hass, descriptor, "operating_mode", "manual")
    assert last_data(mock_connection) == "0d0018"


async def test_external_mode_needs_a_sensor(
    hass: HomeAssistant, descriptor: DeviceDescriptor
) -> None:
    """Without a reading the external sensor mode would not work."""
    with pytest.raises(ServiceValidationError) as err:
        await select(hass, descriptor, "operating_mode", "automatic_external")
    assert err.value.translation_key == "room_sensor_required"


async def test_valve_control_in_manual_mode(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """The valve is only offered while the device follows it."""
    entity_id = entity_id_for(hass, "number", descriptor, "valve_position")
    await send_uplink(hass, mock_connection, descriptor, f"1801{KEEP_ALIVE}")
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    await send_uplink(hass, mock_connection, descriptor, f"1800{KEEP_ALIVE}")
    assert float(hass.states.get(entity_id).state) == 17
    assert hass.states.get(CLIMATE).state == HVACMode.HEAT

    await set_number(hass, descriptor, "valve_position", 50)

    assert last_data(mock_connection) == "4e32"
    assert float(hass.states.get(entity_id).state) == 50


async def test_valve_needs_manual_mode(
    config_entry: MockConfigEntry,
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """The algorithm would immediately override a valve position."""
    await send_uplink(hass, mock_connection, descriptor, f"1801{KEEP_ALIVE}")
    with pytest.raises(CommandRejected, match="requires_manual_mode"):
        await model(config_entry).async_set_valve_openness(50)


async def test_small_valve_movement_is_refused(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Movements below 17 motor steps make the device misbehave."""
    await send_uplink(hass, mock_connection, descriptor, f"1800{KEEP_ALIVE}")
    with pytest.raises(ServiceValidationError) as err:
        await set_number(hass, descriptor, "valve_position", 18)
    assert err.value.translation_key == "valve_change_too_small"


async def test_target_is_refused_in_manual_mode(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """The target temperature has no effect without the algorithm."""
    await send_uplink(hass, mock_connection, descriptor, f"1800{KEEP_ALIVE}")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {ATTR_ENTITY_ID: CLIMATE, "temperature": 21},
            blocking=True,
        )
    assert err.value.translation_key == "requires_automatic_mode"


async def test_new_target_ends_algorithm_pause(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """The device resumes its algorithm when the target changes."""
    entity_id = entity_id_for(hass, "switch", descriptor, "algorithm_paused")
    await send_uplink(hass, mock_connection, descriptor, f"0423506801{KEEP_ALIVE}")
    assert hass.states.get(entity_id).state == STATE_ON

    await hass.services.async_call(
        "climate",
        "set_temperature",
        {ATTR_ENTITY_ID: CLIMATE, "temperature": 21},
        blocking=True,
    )

    assert hass.states.get(entity_id).state == STATE_OFF


async def test_manual_ring_change_ends_algorithm_pause(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Turning the ring also resumes the algorithm."""
    entity_id = entity_id_for(hass, "switch", descriptor, "algorithm_paused")
    await send_uplink(hass, mock_connection, descriptor, f"0423506801{KEEP_ALIVE}")

    await send_uplink(hass, mock_connection, descriptor, f"2816{KEEP_ALIVE}")

    assert hass.states.get(entity_id).state == STATE_OFF


async def test_operating_mode_is_rechecked_while_it_can_change(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A device leaves manual mode by itself, so keep asking."""
    await send_uplink(hass, mock_connection, descriptor, f"1800{KEEP_ALIVE}")

    freezer.tick(timedelta(minutes=10))
    await send_uplink(hass, mock_connection, descriptor)
    assert last_data(mock_connection) != "18"

    freezer.tick(timedelta(hours=1))
    await send_uplink(hass, mock_connection, descriptor)
    assert last_data(mock_connection) == "18"


async def test_automatic_mode_is_not_rechecked(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Automatic is where the device falls back to, so it cannot change."""
    await send_uplink(hass, mock_connection, descriptor, f"1801{KEEP_ALIVE}")

    freezer.tick(timedelta(hours=2))
    await send_uplink(hass, mock_connection, descriptor)

    assert not any(
        downlink.data == b"\x18" for downlink in mock_connection.downlinks.values()
    )


async def test_restart(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """The restart button sends an unconfirmed reset."""
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: entity_id_for(hass, "button", descriptor, "restart")},
        blocking=True,
    )
    downlink = list(mock_connection.downlinks.values())[-1]
    assert downlink.data == bytes.fromhex("30")
    assert not downlink.confirmed


async def test_room_sensor_moves_the_offset(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """In automatic mode the offset closes the gap to the room sensor."""
    link_room_sensor(hass, config_entry, descriptor)
    hass.states.async_set(
        ROOM_SENSOR, "24", {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS}
    )

    await send_uplink(hass, mock_connection, descriptor, f"1801541c{KEEP_ALIVE}")
    assert last_data(mock_connection) == "532554"
    count = len(mock_connection.downlinks)

    await send_uplink(hass, mock_connection, descriptor)
    await send_uplink(hass, mock_connection, descriptor)
    assert not [
        downlink
        for downlink in list(mock_connection.downlinks.values())[count:]
        if downlink.data.startswith(b"\x53")
    ]


async def test_room_sensor_inside_deadband(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A small difference is not worth a downlink."""
    link_room_sensor(hass, config_entry, descriptor)
    hass.states.async_set(ROOM_SENSOR, "22.7", {})

    await send_uplink(hass, mock_connection, descriptor, f"1801541c{KEEP_ALIVE}")

    assert not [
        downlink
        for downlink in mock_connection.downlinks.values()
        if downlink.data.startswith(b"\x53")
    ]


async def test_room_sensor_feeds_external_mode(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """In external mode the reading replaces the device sensor."""
    link_room_sensor(hass, config_entry, descriptor)
    hass.states.async_set(
        ROOM_SENSOR, "70.7", {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.FAHRENHEIT}
    )

    await send_uplink(hass, mock_connection, descriptor, f"1802{KEEP_ALIVE}")
    assert last_data(mock_connection) == "3c00d7"
    count = len(mock_connection.downlinks)

    await send_uplink(hass, mock_connection, descriptor)
    assert not [
        downlink
        for downlink in list(mock_connection.downlinks.values())[count:]
        if downlink.data.startswith(b"\x3c")
    ]


async def test_unavailable_room_sensor_is_ignored(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Do not act on a sensor without a reading."""
    link_room_sensor(hass, config_entry, descriptor)
    hass.states.async_set(ROOM_SENSOR, STATE_UNAVAILABLE, {})

    await send_uplink(hass, mock_connection, descriptor, f"1802{KEEP_ALIVE}")

    assert not [
        downlink
        for downlink in mock_connection.downlinks.values()
        if downlink.data.startswith(b"\x3c")
    ]


async def test_options_flow_links_and_unlinks_a_sensor(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    descriptor: DeviceDescriptor,
) -> None:
    """The options flow stores one sensor per device."""
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": descriptor.dev_eui}
    )
    assert result["step_id"] == "room_sensor"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"room_sensor": ROOM_SENSOR}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        "room_sensors": {descriptor.dev_eui: ROOM_SENSOR}
    }

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": descriptor.dev_eui}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert config_entry.options == {"room_sensors": {}}


async def test_options_flow_without_devices(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The options flow needs a loaded entry."""
    assert await hass.config_entries.async_unload(config_entry.entry_id)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices"
