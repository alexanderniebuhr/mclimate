"""MClimate device updates."""

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
import logging
import time
from typing import Any, override

from lorawan_connection import DownlinkError

from homeassistant.components.lorawan import device_identifier
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import CONF_ROOM_SENSORS, DOMAIN
from .protocol import KeepAlive, Version
from .vicki import CommandRejected, Vicki

_LOGGER = logging.getLogger(__name__)

# The room sensor only moves the offset for a difference worth a downlink, and
# then waits until the device can have reported the effect.
OFFSET_DEADBAND = 0.5
OFFSET_LIMIT = 4.9
OFFSET_WAIT_UPLINKS = 2

EXTERNAL_DEADBAND = 0.2
EXTERNAL_REFRESH_SECONDS = 6 * 3600

# The device falls back to automatic after 12 hours without a motor command or
# external reading, without saying so in the keep-alive.
MODE_REFRESH_INTERVAL = timedelta(hours=1)
FALLBACK_MODES = ("manual", "automatic_external")


def _format_version(version: Version | None) -> str | None:
    """Format a device version for the device registry."""
    return f"{version[0]}.{version[1]}" if version is not None else None


class VickiCoordinator(DataUpdateCoordinator[Vicki]):
    """Coordinate updates of one Vicki."""

    def __init__(self, hass: HomeAssistant, device: Vicki, entry_id: str) -> None:
        """Subscribe once to the device model."""
        super().__init__(
            hass,
            _LOGGER,
            # DeviceManager owns the coordinator's lifecycle.
            config_entry=None,
            name=device.descriptor.name,
        )
        self._entry_id = entry_id
        self._registered_firmware: Version | None = None
        self._seen_keep_alive: KeepAlive | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._offset_wait = 0
        self._last_external: float | None = None
        self._last_external_at = 0.0
        self._mode_checked_at: datetime | None = None
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
        keep_alive = self.data.keep_alive
        if keep_alive is not None and keep_alive is not self._seen_keep_alive:
            self._seen_keep_alive = keep_alive
            self._async_request_state()
            self._async_sync_room_sensor(keep_alive)
            self._async_check_operating_mode()

    @callback
    def _async_update_device_registry(self) -> None:
        """Store firmware details once the device has reported them."""
        firmware = self.data.firmware_version
        if firmware is None or firmware == self._registered_firmware:
            return
        registry = dr.async_get(self.hass)
        if device := registry.async_get_device_by_identifier(
            device_identifier(DOMAIN, self.data), self._entry_id
        ):
            self._registered_firmware = firmware
            registry.async_update_device(
                device.id,
                hw_version=_format_version(self.data.hardware_version),
                sw_version=_format_version(firmware),
            )

    @property
    def room_sensor(self) -> str | None:
        """Return the temperature sensor linked to this device."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return None
        sensors = entry.options.get(CONF_ROOM_SENSORS, {})
        return sensors.get(self.data.descriptor.dev_eui)

    def _room_temperature(self) -> float | None:
        """Return the linked sensor's reading in degrees Celsius."""
        if (sensor := self.room_sensor) is None:
            return None
        if (state := self.hass.states.get(sensor)) is None:
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature.CELSIUS)
        return TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)

    @callback
    def _async_run(
        self,
        command: Coroutine[Any, Any, None],
        on_failure: Callable[[], None] | None = None,
    ) -> None:
        """Send a command the user did not ask for in the background."""

        async def _async_guarded() -> None:
            try:
                await command
            except DownlinkError, TimeoutError, CommandRejected:
                _LOGGER.debug("Could not send a command to %s", self.name)
                if on_failure is not None:
                    on_failure()

        task = self.hass.async_create_background_task(
            _async_guarded(), f"{self.name} command"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @callback
    def _async_request_state(self) -> None:
        """Ask the device for firmware and settings it has not reported yet."""
        if (request := self.data.next_state_request()) is not None:
            self._async_run(
                self.data.async_send_state_request(request),
                self.data.state_request_failed,
            )

    @callback
    def _async_check_operating_mode(self) -> None:
        """Keep asking while the device can leave its mode on its own."""
        if self.data.settings.get("operating_mode") not in FALLBACK_MODES:
            self._mode_checked_at = None
            return
        now = dt_util.utcnow()
        if self._mode_checked_at is None:
            self._mode_checked_at = now
        elif now - self._mode_checked_at >= MODE_REFRESH_INTERVAL:
            self._mode_checked_at = now
            self._async_run(self.data.async_refresh_operating_mode())

    @callback
    def _async_sync_room_sensor(self, keep_alive: KeepAlive) -> None:
        """Apply the linked room sensor according to the operating mode."""
        if (room := self._room_temperature()) is None:
            return
        mode = self.data.settings.get("operating_mode")
        if mode == "automatic_external":
            self._async_send_external_temperature(room)
        elif mode == "automatic":
            self._async_adjust_offset(room, keep_alive)

    @callback
    def _async_send_external_temperature(self, room: float) -> None:
        """Forward a changed reading, and refresh it now and then regardless."""
        now = time.monotonic()
        if (
            self._last_external is not None
            and abs(room - self._last_external) < EXTERNAL_DEADBAND
            and now - self._last_external_at < EXTERNAL_REFRESH_SECONDS
        ):
            return
        self._last_external = room
        self._last_external_at = now
        self._async_run(self.data.async_set_external_temperature(room))

    @callback
    def _async_adjust_offset(self, room: float, keep_alive: KeepAlive) -> None:
        """Move the offset so the device reading follows the room sensor."""
        if self._offset_wait:
            self._offset_wait -= 1
            return
        if (offset := self.data.settings.get("temperature_offset")) is None:
            return
        wanted = round(offset + room - keep_alive.temperature, 1)
        wanted = max(-OFFSET_LIMIT, min(OFFSET_LIMIT, wanted))
        if abs(wanted - offset) >= OFFSET_DEADBAND:
            self._offset_wait = OFFSET_WAIT_UPLINKS
            self._async_run(self.data.async_set_setting("temperature_offset", wanted))

    @override
    async def async_shutdown(self) -> None:
        """Unsubscribe from device updates."""
        self._unsubscribe()
        for task in self._tasks:
            task.cancel()
        await super().async_shutdown()
