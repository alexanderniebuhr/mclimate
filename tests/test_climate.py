"""Test the Vicki thermostat."""

from unittest.mock import patch

from lorawan_connection import DeviceDescriptor, DownlinkError
from lorawan_connection.mock import MockConnection
import pytest

from homeassistant.components.climate import (
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .conftest import KEEP_ALIVE, send_uplink

ENTITY_ID = "climate.living_room"

pytestmark = pytest.mark.usefixtures("setup_integration")


async def set_temperature(hass: HomeAssistant, **data: object) -> None:
    """Call the set_temperature action."""
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {ATTR_ENTITY_ID: ENTITY_ID, **data},
        blocking=True,
    )


async def set_hvac_mode(hass: HomeAssistant, mode: HVACMode) -> None:
    """Call the set_hvac_mode action."""
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: mode},
        blocking=True,
    )


def last_data(connection: MockConnection) -> str:
    """Return the most recent downlink."""
    return list(connection.downlinks.values())[-1].data.hex()


async def test_unknown_until_first_uplink(hass: HomeAssistant) -> None:
    """Values are unknown until the device has reported."""
    state = hass.states.get(ENTITY_ID)
    assert state.state == "unknown"
    assert state.attributes.get(ATTR_HVAC_ACTION) is None


async def test_reported_state(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A keep-alive updates the thermostat."""
    await send_uplink(hass, mock_connection, descriptor)
    state = hass.states.get(ENTITY_ID)
    assert state.state == HVACMode.HEAT
    assert state.attributes["current_temperature"] == 22.5
    assert state.attributes[ATTR_TEMPERATURE] == 20
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.HEATING
    assert state.attributes["target_temp_step"] == 0.5


async def test_idle_when_valve_closed(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A fully closed valve means the thermostat is idle."""
    await send_uplink(hass, mock_connection, descriptor, "81149c782c2c11f0a0")
    state = hass.states.get(ENTITY_ID)
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.IDLE


async def test_precise_target_report(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A reported 0.1 degree target replaces the rounded keep-alive value."""
    await send_uplink(hass, mock_connection, descriptor, f"520102{KEEP_ALIVE}")
    state = hass.states.get(ENTITY_ID)
    assert state.attributes[ATTR_TEMPERATURE] == 25.8


async def test_set_whole_temperature(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A new target is queued with 0.1 degree resolution and shows immediately."""
    await send_uplink(hass, mock_connection, descriptor)

    await set_temperature(hass, temperature=21)

    downlink = list(mock_connection.downlinks.values())[-1]
    assert downlink.data == bytes.fromhex("5100d2")
    assert downlink.f_port == 1
    assert not downlink.confirmed
    assert hass.states.get(ENTITY_ID).attributes[ATTR_TEMPERATURE] == 21


async def test_commanded_value_survives_delivery_uplink(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Keep showing the command until the device could have applied it."""
    await send_uplink(hass, mock_connection, descriptor)
    await set_temperature(hass, temperature=21)

    await send_uplink(hass, mock_connection, descriptor)
    assert hass.states.get(ENTITY_ID).attributes[ATTR_TEMPERATURE] == 21

    await send_uplink(hass, mock_connection, descriptor)
    assert hass.states.get(ENTITY_ID).attributes[ATTR_TEMPERATURE] == 20


async def test_set_fractional_temperature(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Fractions are sent in tenths of a degree."""
    await send_uplink(hass, mock_connection, descriptor)

    await set_temperature(hass, temperature=21.5)

    assert last_data(mock_connection) == "5100d7"


async def test_old_firmware_refused(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Firmware before 4.3 is not supported."""
    await send_uplink(hass, mock_connection, descriptor, f"042342{KEEP_ALIVE}")
    with pytest.raises(ServiceValidationError) as err:
        await set_temperature(hass, temperature=21.5)
    assert err.value.translation_key == "firmware_too_old"


async def test_legacy_firmware_refused(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A legacy keep-alive means firmware before 3.5."""
    await send_uplink(hass, mock_connection, descriptor, "011D5A78FA2C01F080")
    with pytest.raises(ServiceValidationError) as err:
        await set_temperature(hass, temperature=21)
    assert err.value.translation_key == "firmware_too_old"


async def test_downlink_failure(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A rejected command is reported and does not change the state."""
    await send_uplink(hass, mock_connection, descriptor)
    with (
        patch.object(
            mock_connection, "async_send_downlink", side_effect=DownlinkError("no")
        ),
        pytest.raises(HomeAssistantError) as err,
    ):
        await set_temperature(hass, temperature=21)
    assert err.value.translation_key == "command_failed"
    assert hass.states.get(ENTITY_ID).attributes[ATTR_TEMPERATURE] == 20


async def test_downlink_timeout(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A server that does not respond is reported."""
    await send_uplink(hass, mock_connection, descriptor)
    with (
        patch.object(mock_connection, "async_send_downlink", side_effect=TimeoutError),
        pytest.raises(HomeAssistantError) as err,
    ):
        await set_temperature(hass, temperature=21)
    assert err.value.translation_key == "command_timeout"


async def test_off_and_back_on(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Off is the lowest target, and heat restores the last target."""
    await send_uplink(hass, mock_connection, descriptor)

    await set_hvac_mode(hass, HVACMode.OFF)
    assert last_data(mock_connection) == "510032"
    state = hass.states.get(ENTITY_ID)
    assert state.state == HVACMode.OFF
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.OFF

    await set_hvac_mode(hass, HVACMode.HEAT)
    assert last_data(mock_connection) == "5100c8"
    assert hass.states.get(ENTITY_ID).state == HVACMode.HEAT


async def test_heat_when_already_heating(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Do not spend a downlink on a mode the device is already in."""
    await send_uplink(hass, mock_connection, descriptor)
    count = len(mock_connection.downlinks)
    await set_hvac_mode(hass, HVACMode.HEAT)
    assert len(mock_connection.downlinks) == count


async def test_set_temperature_with_off_mode(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """The off mode wins over a temperature in the same action."""
    await send_uplink(hass, mock_connection, descriptor)
    await set_temperature(hass, temperature=21, hvac_mode=HVACMode.OFF)
    assert last_data(mock_connection) == "510032"
