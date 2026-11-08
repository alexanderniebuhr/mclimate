"""Base entity for MClimate devices."""

from asyncio import timeout
from collections.abc import Callable, Coroutine
from typing import Any, override

from lorawan_connection import DownlinkError

from homeassistant.components.lorawan import LoRaWANEntity
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import VickiCoordinator
from .protocol import KeepAlive
from .vicki import CommandRejected, Vicki

COMMAND_TIMEOUT = 30


def from_keep_alive[T](
    value_fn: Callable[[KeepAlive], T],
) -> Callable[[Vicki], T | None]:
    """Read a value from the last keep-alive, if there has been one."""

    def get_value(device: Vicki) -> T | None:
        return None if device.keep_alive is None else value_fn(device.keep_alive)

    return get_value


class VickiEntity(LoRaWANEntity[Vicki]):
    """Base entity for a Vicki."""

    coordinator: VickiCoordinator

    @property
    @override
    def device_info(self) -> DeviceInfo:
        """Describe the device this entity belongs to."""
        return self.coordinator.device_info

    async def async_send_command(self, command: Coroutine[Any, Any, None]) -> None:
        """Queue a command, translating failures for the user."""
        try:
            async with timeout(COMMAND_TIMEOUT):
                await command
        except CommandRejected as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=err.args[0]
            ) from err
        except TimeoutError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_timeout"
            ) from err
        except DownlinkError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_failed"
            ) from err


class VickiSettingEntity(VickiEntity):
    """Entity for a setting the device stores and reports on request."""

    @property
    @override
    def available(self) -> bool:
        """Hide settings the device firmware does not have."""
        return super().available and self.device.supports_setting(
            self.entity_description.key
        )

    @property
    def setting_value(self) -> Any:
        """Return the last known value of the setting."""
        return self.device.settings.get(self.entity_description.key)

    async def async_set_setting(self, value: Any) -> None:
        """Queue a new value for the setting."""
        await self.async_send_command(
            self.device.async_set_setting(self.entity_description.key, value)
        )
