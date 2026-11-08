"""Test discovery through the custom manifest."""

import json
from pathlib import Path

from pytest_homeassistant.common import MockConfigEntry

import custom_components.mclimate_lorawan as integration
from custom_components.mclimate_lorawan.vicki import Vicki
from homeassistant.core import HomeAssistant

from .conftest import DOMAIN


def test_manifest_matches_device_identity() -> None:
    """Discovery must cover every catalog the model can be matched in."""
    manifest = json.loads(
        (Path(integration.__file__).parent / "manifest.json").read_text()
    )
    assert sorted(map(tuple, manifest["lorawan"]), key=str) == sorted(
        ((stack, brand) for stack, (brand, _) in Vicki.identifiers.items()), key=str
    )


async def test_discovered_when_connection_registers(
    hass: HomeAssistant, connection_entry: MockConfigEntry
) -> None:
    """A connection holding a Vicki starts a config flow."""
    await hass.async_start()
    assert await hass.config_entries.async_setup(connection_entry.entry_id)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["step_id"] == "confirm"
