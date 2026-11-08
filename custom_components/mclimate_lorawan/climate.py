"""Climate platform for MClimate devices."""

from typing import Any, override

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MClimateConfigEntry
from .coordinator import VickiCoordinator
from .entity import VickiEntity
from .protocol import MAX_TARGET_TEMPERATURE, MIN_TARGET_TEMPERATURE

PARALLEL_UPDATES = 0

DESCRIPTION = ClimateEntityDescription(key="thermostat", name=None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MClimateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up thermostats for existing and newly discovered devices."""

    @callback
    def added(coordinator: VickiCoordinator) -> None:
        async_add_entities([VickiClimate(coordinator)])

    entry.async_on_unload(entry.runtime_data.subscribe_coordinator_added(added))


class VickiClimate(VickiEntity, ClimateEntity):
    """Thermostat of a Vicki.

    The device has no off command, so off is the lowest target temperature.
    """

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_max_temp = MAX_TARGET_TEMPERATURE
    _attr_min_temp = MIN_TARGET_TEMPERATURE
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: VickiCoordinator) -> None:
        """Initialize the thermostat."""
        super().__init__(coordinator, DESCRIPTION)

    @property
    @override
    def native_current_temperature(self) -> float | None:
        """Return the temperature measured by the device."""
        keep_alive = self.device.keep_alive
        return keep_alive.temperature if keep_alive is not None else None

    @property
    @override
    def native_target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self.device.target_temperature

    @property
    @override
    def target_temperature_step(self) -> float:
        """Return the smallest step the firmware can apply."""
        return 0.5 if self.device.supports_precise_target else 1.0

    @property
    @override
    def hvac_mode(self) -> HVACMode | None:
        """Return off when the target is at the frost protection minimum."""
        target = self.device.target_temperature
        if target is None:
            return None
        return HVACMode.OFF if target <= MIN_TARGET_TEMPERATURE else HVACMode.HEAT

    @property
    @override
    def hvac_action(self) -> HVACAction | None:
        """Return whether the valve is letting water through."""
        keep_alive = self.device.keep_alive
        if keep_alive is None or self.hvac_mode is None:
            return None
        if self.hvac_mode is HVACMode.OFF:
            return HVACAction.OFF
        return HVACAction.HEATING if keep_alive.valve_openness else HVACAction.IDLE

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Switch between the lowest target and the last heating target."""
        if hvac_mode == HVACMode.OFF:
            target = float(MIN_TARGET_TEMPERATURE)
        elif self.hvac_mode is HVACMode.HEAT:
            return
        else:
            target = self.device.last_heating_target
        await self.async_send_command(self.device.async_set_target_temperature(target))

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        if kwargs.get(ATTR_HVAC_MODE) == HVACMode.OFF:
            await self.async_set_hvac_mode(HVACMode.OFF)
        elif (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.async_send_command(
                self.device.async_set_target_temperature(float(temperature))
            )
