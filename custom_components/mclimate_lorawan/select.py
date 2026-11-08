"""Select platform for MClimate devices."""

from typing import override

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MClimateConfigEntry
from .const import DOMAIN
from .coordinator import VickiCoordinator
from .entity import VickiSettingEntity
from .protocol import DISPLAY_UNITS, OPERATING_MODES, PRIMARY_MODES, UPLINK_TYPES

PARALLEL_UPDATES = 0

DESCRIPTIONS = (
    SelectEntityDescription(
        key="operating_mode",
        translation_key="operating_mode",
        entity_category=EntityCategory.CONFIG,
        options=list(OPERATING_MODES),
    ),
    SelectEntityDescription(
        key="primary_mode",
        translation_key="primary_mode",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        options=list(PRIMARY_MODES),
    ),
    SelectEntityDescription(
        key="display_units",
        translation_key="display_units",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        options=list(DISPLAY_UNITS),
    ),
    SelectEntityDescription(
        key="uplink_type",
        translation_key="uplink_type",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        options=list(UPLINK_TYPES),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MClimateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up selects for existing and newly discovered devices."""

    @callback
    def added(coordinator: VickiCoordinator) -> None:
        async_add_entities(
            VickiSettingSelect(coordinator, description) for description in DESCRIPTIONS
        )

    entry.async_on_unload(entry.runtime_data.subscribe_coordinator_added(added))


class VickiSettingSelect(VickiSettingEntity, SelectEntity):
    """A device setting with fixed choices."""

    @property
    @override
    def current_option(self) -> str | None:
        """Return the last known choice."""
        return self.setting_value

    @override
    async def async_select_option(self, option: str) -> None:
        """Queue a new choice."""
        if option == "automatic_external" and self.coordinator.room_sensor is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="room_sensor_required"
            )
        await self.async_set_setting(option)
