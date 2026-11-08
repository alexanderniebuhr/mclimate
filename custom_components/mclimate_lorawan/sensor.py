"""Sensor platform for MClimate devices."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MClimateConfigEntry
from .coordinator import VickiCoordinator
from .entity import VickiEntity, from_keep_alive
from .vicki import Vicki

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class VickiSensorDescription(SensorEntityDescription):
    """Select a value from the device model."""

    value_fn: Callable[[Vicki], float | None]


DESCRIPTIONS = (
    VickiSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=from_keep_alive(lambda data: data.temperature),
    ),
    VickiSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=from_keep_alive(lambda data: data.humidity),
    ),
    VickiSensorDescription(
        key="valve_openness",
        translation_key="valve_openness",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=from_keep_alive(lambda data: data.valve_openness),
    ),
    VickiSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=from_keep_alive(lambda data: data.battery_voltage),
    ),
    VickiSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.battery_level,
    ),
    VickiSensorDescription(
        key="motor_position",
        translation_key="motor_position",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=from_keep_alive(lambda data: data.motor_position),
    ),
    VickiSensorDescription(
        key="motor_range",
        translation_key="motor_range",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=from_keep_alive(lambda data: data.motor_range),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MClimateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for existing and newly discovered devices."""

    @callback
    def added(coordinator: VickiCoordinator) -> None:
        async_add_entities(
            VickiSensor(coordinator, description) for description in DESCRIPTIONS
        )

    entry.async_on_unload(entry.runtime_data.subscribe_coordinator_added(added))


class VickiSensor(VickiEntity, SensorEntity):
    """A measurement of a Vicki."""

    entity_description: VickiSensorDescription

    @property
    @override
    def native_value(self) -> float | None:
        """Return the last reported value."""
        return self.entity_description.value_fn(self.device)
