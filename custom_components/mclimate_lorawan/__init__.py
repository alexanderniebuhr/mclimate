"""Support MClimate devices over LoRaWAN."""

from lorawan_connection import ConnectionUnavailable

from homeassistant.components.lorawan import DeviceManager
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import VickiCoordinator
from .vicki import Vicki, VickiCollection

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type MClimateConfigEntry = ConfigEntry[DeviceManager[Vicki, VickiCoordinator]]

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: MClimateConfigEntry) -> None:
    """Set up MClimate devices across the available LoRaWAN connections."""
    manager = entry.runtime_data = DeviceManager(
        hass,
        entry,
        create_collection=VickiCollection,
        create_coordinator=lambda hass, device: VickiCoordinator(
            hass, device, entry.entry_id
        ),
    )
    entry.async_on_unload(manager.close)
    try:
        await manager.async_setup()
    except ConnectionUnavailable as err:
        raise ConfigEntryNotReady(str(err)) from err
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(hass: HomeAssistant, entry: MClimateConfigEntry) -> None:
    """Unload entities; the manager releases the collection and coordinators."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
