"""Test the Vicki protocol with examples from the MClimate documentation."""

import pytest

from custom_components.mclimate_lorawan.protocol import (
    VickiProtocolError,
    decode_uplink,
    encode_child_lock,
    encode_target_temperature,
)


def test_keep_alive_legacy_child_lock_on() -> None:
    """Decode the documented keep-alive with the child lock enabled."""
    keep_alive = decode_uplink(bytes.fromhex("011D5A78FA2C01F080")).keep_alive
    assert keep_alive is not None
    assert keep_alive.legacy_firmware
    assert keep_alive.target_temperature == 29
    assert keep_alive.temperature == 18.01
    assert keep_alive.humidity == 46.88
    assert keep_alive.motor_position == 250
    assert keep_alive.motor_range == 300
    assert keep_alive.battery_voltage == 3.5
    assert keep_alive.child_lock


def test_keep_alive_legacy_child_lock_off() -> None:
    """Decode the documented keep-alive with the child lock disabled."""
    keep_alive = decode_uplink(bytes.fromhex("01185C5CDFDF118000")).keep_alive
    assert keep_alive is not None
    assert keep_alive.target_temperature == 24
    assert keep_alive.temperature == 19.3
    assert keep_alive.humidity == 35.94
    assert keep_alive.motor_position == 479
    assert keep_alive.motor_range == 479
    assert keep_alive.battery_voltage == 2.8
    assert not keep_alive.child_lock


def test_keep_alive_current_formula() -> None:
    """Use the temperature formula of firmware 3.5 and later."""
    keep_alive = decode_uplink(bytes.fromhex("81149c78fa2c01f0a0")).keep_alive
    assert keep_alive is not None
    assert not keep_alive.legacy_firmware
    assert keep_alive.temperature == 22.53
    assert keep_alive.attached_backplate
    assert keep_alive.valve_openness == 17


@pytest.mark.parametrize(
    ("byte7", "field"),
    [
        (0x08, "open_window"),
        (0x04, "high_motor_consumption"),
        (0x02, "low_motor_consumption"),
        (0x01, "sensor_broken"),
    ],
)
def test_keep_alive_motor_flags(byte7: int, field: str) -> None:
    """Map each flag of byte 7."""
    payload = bytes((0x81, 20, 150, 120, 0, 0, 0, byte7, 0))
    keep_alive = decode_uplink(payload).keep_alive
    assert getattr(keep_alive, field)


@pytest.mark.parametrize(
    ("byte8", "field"),
    [
        (0x80, "child_lock"),
        (0x40, "calibration_failed"),
        (0x20, "attached_backplate"),
        (0x10, "online"),
        (0x08, "anti_freeze"),
        (0x02, "battery_low"),
    ],
)
def test_keep_alive_status_flags(byte8: int, field: str) -> None:
    """Map each flag of byte 8."""
    payload = bytes((0x81, 20, 150, 120, 0, 0, 0, 0, byte8))
    keep_alive = decode_uplink(payload).keep_alive
    assert getattr(keep_alive, field)


def test_zero_motor_range() -> None:
    """Report a closed valve before the motor has been calibrated."""
    keep_alive = decode_uplink(bytes((0x81, 20, 150, 120, 0, 0, 0, 0, 0))).keep_alive
    assert keep_alive is not None
    assert keep_alive.valve_openness == 0


def test_version_response_before_keep_alive() -> None:
    """Decode the documented version response followed by a keep-alive."""
    uplink = decode_uplink(bytes.fromhex("042321011D5A78FA2C01F080"))
    assert uplink.hardware_version == (2, 3)
    assert uplink.firmware_version == (2, 1)
    assert uplink.keep_alive is not None
    assert uplink.keep_alive.target_temperature == 29


def test_multiple_responses_before_keep_alive() -> None:
    """Skip the responses the integration does not use."""
    uplink = decode_uplink(bytes.fromhex("120B150F1A1801011863530000008000"))
    assert uplink.keep_alive is not None
    assert uplink.keep_alive.target_temperature == 24
    assert uplink.keep_alive.temperature == 23.81
    assert uplink.keep_alive.humidity == 32.42
    assert uplink.keep_alive.battery_voltage == 2.8


def test_precise_target_overrides_keep_alive() -> None:
    """Prefer the 0.1 degree target that accompanies a rounded keep-alive."""
    uplink = decode_uplink(bytes.fromhex("520102011D5A78FA2C01F080"))
    assert uplink.precise_target == 25.8
    assert uplink.target_temperature == 25.8


def test_manual_target_without_keep_alive() -> None:
    """Report a manual change when the keep-alive did not fit."""
    uplink = decode_uplink(bytes.fromhex("2816"))
    assert uplink.keep_alive is None
    assert uplink.target_temperature == 22.0


def test_keep_alive_target_beats_manual_change() -> None:
    """Use the current target of the keep-alive."""
    uplink = decode_uplink(bytes.fromhex("2816011D5A78FA2C01F080"))
    assert uplink.target_temperature == 29.0


def test_unknown_response_falls_back_to_keep_alive() -> None:
    """Keep the measurements when newer firmware adds unknown responses."""
    uplink = decode_uplink(bytes.fromhex("A601011D5A78FA2C01F080"))
    assert uplink.keep_alive is not None
    assert uplink.keep_alive.target_temperature == 29
    assert uplink.firmware_version is None


def test_no_target_in_uplink() -> None:
    """Report no target for responses that do not carry one."""
    assert decode_uplink(bytes.fromhex("042321")).target_temperature is None


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "01",
        "011D5A78FA2C01F0",
        "A6",
        "0423",
        "12",
        "1209",
    ],
)
def test_invalid_uplink(payload: str) -> None:
    """Reject truncated, unknown and empty payloads."""
    with pytest.raises(VickiProtocolError):
        decode_uplink(bytes.fromhex(payload))


def test_encoders() -> None:
    """Match the documented downlink examples."""
    assert encode_target_temperature(25.8) == bytes.fromhex("510102")
    assert encode_child_lock(True) == bytes.fromhex("0701")
    assert encode_child_lock(False) == bytes.fromhex("0700")
