"""Encode and decode the MClimate Vicki LoRaWAN protocol."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

DOWNLINK_PORT = 1
MIN_TARGET_TEMPERATURE = 5
MAX_TARGET_TEMPERATURE = 30
MIN_FIRMWARE = (5, 0)

GET_VERSIONS = b"\x04"
RESTART = b"\x30"

_KEEP_ALIVE_LENGTH = 9
_KEEP_ALIVE_LEGACY = 0x01
_KEEP_ALIVE_CURRENT = 0x81

_VERSIONS = 0x04
_MANUAL_TARGET = 0x28
_PRECISE_TARGET = 0x52

_GAIN_SCALE = 131072
_OFFSET_STEP = 0.176

# An uplink at the slowest data rate has room for 51 bytes, and the keep-alive
# that follows the responses needs nine of them.
_MAX_RESPONSE_BYTES = 42

OPERATING_MODES = ("manual", "automatic", "automatic_external")
PRIMARY_MODES = ("heating", "cooling")
DISPLAY_UNITS = ("celsius", "fahrenheit", "scale")
UPLINK_TYPES = ("unconfirmed", "confirmed")

type Version = tuple[int, int]


class VickiProtocolError(ValueError):
    """An uplink does not follow the Vicki protocol."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Register:
    """Settings the device reads and writes together.

    A rejected setting is ignored by the device without a response, so error
    returns the translation key of a problem before anything is sent.
    """

    fields: tuple[str, ...]
    get_code: int
    length: int
    decode: Callable[[bytes], tuple[Any, ...]]
    encode: Callable[..., bytes]
    error: Callable[..., str | None] | None = None


def _number(
    name: str,
    get_code: int,
    set_code: int,
    *,
    scale: float = 1,
    error: Callable[..., str | None] | None = None,
) -> Register:
    """Describe a setting stored as one byte, where value = byte * scale."""
    return Register(
        fields=(name,),
        get_code=get_code,
        length=1,
        decode=lambda data: (round(data[0] * scale, 1),),
        encode=lambda value: bytes((set_code, round(value / scale))),
        error=error,
    )


def _option(name: str, get_code: int, set_code: int, options: tuple[str, ...]) -> Register:
    """Describe a setting that selects one of the options by index."""
    return Register(
        fields=(name,),
        get_code=get_code,
        length=1,
        decode=lambda data: (options[data[0]] if data[0] < len(options) else None,),
        encode=lambda value: bytes((set_code, options.index(value))),
    )


def _switch(name: str, get_code: int, set_code: int) -> Register:
    """Describe a setting that is on or off."""
    return Register(
        fields=(name,),
        get_code=get_code,
        length=1,
        decode=lambda data: (bool(data[0]),),
        encode=lambda value: bytes((set_code, int(value))),
    )


def _gain(name: str, get_code: int, set_code: int) -> Register:
    """Describe a PI gain stored in 24 bits."""
    return Register(
        fields=(name,),
        get_code=get_code,
        length=3,
        decode=lambda data: (round(int.from_bytes(data) / _GAIN_SCALE, 5),),
        encode=lambda value: bytes((set_code,))
        + round(value * _GAIN_SCALE).to_bytes(3),
    )


def _target_limits_error(minimum: float, maximum: float) -> str | None:
    """Require a usable range on the rotary ring."""
    return None if minimum < maximum else "invalid_target_limits"


def _valve_limits_error(maximum: float, minimum: float) -> str | None:
    """Require the 10 percent span the device insists on."""
    return None if maximum - minimum >= 10 else "invalid_valve_limits"


def _anti_freeze_error(
    activation: float, deactivation: float, target: float
) -> str | None:
    """Require the thresholds to surround the anti-freeze target."""
    return None if activation < target < deactivation else "invalid_anti_freeze"


def _offline_target_error(value: float) -> str | None:
    """Allow zero, which disables the feature, or a real target."""
    if value == 0 or MIN_TARGET_TEMPERATURE <= value <= MAX_TARGET_TEMPERATURE:
        return None
    return "invalid_offline_target"


