"""MClimate device updates."""

import asyncio
import logging
import time
from typing import override

from lorawan_connection import DownlinkError

from homeassistant.components.lorawan import device_identifier
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .protocol import Version
from .vicki import Vicki

_LOGGER = logging.getLogger(__name__)

VERSION_REQUEST_INTERVAL = 3600


def _format_version(version: Version | None) -> str | None:
    """Format a device version for the device registry."""
    return f"{version[0]}.{version[1]}" if version is not None else None


class VickiCoordinator(DataUpdateCoordinator[Vicki]):
    """Coordinate updates of one Vicki."""

    def __init__(self, hass: HomeAssistant, device: Vicki) -> None:
        """Subscribe once to the device model."""
        super().__init__(
            hass,
            _LOGGER,
            # DeviceManager owns the coordinator's lifecycle.
            config_entry=None,
            name=device.descriptor.name,
        )
        self._registered_firmware: Version | None = None
        self._versions_requested_at: float | None = None
        self._version_task: asyncio.Task[None] | None = None
        self.async_set_updated_data(device)
        self._unsubscribe = device.add_update_listener(self._async_device_updated)

    @property
    def device_info(self) -> DeviceInfo:
        """Describe this device for its entities."""
        return DeviceInfo(
            identifiers={device_identifier(DOMAIN, self.data)},
            name=self.data.descriptor.name,
            manufacturer="MClimate",
            model="Vicki",
            model_id="vicki",
            hw_version=_format_version(self.data.hardware_version),
            sw_version=_format_version(self.data.firmware_version),
        )

    @override
    @callback
    def async_set_updated_data(self, data: Vicki) -> None:
        """Log once when the LoRaWAN connection returns."""
        if not self.last_update_success:
            _LOGGER.info("Connection to %s restored", self.name)
        super().async_set_updated_data(data)

    @callback
    def _async_device_updated(self) -> None:
        """Update entities and fill in what the device has not reported yet."""
        self.async_set_updated_data(self.data)
        self._async_update_device_registry()
        self._async_request_versions()

    @callback
    def _async_update_device_registry(self) -> None:
        """Store firmware details once the device has reported them."""
        firmware = self.data.firmware_version
        if firmware is None or firmware == self._registered_firmware:
            return
        registry = dr.async_get(self.hass)
        if device := registry.async_get_device(
            identifiers={device_identifier(DOMAIN, self.data)}
        ):
            self._registered_firmware = firmware
            registry.async_update_device(
                device.id,
                hw_version=_format_version(self.data.hardware_version),
                sw_version=_format_version(firmware),
            )

    @callback
    def _async_request_versions(self) -> None:
        """Ask a device that is talking to us for its firmware version."""
        if self.data.keep_alive is None or self.data.firmware_version is not None:
            return
        now = time.monotonic()
        if (
            self._versions_requested_at is not None
            and now - self._versions_requested_at < VERSION_REQUEST_INTERVAL
        ):
            return
        self._versions_requested_at = now
        self._version_task = self.hass.async_create_background_task(
            self._async_send_version_request(), f"{self.name} version request"
        )

    async def _async_send_version_request(self) -> None:
        """Queue the version request, retrying on a later uplink on failure."""
        try:
            await self.data.async_request_versions()
        except DownlinkError, TimeoutError:
            _LOGGER.debug("Could not request versions from %s", self.name)
            self._versions_requested_at = None

    @override
    async def async_shutdown(self) -> None:
        """Unsubscribe from device updates."""
        self._unsubscribe()
        if self._version_task is not None:
            self._version_task.cancel()
        await super().async_shutdown()
