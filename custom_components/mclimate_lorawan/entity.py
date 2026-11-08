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
from .vicki import UnsupportedCommand, Vicki

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
        except UnsupportedCommand as err:
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
