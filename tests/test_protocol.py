"""Test the Vicki protocol with examples from the MClimate documentation."""

import pytest

from custom_components.mclimate_lorawan.protocol import (
    REGISTER_BY_FIELD,
    REGISTERS,
    VickiProtocolError,
    build_settings_request,
    decode_uplink,
    encode_child_lock,
    encode_external_temperature,
    encode_target_temperature,
    encode_valve_openness,
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
        "54",
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
    assert encode_valve_openness(10) == bytes.fromhex("4E0A")
    assert encode_external_temperature(21.5) == bytes.fromhex("3C00D7")


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("1209", {"keep_alive_period": 9}),
        ("15051E", {"target_temperature_min": 5, "target_temperature_max": 30}),
        ("1801", {"operating_mode": "automatic"}),
        ("1F01", {"primary_mode": "cooling"}),
        ("3400", {"child_lock_offline": False}),
        ("36123456", {"pi_proportional_gain": 9.10222}),
        ("3D112233", {"pi_integral_gain": 8.5668}),
        ("400B", {"pi_run_period": 11}),
        ("4210", {"pi_hysteresis": 1.6}),
        (
            "4601020F",
            {"window_detection": True, "window_duration": 10, "window_delta": 1.5},
        ),
        (
            "4A3C5A07",
            {
                "anti_freeze_activation": 6.0,
                "anti_freeze_deactivation": 9.0,
                "anti_freeze_target": 7,
            },
        ),
        ("4D03E8", {"pi_max_integral": 100.0}),
        ("500064", {"valve_maximum": 100, "valve_minimum": 0}),
        ("5438", {"temperature_offset": 4.9}),
        ("5500", {}),
        ("5601", {"display_units": "fahrenheit"}),
        ("1B00", {"uplink_type": "unconfirmed"}),
        ("19C6", {"join_retry_period": 990}),
        ("1D020C", {"watchdog_confirmed": 2, "watchdog_unconfirmed": 12}),
        ("6200", {"setback_time": 0}),
        ("6406", {"led_duration": 3.0}),
        ("660000", {"offline_target": 0.0}),
        ("6800", {"algorithm_paused": False}),
    ],
)
def test_setting_responses(response: str, expected: dict[str, object]) -> None:
    """Decode the documented response of every setting."""
    payload = bytes.fromhex(response)
    if not expected:
        with pytest.raises(VickiProtocolError):
            decode_uplink(payload)
        return
    assert decode_uplink(payload).settings == expected


@pytest.mark.parametrize(
    ("field", "values", "command"),
    [
        ("keep_alive_period", (10,), "020A"),
        ("target_temperature_min", (16, 24), "081018"),
        ("operating_mode", ("automatic",), "0D01"),
        ("primary_mode", ("heating",), "1E00"),
        ("child_lock_offline", (True,), "3501"),
        ("pi_proportional_gain", (2.74688,), "37057E67"),
        ("pi_integral_gain", (1,), "3E020000"),
        ("pi_run_period", (15,), "410F"),
        ("pi_hysteresis", (0.3,), "4303"),
        ("window_detection", (True, 30, 1.3), "4501060D"),
        ("anti_freeze_activation", (6.0, 9.0, 7), "493C5A07"),
        ("pi_max_integral", (30.0,), "4C012C"),
        ("valve_maximum", (60, 20), "4F2850"),
        ("temperature_offset", (-5,), "5300"),
        ("temperature_offset", (0,), "531C"),
        ("temperature_offset", (2,), "5327"),
        ("temperature_offset", (5,), "5338"),
        ("display_units", ("fahrenheit",), "5501"),
        ("uplink_type", ("confirmed",), "1101"),
        ("join_retry_period", (1200,), "10F0"),
        ("watchdog_confirmed", (3, 0), "1C0300"),
        ("setback_time", (60,), "6106"),
        ("led_duration", (3,), "6306"),
        ("offline_target", (21.5,), "6500D7"),
        ("algorithm_paused", (True,), "6701"),
    ],
)
def test_setting_commands(field: str, values: tuple[object, ...], command: str) -> None:
    """Encode the documented command of every setting."""
    assert REGISTER_BY_FIELD[field].encode(*values) == bytes.fromhex(command)


@pytest.mark.parametrize(
    ("field", "values", "expected"),
    [
        ("target_temperature_min", (24, 16), "invalid_target_limits"),
        ("target_temperature_min", (16, 24), None),
        ("valve_maximum", (20, 15), "invalid_valve_limits"),
        ("valve_maximum", (60, 20), None),
        ("anti_freeze_activation", (25.0, 25.5, 8), "invalid_anti_freeze"),
        ("anti_freeze_activation", (6.0, 9.0, 7), None),
        ("offline_target", (3,), "invalid_offline_target"),
        ("offline_target", (0,), None),
        ("offline_target", (21.5,), None),
    ],
)
def test_setting_validation(
    field: str, values: tuple[float, ...], expected: str | None
) -> None:
    """Catch values the device would silently ignore."""
    check = REGISTER_BY_FIELD[field].error
    assert check is not None
    assert check(*values) == expected


def test_settings_request_fits_one_uplink() -> None:
    """Leave room for the keep-alive in the slowest uplink."""
    request = build_settings_request(REGISTERS)
    lengths = {register.get_code: register.length + 1 for register in REGISTERS}
    assert 0 < len(request) < len(REGISTERS)
    assert sum(lengths[code] for code in request) <= 42


def test_unknown_operating_mode_is_not_guessed() -> None:
    """Mode 03 needs a paired sensor and is not offered."""
    assert decode_uplink(bytes.fromhex("1803")).settings == {"operating_mode": None}
