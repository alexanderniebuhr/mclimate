"""Fixtures for MClimate devices and a LoRaWAN connection integration."""

from collections.abc import Generator
from unittest.mock import Mock

from lorawan_connection import DeviceDescriptor, UplinkEvent
from lorawan_connection.mock import MockConnection
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    MockModule,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from custom_components.mclimate_lorawan.vicki import Vicki
from homeassistant.components.lorawan import async_register_connection
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

DOMAIN = "mclimate_lorawan"

# Target 20, 22.53 degrees, 46.88 % humidity, motor 250 of 300, 3.5 V,
# child lock on and attached to the backplate.
KEEP_ALIVE = "81149c78fa2c01f0a0"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture
def stack() -> str:
    """Select the connection's device catalog."""
    return "chirpstack"


@pytest.fixture
def descriptor(stack: str) -> DeviceDescriptor:
    """Use the official Vicki identity with an arbitrary local profile ID."""
    brand_id, model_id = Vicki.identifiers[stack]
    return DeviceDescriptor(
        network_id="network",
        dev_eui="0201010101010101",
        name="Living room",
        application_id="application",
        profile_id="local-profile",
        stack=stack,
        brand_id=brand_id,
        model_id=model_id,
    )


@pytest.fixture
def mock_connection(descriptor: DeviceDescriptor, stack: str) -> MockConnection:
    """Replay devices and emit events without a server."""
    return MockConnection([descriptor], stack_type=stack)


@pytest.fixture
def connection_integration(
    hass: HomeAssistant, mock_connection: MockConnection
) -> Generator[None]:
    """Provide a connection through the shared integration's public interface."""

    async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
        entry.async_on_unload(
            await async_register_connection(hass, entry, connection=mock_connection)
        )

    async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Unload a config entry."""

    mock_integration(
        hass,
        MockModule(
            "test_connection",
            dependencies=["lorawan"],
            async_setup_entry=async_setup_entry,
            async_unload_entry=async_unload_entry,
        ),
    )
    mock_platform(hass, "test_connection.config_flow", Mock())
    with mock_config_flow("test_connection", ConfigFlow):
        yield


@pytest.fixture
def connection_entry(
    hass: HomeAssistant, connection_integration: None
) -> MockConfigEntry:
    """Create the connection integration's entry."""
    entry = MockConfigEntry(domain="test_connection", entry_id="network")
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create the single MClimate entry."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="MClimate")
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant,
    connection_entry: MockConfigEntry,
    config_entry: MockConfigEntry,
) -> None:
    """Set up the connection and the integration."""
    assert await hass.config_entries.async_setup(connection_entry.entry_id)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


def entity_id_for(
    hass: HomeAssistant, platform: str, descriptor: DeviceDescriptor, key: str
) -> str:
    """Find an entity by unique ID, independent of its translated name."""
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{descriptor.network_id}:{descriptor.dev_eui}:{key}"
    )
    assert entity_id is not None
    return entity_id


async def send_uplink(
    hass: HomeAssistant,
    connection: MockConnection,
    descriptor: DeviceDescriptor,
    payload: str = KEEP_ALIVE,
) -> None:
    """Deliver an uplink and let the background tasks it starts finish."""
    connection.emit(
        UplinkEvent(
            descriptor=descriptor,
            received_at=dt_util.utcnow(),
            data=bytes.fromhex(payload),
            f_port=2,
        )
    )
    await hass.async_block_till_done(wait_background_tasks=True)
