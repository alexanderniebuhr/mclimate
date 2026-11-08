"""Encode and decode the MClimate Vicki LoRaWAN protocol."""

from dataclasses import dataclass
from typing import Any

DOWNLINK_PORT = 1
MIN_TARGET_TEMPERATURE = 5
MAX_TARGET_TEMPERATURE = 30
MIN_FIRMWARE = (4, 3)

GET_VERSIONS = b"\x04"

_KEEP_ALIVE_LENGTH = 9
_KEEP_ALIVE_LEGACY = 0x01
_KEEP_ALIVE_CURRENT = 0x81

_VERSIONS = 0x04
_MANUAL_TARGET = 0x28
_PRECISE_TARGET = 0x52

# Total length of each command response, including its command byte.
_RESPONSE_LENGTHS = {
    _VERSIONS: 3,
    0x12: 2,
    0x13: 5,
    0x14: 2,
    0x15: 3,
    0x16: 4,
    0x17: 3,
    0x18: 2,
    0x19: 2,
    0x1B: 2,
    0x1D: 3,
    0x1F: 2,
    0x21: 7,
    0x23: 5,
    0x27: 2,
    _MANUAL_TARGET: 2,
    0x29: 3,
    0x2B: 2,
    0x34: 2,
    0x36: 4,
    0x3D: 4,
    0x3F: 3,
    0x40: 2,
    0x42: 2,
    0x44: 3,
    0x46: 4,
    0x48: 2,
    0x4A: 4,
    0x4D: 3,
    0x50: 3,
    _PRECISE_TARGET: 3,
    0x54: 2,
}

type Version = tuple[int, int]


class VickiProtocolError(ValueError):
    """An uplink does not follow the Vicki protocol."""


@dataclass(frozen=True, slots=True, kw_only=True)
class KeepAlive:
    """Periodic device report."""

    legacy_firmware: bool
    target_temperature: int
    temperature: float
    humidity: float
    motor_position: int
    motor_range: int
    battery_voltage: float
    open_window: bool
    high_motor_consumption: bool
    low_motor_consumption: bool
    sensor_broken: bool
    child_lock: bool
    calibration_failed: bool
    attached_backplate: bool
    online: bool
    anti_freeze: bool
    battery_low: bool

    @property
    def valve_openness(self) -> int:
        """Return how far the valve is open, in percent."""
        if not self.motor_range:
            return 0
        return round((1 - self.motor_position / self.motor_range) * 100)


@dataclass(frozen=True, slots=True, kw_only=True)
class Uplink:
    """Everything a single uplink reported."""

    keep_alive: KeepAlive | None = None
    hardware_version: Version | None = None
    firmware_version: Version | None = None
    precise_target: float | None = None
    manual_target: int | None = None

    @property
    def target_temperature(self) -> float | None:
        """Return the most accurate target temperature in this uplink."""
        if self.precise_target is not None:
            return self.precise_target
        if self.keep_alive is not None:
            return float(self.keep_alive.target_temperature)
        if self.manual_target is not None:
            return float(self.manual_target)
        return None


def _decode_keep_alive(data: bytes) -> KeepAlive:
    """Decode the nine bytes of a keep-alive message."""
    legacy = data[0] == _KEEP_ALIVE_LEGACY
    temperature = data[2] * 165 / 256 - 40 if legacy else (data[2] - 28.33333) / 5.66666
    return KeepAlive(
        legacy_firmware=legacy,
        target_temperature=data[1],
        temperature=round(temperature, 2),
        humidity=round(data[3] * 100 / 256, 2),
        motor_position=(data[6] >> 4) << 8 | data[4],
        motor_range=(data[6] & 0x0F) << 8 | data[5],
        battery_voltage=round(2 + (data[7] >> 4) * 0.1, 1),
        open_window=bool(data[7] & 0x08),
        high_motor_consumption=bool(data[7] & 0x04),
        low_motor_consumption=bool(data[7] & 0x02),
        sensor_broken=bool(data[7] & 0x01),
        child_lock=bool(data[8] & 0x80),
        calibration_failed=bool(data[8] & 0x40),
        attached_backplate=bool(data[8] & 0x20),
        online=bool(data[8] & 0x10),
        anti_freeze=bool(data[8] & 0x08),
        battery_low=bool(data[8] & 0x02),
    )


def _is_keep_alive(data: bytes) -> bool:
    """Return whether data is exactly one keep-alive message."""
    return len(data) == _KEEP_ALIVE_LENGTH and data[0] in (
        _KEEP_ALIVE_LEGACY,
        _KEEP_ALIVE_CURRENT,
    )


def _decode_response(code: int, payload: bytes) -> dict[str, Any]:
    """Return the uplink fields carried by one command response."""
    if code == _VERSIONS:
        return {
            "hardware_version": (payload[0] >> 4, payload[0] & 0x0F),
            "firmware_version": (payload[1] >> 4, payload[1] & 0x0F),
        }
    if code == _MANUAL_TARGET:
        return {"manual_target": payload[0]}
    if code == _PRECISE_TARGET:
        return {"precise_target": (payload[0] << 8 | payload[1]) / 10}
    return {}


def decode_uplink(data: bytes) -> Uplink:
    """Decode command responses and the keep-alive that may follow them."""
    fields: dict[str, Any] = {}
    offset = 0
    while offset < len(data):
        if _is_keep_alive(data[offset:]):
            fields["keep_alive"] = _decode_keep_alive(data[offset:])
            return Uplink(**fields)
        code = data[offset]
        length = _RESPONSE_LENGTHS.get(code)
        if length is None or offset + length > len(data):
            # Responses from newer firmware cannot be skipped reliably, but the
            # device always appends the keep-alive after them.
            if _is_keep_alive(tail := data[-_KEEP_ALIVE_LENGTH:]):
                return Uplink(keep_alive=_decode_keep_alive(tail))
            raise VickiProtocolError(f"Cannot decode uplink {data.hex()}")
        fields |= _decode_response(code, data[offset + 1 : offset + length])
        offset += length
    if not fields:
        raise VickiProtocolError(f"Uplink {data.hex()} has no usable data")
    return Uplink(**fields)


def encode_target_temperature(value: float) -> bytes:
    """Encode a target temperature with 0.1 degree resolution."""
    tenths = round(value * 10)
    return bytes((0x51, tenths >> 8, tenths & 0xFF))


def encode_child_lock(enabled: bool) -> bytes:
    """Encode the child lock state."""
    return bytes((0x07, int(enabled)))
