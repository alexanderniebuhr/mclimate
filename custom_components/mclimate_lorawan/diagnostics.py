"""Diagnostics for MClimate devices."""

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import MClimateConfigEntry
from .vicki import Vicki

TO_REDACT = {"application_id", "dev_eui", "name", "network_id", "profile_id"}


def _device_diagnostics(device: Vicki) -> dict[str, Any]:
    """Return what the integration knows about one device."""
    return {
        "descriptor": async_redact_data(asdict(device.descriptor), TO_REDACT),
        "keep_alive": asdict(device.keep_alive) if device.keep_alive else None,
        "hardware_version": device.hardware_version,
        "firmware_version": device.firmware_version,
        "target_temperature": device.target_temperature,
        "child_lock": device.child_lock,
        "settings": device.settings,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MClimateConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for all devices."""
    return {
        "devices": [
            _device_diagnostics(coordinator.data)
            for coordinator in entry.runtime_data.coordinators.values()
        ]
    }
