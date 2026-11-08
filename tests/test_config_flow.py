"""Test user setup and LoRaWAN discovery."""

from collections.abc import Generator
from unittest.mock import patch

from lorawan_connection import DeviceDescriptor, RemovedEvent
from lorawan_connection.mock import MockConnection
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.lorawan import LoRaWANDiscoveryInfo
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from .conftest import DOMAIN

SOURCES = [(SOURCE_USER, None), (SOURCE_INTEGRATION_DISCOVERY, LoRaWANDiscoveryInfo())]


@pytest.fixture(autouse=True)
def mock_discovery() -> Generator[None]:
    """Start flows explicitly instead of scheduling them during registration."""
    with patch(
        "homeassistant.components.lorawan.connection.discovery_flow.async_create_flow"
    ):
        yield


@pytest.mark.parametrize(("source", "data"), SOURCES)
@pytest.mark.parametrize("stack", ["chirpstack", "tts"])
async def test_setup(
    hass: HomeAssistant,
    source: str,
    data: LoRaWANDiscoveryInfo | None,
    connection_entry: MockConfigEntry,
) -> None:
    """Both entry points require a supported device on either backend."""
    assert await hass.config_entries.async_setup(connection_entry.entry_id)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source}, data=data
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    with patch(
        "custom_components.mclimate_lorawan.async_setup_entry", return_value=None
    ) as setup:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MClimate"
    assert result["data"] == {}
    assert result["result"].unique_id == DOMAIN
    setup.assert_called_once()


@pytest.mark.parametrize(("source", "data"), SOURCES)
@pytest.mark.usefixtures("config_entry")
async def test_already_configured(
    hass: HomeAssistant, source: str, data: LoRaWANDiscoveryInfo | None
) -> None:
    """Only one entry is needed for all connections."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source}, data=data
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


@pytest.mark.parametrize(("source", "data"), SOURCES)
async def test_no_connections(
    hass: HomeAssistant, source: str, data: LoRaWANDiscoveryInfo | None
) -> None:
    """Explain that a LoRaWAN backend must be configured first."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source}, data=data
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_lorawan_connections"


@pytest.mark.parametrize(("source", "data"), SOURCES)
async def test_no_supported_devices(
    hass: HomeAssistant,
    source: str,
    data: LoRaWANDiscoveryInfo | None,
    connection_entry: MockConfigEntry,
    mock_connection: MockConnection,
    descriptor: DeviceDescriptor,
) -> None:
    """Abort when no connection holds a Vicki."""
    mock_connection.emit(
        RemovedEvent(descriptor=descriptor, received_at=dt_util.utcnow())
    )
    assert await hass.config_entries.async_setup(connection_entry.entry_id)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source}, data=data
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_supported_devices"
