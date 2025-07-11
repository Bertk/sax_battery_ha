"""Test config flow for SAX Battery integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sax_battery.const import DOMAIN
from custom_components.sax_battery.enums import (
    DeviceConstants,
    FormatConstants,
    TypeConstants,
)
from custom_components.sax_battery.items import ModbusItem, SAXItem
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component


@pytest.fixture
def mock_modbus_api():
    """Create a mock ModbusAPI."""
    api = MagicMock()
    api.async_write_holding_register = MagicMock(return_value=True)
    api.read_holding_registers = MagicMock(return_value=[42])
    return api


@pytest.fixture
def sample_modbus_item():
    """Create a sample ModbusItem for testing."""
    return ModbusItem(
        slave=1,
        address=100,
        name="test_sensor",
        mformat=FormatConstants.NUMBER,
        mtype=TypeConstants.SENSOR,
        device=DeviceConstants.SYS,
    )


@pytest.fixture
def sample_sax_item():
    """Create a sample SAXItem for testing."""
    return SAXItem(
        name="test_pilot",
        mformat=FormatConstants.STATUS,
        mtype=TypeConstants.SWITCH,
        device=DeviceConstants.SYS,
    )


@pytest.fixture
async def hass_with_sax(hass: HomeAssistant, mock_sax_data):
    """Set up Home Assistant with SAX Battery integration."""
    hass.data[DOMAIN] = {"test_entry": mock_sax_data}

    with patch("custom_components.sax_battery.async_setup_entry", return_value=True):
        assert await async_setup_component(hass, DOMAIN, {})

    return hass


class TestSAXBatteryConfigFlow:
    """Test config flow."""

    async def test_form_user_success(
        self,
        hass: HomeAssistant,
        mock_modbus_client,
        mock_setup_entry,
    ) -> None:
        """Test successful user configuration."""
        with patch(
            "custom_components.sax_battery.config_flow.ModbusAPI",
            return_value=mock_modbus_client,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            assert result.get("type") == FlowResultType.FORM
            assert result.get("errors") == {}

            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "host": "192.168.1.100",
                    "port": 502,
                    "slave_id": 64,
                    "battery_id": "battery_a",
                },
            )
            await hass.async_block_till_done()

            assert result2.get("type") == FlowResultType.CREATE_ENTRY
            assert result2.get("title") == "SAX Battery (battery_a)"
            assert result2.get("data") == {
                "host": "192.168.1.100",
                "port": 502,
                "slave_id": 64,
                "battery_id": "battery_a",
            }

    async def test_form_user_connection_error(
        self,
        hass: HomeAssistant,
        mock_modbus_client,
    ) -> None:
        """Test connection error during configuration."""
        mock_modbus_client.connect.return_value = False

        with patch(
            "custom_components.sax_battery.config_flow.ModbusAPI",
            return_value=mock_modbus_client,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "host": "192.168.1.100",
                    "port": 502,
                    "slave_id": 64,
                    "battery_id": "battery_a",
                },
            )

            assert result2.get("type") == FlowResultType.FORM
            assert result2.get("errors") == {"base": "cannot_connect"}

    async def test_form_user_invalid_host(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test invalid host format."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "invalid_host_format",
                "port": 502,
                "slave_id": 64,
                "battery_id": "battery_a",
            },
        )

        assert result2.get("type") == FlowResultType.FORM
        assert result2.get("errors") == {"host": "invalid_host"}

    async def test_form_user_duplicate_battery_id(
        self,
        hass: HomeAssistant,
        mock_modbus_client,
    ) -> None:
        """Test duplicate battery ID error."""
        # Create existing entry
        existing_entry = MockConfigEntry(
            domain=DOMAIN,
            data={"battery_id": "battery_a"},
            unique_id="battery_a",
        )
        existing_entry.add_to_hass(hass)

        with patch(
            "custom_components.sax_battery.config_flow.ModbusAPI",
            return_value=mock_modbus_client,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "host": "192.168.1.101",
                    "port": 502,
                    "slave_id": 65,
                    "battery_id": "battery_a",  # Duplicate ID
                },
            )

            assert result2.get("type") == FlowResultType.FORM
            assert result2.get("errors") == {"battery_id": "already_configured"}

    async def test_options_flow(
        self,
        hass: HomeAssistant,
        mock_modbus_client,
    ) -> None:
        """Test options flow."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                "host": "192.168.1.100",
                "port": 502,
                "slave_id": 64,
                "battery_id": "battery_a",
            },
            options={
                "scan_interval": 10,
                "pilot_enabled": True,
            },
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result.get("type") == FlowResultType.FORM
        assert result.get("step_id") == "init"

        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "scan_interval": 15,
                "pilot_enabled": False,
            },
        )

        assert result2.get("type") == FlowResultType.CREATE_ENTRY
        assert result2.get("data") == {
            "scan_interval": 15,
            "pilot_enabled": False,
        }
