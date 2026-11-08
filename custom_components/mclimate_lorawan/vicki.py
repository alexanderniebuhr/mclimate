"""Device model for the MClimate Vicki thermostat."""

from dataclasses import dataclass
import logging
from typing import override

from lorawan_connection import (
    Device,
    DeviceCollection,
    DeviceDescriptor,
    DeviceEvent,
    EventType,
)

from .protocol import (
    DOWNLINK_PORT,
    GET_VERSIONS,
    MIN_FIRMWARE,
    MIN_TARGET_TEMPERATURE,
    KeepAlive,
    Version,
    VickiProtocolError,
    decode_uplink,
    encode_child_lock,
    encode_target_temperature,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_HEATING_TARGET = 20.0

# A Class A downlink is delivered after the next uplink, so that uplink still
# reports the old state and only the one after it can show the result.
_PENDING_UPLINKS = 2


class CommandRejected(Exception):
    """A command cannot be sent. The argument names the reason."""


@dataclass(slots=True)
class _Pending[T]:
    """A commanded value waiting to be confirmed by the device."""

    value: T
    uplinks_left: int = _PENDING_UPLINKS


def _settle[T](pending: _Pending[T] | None, reported: T | None) -> _Pending[T] | None:
    """Drop a commanded value once the device confirmed or ignored it."""
    if pending is None or reported is None:
        return pending
    if reported == pending.value or pending.uplinks_left <= 1:
        return None
    pending.uplinks_left -= 1
    return pending


class Vicki(Device):
    """Model for the MClimate Vicki LoRaWAN thermostat."""

    identifiers = {
        "chirpstack": (824, "c521e66f-5745-45a0-b483-00fe1db8eaac"),
        "tts": ("mclimate", "vicki"),
    }

    def __init__(self, descriptor: DeviceDescriptor) -> None:
        """Initialize values as unobserved until a device report arrives."""
        super().__init__(descriptor)
        self.keep_alive: KeepAlive | None = None
        self.hardware_version: Version | None = None
        self.firmware_version: Version | None = None
        self.last_heating_target = DEFAULT_HEATING_TARGET
        self._reported_target: float | None = None
        self._pending_target: _Pending[float] | None = None
        self._pending_child_lock: _Pending[bool] | None = None

    @property
    def target_temperature(self) -> float | None:
        """Return the commanded target, or the last reported one."""
        if self._pending_target is not None:
            return self._pending_target.value
        return self._reported_target

    @property
    def child_lock(self) -> bool | None:
        """Return the commanded child lock state, or the last reported one."""
        if self._pending_child_lock is not None:
            return self._pending_child_lock.value
        return self.keep_alive.child_lock if self.keep_alive is not None else None

    @override
    def handle_event(self, event: DeviceEvent) -> None:
        """Apply a complete uplink, leaving old values intact on invalid data."""
        if self.closed or event.type != EventType.UPLINK:
            return
        try:
            uplink = decode_uplink(event.data)
        except VickiProtocolError as err:
            _LOGGER.debug("Ignoring uplink from %s: %s", self.descriptor.dev_eui, err)
            return

        if uplink.keep_alive is not None:
            self.keep_alive = uplink.keep_alive
            self._pending_child_lock = _settle(
                self._pending_child_lock, uplink.keep_alive.child_lock
            )
        if uplink.firmware_version is not None:
            self.hardware_version = uplink.hardware_version
            self.firmware_version = uplink.firmware_version
        if (target := uplink.target_temperature) is not None:
            self._reported_target = target
            self._pending_target = _settle(self._pending_target, target)
            if target > MIN_TARGET_TEMPERATURE:
                self.last_heating_target = target
        self.notify()

    def _check_firmware(self, minimum: Version = MIN_FIRMWARE) -> None:
        """Refuse a command the firmware is known not to support."""
        if (self.keep_alive is not None and self.keep_alive.legacy_firmware) or (
            self.firmware_version is not None and self.firmware_version < minimum
        ):
            raise CommandRejected("firmware_too_old")

    async def _async_send(self, data: bytes) -> None:
        """Queue a command for the next receive window of the device."""
        await self.async_send_downlink(
            data=data, f_port=DOWNLINK_PORT, wait_for_ack=False
        )

    async def async_set_target_temperature(self, value: float) -> None:
        """Queue a new target temperature."""
        self._check_firmware()
        value = round(value, 1)
        await self._async_send(encode_target_temperature(value))
        self._pending_target = _Pending(value)
        if value > MIN_TARGET_TEMPERATURE:
            self.last_heating_target = value
        self.notify()

    async def async_set_child_lock(self, enabled: bool) -> None:
        """Queue a new child lock state."""
        self._check_firmware()
        await self._async_send(encode_child_lock(enabled))
        self._pending_child_lock = _Pending(enabled)
        self.notify()

    async def async_request_versions(self) -> None:
        """Ask the device to report its hardware and firmware versions."""
        await self._async_send(GET_VERSIONS)


class VickiCollection(DeviceCollection[Vicki]):
    """All MClimate models supported by this integration."""

    DEVICES = (Vicki,)
