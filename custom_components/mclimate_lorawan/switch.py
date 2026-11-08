"""Switch platform for MClimate devices."""

from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MClimateConfigEntry
from .coordinator import VickiCoordinator
from .entity import VickiEntity, VickiSettingEntity

PARALLEL_UPDATES = 0

DESCRIPTION = SwitchEntityDescription(
    key="child_lock",
    translation_key="child_lock",
    entity_category=EntityCategory.CONFIG,
)

SETTING_DESCRIPTIONS = (
    SwitchEntityDescription(
        key="window_detection",
        translation_key="window_detection",
        entity_category=EntityCategory.CONFIG,
    ),
    SwitchEntityDescription(
        key="child_lock_offline",
        translation_key="child_lock_offline",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    SwitchEntityDescription(
        key="algorithm_paused",
        translation_key="algorithm_paused",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
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
        async_add_entities(
            VickiSettingSwitch(coordinator, description)
            for description in SETTING_DESCRIPTIONS
        )

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


class VickiSettingSwitch(VickiSettingEntity, SwitchEntity):
    """A device setting that is on or off."""

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the last known state of the setting."""
        return self.setting_value

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self.async_set_setting(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self.async_set_setting(False)
