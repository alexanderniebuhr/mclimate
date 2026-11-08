"""Button platform for MClimate devices."""

from typing import override

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MClimateConfigEntry
from .coordinator import VickiCoordinator
from .entity import VickiEntity

PARALLEL_UPDATES = 0

DESCRIPTION = ButtonEntityDescription(
    key="restart",
    device_class=ButtonDeviceClass.RESTART,
    entity_category=EntityCategory.CONFIG,
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MClimateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons for existing and newly discovered devices."""

    @callback
    def added(coordinator: VickiCoordinator) -> None:
        async_add_entities([VickiRestart(coordinator, DESCRIPTION)])

    entry.async_on_unload(entry.runtime_data.subscribe_coordinator_added(added))


class VickiRestart(VickiEntity, ButtonEntity):
    """Restart a Vicki, which also recalibrates its motor and rejoins the network."""

    @override
    async def async_press(self) -> None:
        """Queue the restart."""
        await self.async_send_command(self.device.async_restart())
