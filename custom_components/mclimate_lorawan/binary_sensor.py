"""Binary sensor platform for MClimate devices."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MClimateConfigEntry
from .coordinator import VickiCoordinator
from .entity import VickiEntity, from_keep_alive
from .vicki import Vicki

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class VickiBinarySensorDescription(BinarySensorEntityDescription):
    """Select a flag from the device model."""

    value_fn: Callable[[Vicki], bool | None]


DESCRIPTIONS = (
    VickiBinarySensorDescription(
        key="open_window",
        translation_key="open_window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=from_keep_alive(lambda data: data.open_window),
    ),
    VickiBinarySensorDescription(
        key="anti_freeze",
        translation_key="anti_freeze",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=from_keep_alive(lambda data: data.anti_freeze),
    ),
    VickiBinarySensorDescription(
        key="battery_low",
        translation_key="battery_low",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=from_keep_alive(lambda data: data.battery_low),
    ),
    VickiBinarySensorDescription(
        key="sensor_broken",
        translation_key="sensor_broken",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=from_keep_alive(lambda data: data.sensor_broken),
    ),
    VickiBinarySensorDescription(
        key="calibration_failed",
        translation_key="calibration_failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=from_keep_alive(lambda data: data.calibration_failed),
    ),
    VickiBinarySensorDescription(
        key="attached_backplate",
        translation_key="attached_backplate",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=from_keep_alive(lambda data: data.attached_backplate),
    ),
    VickiBinarySensorDescription(
        key="high_motor_consumption",
        translation_key="high_motor_consumption",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=from_keep_alive(lambda data: data.high_motor_consumption),
    ),
    VickiBinarySensorDescription(
        key="low_motor_consumption",
        translation_key="low_motor_consumption",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=from_keep_alive(lambda data: data.low_motor_consumption),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MClimateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors for existing and newly discovered devices."""

    @callback
    def added(coordinator: VickiCoordinator) -> None:
        async_add_entities(
            VickiBinarySensor(coordinator, description) for description in DESCRIPTIONS
        )

    entry.async_on_unload(entry.runtime_data.subscribe_coordinator_added(added))


class VickiBinarySensor(VickiEntity, BinarySensorEntity):
    """A status flag of a Vicki."""

    entity_description: VickiBinarySensorDescription

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the last reported flag."""
        return self.entity_description.value_fn(self.device)
