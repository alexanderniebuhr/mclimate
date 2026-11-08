"""Switch platform for MClimate devices."""

from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MClimateConfigEntry
from .coordinator import VickiCoordinator
from .entity import VickiEntity

PARALLEL_UPDATES = 0

DESCRIPTION = SwitchEntityDescription(
    key="child_lock",
    translation_key="child_lock",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MClimateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches for existing and newly discovered devices."""

    @callback
    def added(coordinator: VickiCoordinator) -> None:
        async_add_entities([VickiChildLock(coordinator, DESCRIPTION)])

    entry.async_on_unload(entry.runtime_data.subscribe_coordinator_added(added))


class VickiChildLock(VickiEntity, SwitchEntity):
    """Child lock of a Vicki."""

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the rotary ring is locked."""
        return self.device.child_lock

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Lock the rotary ring."""
        await self.async_send_command(self.device.async_set_child_lock(True))

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unlock the rotary ring."""
        await self.async_send_command(self.device.async_set_child_lock(False))