REGISTERS = (
    _number("keep_alive_period", 0x12, 0x02),
    Register(
        fields=("target_temperature_min", "target_temperature_max"),
        get_code=0x15,
        length=2,
        decode=lambda data: (data[0], data[1]),
        encode=lambda minimum, maximum: bytes((0x08, round(minimum), round(maximum))),
        error=_target_limits_error,
    ),
    _option("operating_mode", 0x18, 0x0D, OPERATING_MODES),
    _option("primary_mode", 0x1F, 0x1E, PRIMARY_MODES),
    _switch("child_lock_offline", 0x34, 0x35),
    _gain("pi_proportional_gain", 0x36, 0x37),
    _gain("pi_integral_gain", 0x3D, 0x3E),
    _number("pi_run_period", 0x40, 0x41),
    _number("pi_hysteresis", 0x42, 0x43, scale=0.1),
    Register(
        fields=("window_detection", "window_duration", "window_delta"),
        get_code=0x46,
        length=3,
        decode=lambda data: (bool(data[0] & 1), data[1] * 5, round(data[2] / 10, 1)),
        encode=lambda enabled, duration, delta: bytes(
            (0x45, int(enabled), round(duration / 5), round(delta * 10))
        ),
    ),
    Register(
        fields=(
            "anti_freeze_activation",
            "anti_freeze_deactivation",
            "anti_freeze_target",
        ),
        get_code=0x4A,
        length=3,
        decode=lambda data: (round(data[0] / 10, 1), round(data[1] / 10, 1), data[2]),
        encode=lambda activation, deactivation, target: bytes(
            (0x49, round(activation * 10), round(deactivation * 10), round(target))
        ),
        error=_anti_freeze_error,
    ),
    Register(
        fields=("pi_max_integral",),
        get_code=0x4D,
        length=2,
        decode=lambda data: (round(int.from_bytes(data) / 10, 1),),
        encode=lambda value: bytes((0x4C,)) + round(value * 10).to_bytes(2),
    ),
    Register(
        fields=("valve_maximum", "valve_minimum"),
        get_code=0x50,
        length=2,
        decode=lambda data: (100 - data[0], 100 - data[1]),
        encode=lambda maximum, minimum: bytes(
            (0x4F, 100 - round(maximum), 100 - round(minimum))
        ),
        error=_valve_limits_error,
    ),
    Register(
        fields=("temperature_offset",),
        get_code=0x54,
        length=1,
        decode=lambda data: (round((data[0] - 28) * _OFFSET_STEP, 1),),
        encode=lambda value: bytes(
            (0x53, max(0, min(56, round(value / _OFFSET_STEP) + 28)))
        ),
    ),
    _option("display_units", 0x56, 0x55, DISPLAY_UNITS),
    _option("uplink_type", 0x1B, 0x11, UPLINK_TYPES),
    _number("join_retry_period", 0x19, 0x10, scale=5),
    Register(
        fields=("watchdog_confirmed", "watchdog_unconfirmed"),
        get_code=0x1D,
        length=2,
        decode=lambda data: (data[0], data[1]),
        encode=lambda confirmed, unconfirmed: bytes(
            (0x1C, round(confirmed), round(unconfirmed))
        ),
    ),
    _number("setback_time", 0x62, 0x61, scale=10),
    _number("led_duration", 0x64, 0x63, scale=0.5),
    Register(
        fields=("offline_target",),
        get_code=0x66,
        length=2,
        decode=lambda data: (round(int.from_bytes(data) / 10, 1),),
        encode=lambda value: bytes((0x65,)) + round(value * 10).to_bytes(2),
        error=_offline_target_error,
    ),
    _switch("algorithm_paused", 0x68, 0x67),
)

REGISTER_BY_FIELD = {name: reg for reg in REGISTERS for name in reg.fields}
_REGISTER_BY_CODE = {reg.get_code: reg for reg in REGISTERS}

# Total length of each response the integration only has to skip, including its
# command byte.
_SKIPPED_RESPONSE_LENGTHS = {
    0x13: 5,
    0x14: 2,
    0x16: 4,
    0x17: 3,
    0x21: 7,
    0x23: 5,
    0x27: 2,
    0x29: 3,
    0x2B: 2,
    0x3F: 3,
    0x44: 3,
    0x48: 2,
    0x58: 3,
    0x6A: 13,
    0xA4: 2,
}
_RESPONSE_LENGTHS = {
    _VERSIONS: 3,
    _MANUAL_TARGET: 2,
    _PRECISE_TARGET: 3,
    **_SKIPPED_RESPONSE_LENGTHS,
    **{code: reg.length + 1 for code, reg in _REGISTER_BY_CODE.items()},
}

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
    settings: Mapping[str, Any] = field(default_factory=dict)

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


def _merge_response(fields: dict[str, Any], code: int, payload: bytes) -> None:
    """Add what one command response reports to the uplink fields."""
    if code == _VERSIONS:
        fields["hardware_version"] = (payload[0] >> 4, payload[0] & 0x0F)
        fields["firmware_version"] = (payload[1] >> 4, payload[1] & 0x0F)
    elif code == _MANUAL_TARGET:
        fields["manual_target"] = payload[0]
    elif code == _PRECISE_TARGET:
        fields["precise_target"] = (payload[0] << 8 | payload[1]) / 10
    elif (register := _REGISTER_BY_CODE.get(code)) is not None:
        fields.setdefault("settings", {}).update(
            zip(register.fields, register.decode(payload), strict=True)
        )


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
        _merge_response(fields, code, data[offset + 1 : offset + length])
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


def encode_valve_openness(percent: int) -> bytes:
    """Encode a valve position in percent."""
    return bytes((0x4E, percent))


def encode_external_temperature(value: float) -> bytes:
    """Encode a room temperature measured outside the device."""
    return bytes((0x3C,)) + round(value * 10).to_bytes(2)


def build_settings_request(registers: Iterable[Register]) -> bytes:
    """Ask for as many settings as fit into one uplink response."""
    codes = bytearray()
    size = 0
    for register in registers:
        size += register.length + 1
        if size > _MAX_RESPONSE_BYTES:
            break
        codes.append(register.get_code)
    return bytes(codes)
