"""Test coordinator functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from pymodbus import ModbusException
import pytest

from custom_components.sax_battery.coordinator import SAXBatteryCoordinator
from custom_components.sax_battery.enums import DeviceConstants, TypeConstants
from custom_components.sax_battery.items import ModbusItem
from custom_components.sax_battery.modbusobject import ModbusAPI
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady


class TestSAXBatteryCoordinator:
    """Test SAX Battery coordinator."""

    @pytest.fixture
    def mock_hass_coord(self):
        """Create mock Home Assistant instance for coordinator tests."""
        return MagicMock(spec=HomeAssistant)

    @pytest.fixture
    def mock_config_entry_coord(self):
        """Create mock config entry for coordinator tests."""
        config_entry = MagicMock(spec=ConfigEntry)
        config_entry.data = {
            "host": "192.168.1.100",
            "port": 502,
            "batteries": {"battery_a": {"role": "master"}},
        }
        config_entry.options = {}
        return config_entry

    @pytest.fixture
    def mock_sax_data_coord(self):
        """Create mock SAX data for coordinator tests."""
        return MagicMock()

    @pytest.fixture
    def mock_modbus_api_coord(self):
        """Create mock ModbusAPI for coordinator tests."""
        api = MagicMock(spec=ModbusAPI)
        # Make API methods async to match actual implementation
        api.read_holding_registers = AsyncMock()
        api.write_registers = AsyncMock()
        return api

    @pytest.fixture
    async def sax_battery_coordinator_instance(
        self,
        mock_hass_coord,
        mock_config_entry_coord,
        mock_sax_data_coord,
        mock_modbus_api_coord,
    ):
        """Create SAXBatteryCoordinator instance."""
        coordinator = SAXBatteryCoordinator(
            hass=mock_hass_coord,
            config_entry=mock_config_entry_coord,
            sax_data=mock_sax_data_coord,
            modbus_api=mock_modbus_api_coord,
            battery_id="battery_a",
        )
        return coordinator  # noqa: RET504

    @pytest.fixture
    def smart_meter_modbus_item_coord(self, mock_modbus_api_coord):
        """Create smart meter modbus item for coordinator tests."""
        # Create item without _modbus_api in constructor, then set it
        item = ModbusItem(
            name="smartmeter_power",
            mtype=TypeConstants.SENSOR,
            device=DeviceConstants.SYS,
            address=123,
            factor=1.0,
            offset=0,
        )
        # Set the modbus API after creation
        item._modbus_api = mock_modbus_api_coord
        return item

    async def test_update_success(
        self,
        sax_battery_coordinator_instance,
        mock_sax_data_coord,
        mock_modbus_api_coord,
    ):
        """Test successful data update."""
        mock_sax_data_coord.get_smart_meter_items.return_value = []
        mock_sax_data_coord.get_modbus_items.return_value = []

        await sax_battery_coordinator_instance._async_update_data()

        # Should complete without error
        assert sax_battery_coordinator_instance.last_update_success is True

    async def test_update_smart_meter_data_success(
        self,
        sax_battery_coordinator_instance,
        mock_sax_data_coord,
        smart_meter_modbus_item_coord,
    ):
        """Test smart meter data update success."""
        mock_sax_data_coord.get_smart_meter_items.return_value = [
            smart_meter_modbus_item_coord
        ]
        smart_meter_modbus_item_coord._modbus_api.read_holding_registers.return_value = 1500

        data = {}
        await sax_battery_coordinator_instance._update_smart_meter_data(data)

        assert data["smartmeter_power"] == 1500

    async def test_update_smart_meter_data_oserror(
        self,
        sax_battery_coordinator_instance,
        mock_sax_data_coord,
        smart_meter_modbus_item_coord,
    ):
        """Test smart meter data update with OSError."""
        mock_sax_data_coord.get_smart_meter_items.return_value = [
            smart_meter_modbus_item_coord
        ]
        smart_meter_modbus_item_coord._modbus_api.read_holding_registers.side_effect = (
            OSError("Network error")
        )

        data = {}
        await sax_battery_coordinator_instance._update_smart_meter_data(data)

        # Implementation may not set None on error, just log and continue
        # Check that no exception is raised and data remains empty
        assert "smartmeter_power" not in data or data.get("smartmeter_power") is None

    async def test_update_smart_meter_data_timeout_error(
        self,
        sax_battery_coordinator_instance,
        mock_sax_data_coord,
        smart_meter_modbus_item_coord,
    ):
        """Test smart meter data update with TimeoutError."""
        mock_sax_data_coord.get_smart_meter_items.return_value = [
            smart_meter_modbus_item_coord
        ]
        smart_meter_modbus_item_coord._modbus_api.read_holding_registers.side_effect = (
            TimeoutError("Timeout")
        )

        data = {}
        await sax_battery_coordinator_instance._update_smart_meter_data(data)

        # Implementation may not set None on error, just log and continue
        # Check that no exception is raised and data remains empty
        assert "smartmeter_power" not in data or data.get("smartmeter_power") is None

    async def test_update_modbus_exception(
        self,
        sax_battery_coordinator_instance,
        mock_sax_data_coord,
        mock_modbus_api_coord,
    ):
        """Test update with ModbusException."""
        # ModbusException should be caught and logged, not raise ConfigEntryNotReady
        # Set up the exception in get_smart_meter_items
        mock_sax_data_coord.get_smart_meter_items.side_effect = ModbusException(
            "Modbus error"
        )
        mock_sax_data_coord.get_modbus_items.return_value = []

        # Should not raise ConfigEntryNotReady, just log error and continue
        try:
            await sax_battery_coordinator_instance._async_update_data()
            # Should complete without raising an exception
            assert True
        except ConfigEntryNotReady:
            pytest.fail("ModbusException should not raise ConfigEntryNotReady")

    async def test_write_switch_value_success(
        self,
        sax_battery_coordinator_instance,
        mock_modbus_api_coord,
    ):
        """Test successful switch value write."""
        # Create item without _modbus_api in constructor, then set it
        modbus_item = ModbusItem(
            name="test_switch",
            mtype=TypeConstants.SWITCH,
            device=DeviceConstants.SYS,
            address=100,
        )
        modbus_item._modbus_api = mock_modbus_api_coord
        mock_modbus_api_coord.write_registers.return_value = True

        result = await sax_battery_coordinator_instance.async_write_switch_value(
            modbus_item, True
        )

        assert result is True
        mock_modbus_api_coord.write_registers.assert_called_once()

    async def test_write_switch_value_failure(
        self,
        sax_battery_coordinator_instance,
        mock_modbus_api_coord,
    ):
        """Test switch value write failure."""
        modbus_item = ModbusItem(
            name="test_switch",
            mtype=TypeConstants.SWITCH,
            device=DeviceConstants.SYS,
            address=100,
        )
        modbus_item._modbus_api = mock_modbus_api_coord
        mock_modbus_api_coord.write_registers.return_value = False

        result = await sax_battery_coordinator_instance.async_write_switch_value(
            modbus_item, True
        )

        assert result is False

    async def test_write_number_value_success(
        self,
        sax_battery_coordinator_instance,
        mock_modbus_api_coord,
    ):
        """Test successful number value write."""
        modbus_item = ModbusItem(
            name="test_number",
            mtype=TypeConstants.NUMBER,
            device=DeviceConstants.SYS,
            address=100,
        )
        modbus_item._modbus_api = mock_modbus_api_coord
        mock_modbus_api_coord.write_registers.return_value = True

        # Use the correct method name - async_write_number_value
        result = await sax_battery_coordinator_instance.async_write_number_value(
            modbus_item, 42.0
        )

        assert result is True
        mock_modbus_api_coord.write_registers.assert_called_once()

    async def test_write_number_value_failure(
        self,
        sax_battery_coordinator_instance,
        mock_modbus_api_coord,
    ):
        """Test number value write failure."""
        modbus_item = ModbusItem(
            name="test_number",
            mtype=TypeConstants.NUMBER,
            device=DeviceConstants.SYS,
            address=100,
        )
        modbus_item._modbus_api = mock_modbus_api_coord
        mock_modbus_api_coord.write_registers.return_value = False

        # Use the correct method name - async_write_number_value
        result = await sax_battery_coordinator_instance.async_write_number_value(
            modbus_item, 42.0
        )

        assert result is False
