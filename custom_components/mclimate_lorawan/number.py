"""Number platform for MClimate devices."""

from typing import override

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MClimateConfigEntry
from .coordinator import VickiCoordinator
from .entity import VickiEntity, VickiSettingEntity

PARALLEL_UPDATES = 0


def _temperature(
    key: str,
    minimum: float,
    maximum: float,
    step: float,
    *,
    enabled: bool = True,
) -> NumberEntityDescription:
    """Describe a temperature setting."""
    return NumberEntityDescription(
        key=key,
        translation_key=key,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=enabled,
        mode=NumberMode.BOX,
        native_min_value=minimum,
        native_max_value=maximum,
        native_step=step,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    )


def _plain(
    key: str,
    minimum: float,
    maximum: float,
    step: float,
    unit: str | None = None,
    *,
    enabled: bool = False,
) -> NumberEntityDescription:
    """Describe a setting without a device class."""
    return NumberEntityDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=enabled,
        mode=NumberMode.BOX,
        native_min_value=minimum,
        native_max_value=maximum,
        native_step=step,
        native_unit_of_measurement=unit,
    )


DESCRIPTIONS = (
    _plain("keep_alive_period", 3, 255, 1, UnitOfTime.MINUTES, enabled=True),
    _temperature("target_temperature_min", 5, 30, 1),
    _temperature("target_temperature_max", 5, 30, 1),
    _plain("temperature_offset", -4.9, 4.9, 0.1, UnitOfTemperature.CELSIUS, enabled=True),
    _plain("window_duration", 5, 1275, 5, UnitOfTime.MINUTES, enabled=True),
    _plain("window_delta", 0.2, 25.5, 0.1, UnitOfTemperature.CELSIUS, enabled=True),
    _temperature("anti_freeze_activation", 0.1, 25.5, 0.1, enabled=False),
    _temperature("anti_freeze_deactivation", 0.1, 25.5, 0.1, enabled=False),
    _temperature("anti_freeze_target", 5, 30, 1, enabled=False),
    _plain("valve_minimum", 0, 100, 1, PERCENTAGE),
    _plain("valve_maximum", 0, 100, 1, PERCENTAGE),
    _plain("setback_time", 0, 2550, 10, UnitOfTime.MINUTES),
    _temperature("offline_target", 0, 30, 0.1, enabled=False),
    _plain("pi_proportional_gain", 0, 127, 0.00001),
    _plain("pi_integral_gain", 0, 127, 0.00001),
    _plain("pi_max_integral", 0, 1000, 0.1),
    _plain("pi_run_period", 1, 255, 1, UnitOfTime.MINUTES),
    _plain("pi_hysteresis", 0, 10, 0.1, UnitOfTemperature.CELSIUS),
    _plain("led_duration", 0.5, 10, 0.5, UnitOfTime.SECONDS),
    _plain("join_retry_period", 240, 1275, 5, UnitOfTime.SECONDS),
    _plain("watchdog_confirmed", 0, 255, 1),
    _plain("watchdog_unconfirmed", 0, 255, 1, UnitOfTime.HOURS),
)

VALVE_DESCRIPTION = NumberEntityDescription(
    key="valve_position",
    translation_key="valve_position",
    native_min_value=0,
    native_max_value=100,
    native_step=1,
    native_unit_of_measurement=PERCENTAGE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MClimateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up numbers for existing and newly discovered devices."""

    @callback
    def added(coordinator: VickiCoordinator) -> None:
        async_add_entities(
            VickiSettingNumber(coordinator, description) for description in DESCRIPTIONS
        )
        async_add_entities([VickiValvePosition(coordinator, VALVE_DESCRIPTION)])

    entry.async_on_unload(entry.runtime_data.subscribe_coordinator_added(added))


class VickiSettingNumber(VickiSettingEntity, NumberEntity):
    """A numeric device setting."""

    @property
    @override
    def native_value(self) -> float | None:
        """Return the last known value."""
        return self.setting_value

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Queue a new value."""
        await self.async_set_setting(value)


class VickiValvePosition(VickiEntity, NumberEntity):
    """Direct control of the valve, which only exists in manual mode."""

    @property
    @override
    def available(self) -> bool:
        """Only offer the valve while the device follows it."""
        return (
            super().available
            and self.device.settings.get("operating_mode") == "manual"
        )

    @property
    @override
    def native_value(self) -> float | None:
        """Return the commanded or reported valve position."""
        return self.device.valve_openness

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Queue a new valve position."""
        await self.async_send_command(
            self.device.async_set_valve_openness(round(value))
        )
