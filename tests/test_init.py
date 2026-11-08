"""Test integration setup and device lifecycle."""

from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from lorawan_connection import (
    ConnectionUnavailable,
    DeviceDescriptor,
    RemovedEvent,
)
from lorawan_connection.mock import MockConnection
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .conftest import DOMAIN, send_uplink


async def test_setup_retries_after_connection_recovers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    connection_entry: MockConfigEntry,
    mock_connection: MockConnection,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Retry a failed subscription and create entities once the backend recovers."""
    await hass.async_start()
    assert await hass.config_entries.async_setup(connection_entry.entry_id)

    with patch.object(
        mock_connection,
        "async_subscribe",
        side_effect=ConnectionUnavailable("Backend unavailable"),
    ):
        assert not await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.states.async_all("climate")

    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("climate.living_room").state == "unknown"


@pytest.mark.usefixtures("setup_integration")
async def test_unload(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Unloading the entry leaves nothing behind."""
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get("climate.living_room").state == STATE_UNAVAILABLE


@pytest.mark.usefixtures("setup_integration")
async def test_connection_loss(
    hass: HomeAssistant,
    connection_entry: MockConfigEntry,
) -> None:
    """Entities are unavailable while the LoRaWAN server is gone."""
    assert await hass.config_entries.async_unload(connection_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("climate.living_room").state == STATE_UNAVAILABLE


@pytest.mark.usefixtures("setup_integration")
async def test_removed_device(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """A device removed from the server leaves the device registry."""
    identifier = (DOMAIN, f"network:{descriptor.dev_eui}")
    assert device_registry.async_get_device(identifiers={identifier})

    mock_connection.emit(
        RemovedEvent(descriptor=descriptor, received_at=dt_util.utcnow())
    )
    await hass.async_block_till_done()

    assert device_registry.async_get_device(identifiers={identifier}) is None


@pytest.mark.usefixtures("setup_integration")
async def test_firmware_is_requested_once_and_registered(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Ask for the firmware after the first report and store the answer."""
    await send_uplink(hass, mock_connection, descriptor)
    await send_uplink(hass, mock_connection, descriptor)

    [downlink] = mock_connection.downlinks.values()
    assert downlink.data == bytes.fromhex("04")
    assert not downlink.confirmed

    await send_uplink(hass, mock_connection, descriptor, "042343")

    device = device_registry.async_get_device(
        identifiers={(DOMAIN, f"network:{descriptor.dev_eui}")}
    )
    assert device is not None
    assert device.hw_version == "2.3"
    assert device.sw_version == "4.3"


@pytest.mark.usefixtures("setup_integration")
async def test_invalid_uplink_keeps_values(
    hass: HomeAssistant,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Invalid data leaves the previous values intact."""
    await send_uplink(hass, mock_connection, descriptor)
    await send_uplink(hass, mock_connection, descriptor, "a6")
    assert hass.states.get("sensor.living_room_humidity").state == "46.88"
