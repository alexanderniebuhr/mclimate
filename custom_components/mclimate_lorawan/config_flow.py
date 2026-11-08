"""MClimate config flow."""

from typing import Any, override

import probatio

from homeassistant.components.lorawan import (
    LoRaWANDiscoveryInfo,
    NoConnectionsError,
    NoSupportedDevicesError,
    async_validate_devices,
)
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import CONF_DEVICE, CONF_ROOM_SENSOR, CONF_ROOM_SENSORS, DOMAIN
from .vicki import VickiCollection


class MClimateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create one entry for all supported devices."""

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> MClimateOptionsFlow:
        """Create the options flow."""
        return MClimateOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup without choosing a server."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return await self.async_step_confirm(user_input)

    @override
    async def async_step_integration_discovery(
        self, discovery_info: LoRaWANDiscoveryInfo | dict[str, Any]
    ) -> ConfigFlowResult:
        """Discover the vendor once across all servers."""
        return await self.async_step_user()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm MClimate setup."""
        try:
            await async_validate_devices(self.hass, create_collection=VickiCollection)
        except NoConnectionsError:
            return self.async_abort(reason="no_lorawan_connections")
        except NoSupportedDevicesError:
            return self.async_abort(reason="no_supported_devices")

        if user_input is not None:
            return self.async_create_entry(title="MClimate", data={})

        return self.async_show_form(step_id="confirm")


class MClimateOptionsFlow(OptionsFlow):
    """Link a room temperature sensor to a device."""

    def __init__(self) -> None:
        """Initialize the selected device."""
        self._dev_eui = ""

    @override
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the device to configure."""
        if self.config_entry.state is not ConfigEntryState.LOADED or not (
            coordinators := self.config_entry.runtime_data.coordinators
        ):
            return self.async_abort(reason="no_devices")
        if user_input is not None:
            self._dev_eui = user_input[CONF_DEVICE]
            return await self.async_step_room_sensor()
        options = [
            SelectOptionDict(
                value=coordinator.data.descriptor.dev_eui,
                label=coordinator.data.descriptor.name,
            )
            for coordinator in coordinators.values()
        ]
        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_DEVICE): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def async_step_room_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Link or unlink the room sensor of the chosen device."""
        sensors = dict(self.config_entry.options.get(CONF_ROOM_SENSORS, {}))
        if user_input is not None:
            sensors.pop(self._dev_eui, None)
            if sensor := user_input.get(CONF_ROOM_SENSOR):
                sensors[self._dev_eui] = sensor
            return self.async_create_entry(data={CONF_ROOM_SENSORS: sensors})
        return self.async_show_form(
            step_id="room_sensor",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_ROOM_SENSOR,
                        description={"suggested_value": sensors.get(self._dev_eui)},
                    ): EntitySelector(
                        EntitySelectorConfig(
                            domain=SENSOR_DOMAIN,
                            device_class=SensorDeviceClass.TEMPERATURE,
                        )
                    )
                }
            ),
        )
