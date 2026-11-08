"""Device model for the MClimate Vicki thermostat."""

from dataclasses import dataclass
import logging
from typing import Any, override

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
    REGISTER_BY_FIELD,
    REGISTERS,
    RESTART,
    KeepAlive,
    Version,
    VickiProtocolError,
    build_settings_request,
    decode_uplink,
    encode_child_lock,
    encode_external_temperature,
    encode_target_temperature,
    encode_valve_openness,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_HEATING_TARGET = 20.0

# A Class A downlink is delivered after the next uplink, so that uplink still
# reports the old state and only the one after it can show the result.
_PENDING_UPLINKS = 2

# The documentation warns that smaller motor movements make the device misbehave.
_MIN_MOTOR_STEPS = 17

_MAX_REQUEST_WAIT = 24


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
        self.settings: dict[str, Any] = {}
        self._request_wait = 0
        self._request_attempts = 0
        self._pending_valve: _Pending[int] | None = None
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

    @property
    def valve_openness(self) -> int | None:
        """Return the commanded valve position, or the last reported one."""
        if self._pending_valve is not None:
            return self._pending_valve.value
        return self.keep_alive.valve_openness if self.keep_alive is not None else None

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
            self._pending_valve = _settle(
                self._pending_valve, uplink.keep_alive.valve_openness
            )
        if uplink.firmware_version is not None:
            self.hardware_version = uplink.hardware_version
            self.firmware_version = uplink.firmware_version
            self._request_progressed()
        if uplink.settings:
            self.settings.update(uplink.settings)
            self._request_progressed()
        if uplink.manual_target is not None:
            self._resume_algorithm()
        if (target := uplink.target_temperature) is not None:
            self._reported_target = target
            self._pending_target = _settle(self._pending_target, target)
            if target > MIN_TARGET_TEMPERATURE:
                self.last_heating_target = target
        self.notify()

    def _request_progressed(self) -> None:
        """Ask for the next batch as soon as the device has answered."""
        self._request_wait = 0
        self._request_attempts = 0

    def _resume_algorithm(self) -> None:
        """Record that a new target ended a temporary algorithm pause."""
        if "algorithm_paused" in self.settings:
            self.settings["algorithm_paused"] = False

    def _check_firmware(self) -> None:
        """Refuse commands on firmware known to be unsupported."""
        if (self.keep_alive is not None and self.keep_alive.legacy_firmware) or (
            self.firmware_version is not None and self.firmware_version < MIN_FIRMWARE
        ):
            raise CommandRejected("firmware_too_old")

    def _build_state_request(self) -> bytes | None:
        """Return the next batch of questions for the device, if any are left."""
        if self.keep_alive is None or self.keep_alive.legacy_firmware:
            return None
        if self.firmware_version is None:
            return GET_VERSIONS
        if self.firmware_version < MIN_FIRMWARE:
            return None
        missing = [
            register
            for register in REGISTERS
            if register.fields[0] not in self.settings
        ]
        return build_settings_request(missing) if missing else None

    def next_state_request(self) -> bytes | None:
        """Pace the questions, called once for each keep-alive.

        A request reaches the device after the next uplink and is answered in
        the one after that, so sending on every uplink would only duplicate it.
        """
        if self._request_wait:
            self._request_wait -= 1
            return None
        if (request := self._build_state_request()) is None:
            return None
        self._request_attempts += 1
        self._request_wait = min(2**self._request_attempts, _MAX_REQUEST_WAIT)
        return request

    def state_request_failed(self) -> None:
        """Retry on the next uplink when the server rejected a request."""
        self._request_progressed()

    async def async_send_state_request(self, request: bytes) -> None:
        """Queue questions for the device."""
        await self._async_send(request)

    async def _async_send(self, data: bytes) -> None:
        """Queue a command for the next receive window of the device."""
        await self.async_send_downlink(
            data=data, f_port=DOWNLINK_PORT, wait_for_ack=False
        )

    async def async_set_target_temperature(self, value: float) -> None:
        """Queue a new target temperature."""
        self._check_firmware()
        if self.settings.get("operating_mode") == "manual":
            raise CommandRejected("requires_automatic_mode")
        value = round(value, 1)
        await self._async_send(encode_target_temperature(value))
        self._resume_algorithm()
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

    async def async_set_setting(self, key: str, value: Any) -> None:
        """Queue a setting and ask the device to report what it applied."""
        register = REGISTER_BY_FIELD[key]
        self._check_firmware()
        values = [
            value if name == key else self.settings.get(name)
            for name in register.fields
        ]
        if None in values:
            raise CommandRejected("setting_not_loaded")
        if register.error is not None and (reason := register.error(*values)):
            raise CommandRejected(reason)
        await self._async_send(register.encode(*values) + bytes((register.get_code,)))
        self.settings[key] = value
        self.notify()

    async def async_set_valve_openness(self, percent: int) -> None:
        """Queue a valve position, which only applies in manual mode."""
        self._check_firmware()
        if self.settings.get("operating_mode") != "manual":
            raise CommandRejected("requires_manual_mode")
        current = self.valve_openness
        if (
            current is not None
            and self.keep_alive is not None
            and abs(percent - current) * self.keep_alive.motor_range / 100
            < _MIN_MOTOR_STEPS
        ):
            raise CommandRejected("valve_change_too_small")
        await self._async_send(encode_valve_openness(percent))
        self._pending_valve = _Pending(percent)
        self.notify()

    async def async_set_external_temperature(self, value: float) -> None:
        """Queue the room temperature used by the external sensor mode."""
        self._check_firmware()
        await self._async_send(encode_external_temperature(value))

    async def async_refresh_operating_mode(self) -> None:
        """Ask the device which operating mode it is in."""
        await self._async_send(
            bytes((REGISTER_BY_FIELD["operating_mode"].get_code,))
        )

    async def async_restart(self) -> None:
        """Queue a device restart, which also recalibrates the motor."""
        self._check_firmware()
        await self._async_send(RESTART)


class VickiCollection(DeviceCollection[Vicki]):
    """All MClimate models supported by this integration."""

    DEVICES = (Vicki,)
