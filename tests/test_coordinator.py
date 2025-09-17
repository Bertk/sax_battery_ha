"""Test SAX Battery coordinator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pymodbus import ModbusException
from pymodbus.client.mixin import ModbusClientMixin
import pytest

from custom_components.sax_battery.const import (
    CONF_BATTERY_ENABLED,
    CONF_BATTERY_HOST,
    CONF_BATTERY_IS_MASTER,
    CONF_BATTERY_PHASE,
    CONF_BATTERY_PORT,
)
from custom_components.sax_battery.coordinator import SAXBatteryCoordinator
from custom_components.sax_battery.enums import DeviceConstants, TypeConstants
from custom_components.sax_battery.items import ModbusItem, SAXItem
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed


class TestSAXBatteryCoordinator:
    """Test SAX Battery coordinator."""

    @pytest.fixture
    def mock_hass_coord_unique(self) -> MagicMock:
        """Create mock Home Assistant instance for coordinator tests."""
        hass = MagicMock(spec=HomeAssistant)
        hass.data = {}
        return hass

    @pytest.fixture
    def mock_config_entry_coord_unique(self) -> MagicMock:
        """Create mock config entry for coordinator tests."""
        config_entry = MagicMock()
        config_entry.entry_id = "test_coord_entry_id"
        config_entry.data = {"test": "data"}
        return config_entry

    @pytest.fixture
    def mock_sax_data_coord_unique(self) -> MagicMock:
        """Create mock SAX data for coordinator tests."""
        return MagicMock()

    @pytest.fixture
    def mock_modbus_api_coord_unique(self) -> MagicMock:
        """Create mock Modbus API for coordinator tests."""
        api = MagicMock()
        # Based on actual implementation - use write_registers method
        api.write_registers = AsyncMock(return_value=True)
        api.read_holding_registers = AsyncMock()
        return api

    @pytest.fixture
    def mock_battery_config_coord(self) -> dict[str, Any]:
        """Create mock battery configuration for coordinator tests."""
        return {
            CONF_BATTERY_HOST: "192.168.1.100",
            CONF_BATTERY_PORT: 502,
            CONF_BATTERY_ENABLED: True,
            CONF_BATTERY_PHASE: "L1",
            CONF_BATTERY_IS_MASTER: True,
        }

    @pytest.fixture
    async def sax_battery_coordinator_instance_unique(
        self,
        hass: HomeAssistant,  # Use real hass from test framework
        mock_config_entry_coord_unique,
        mock_sax_data_coord_unique,
        mock_modbus_api_coord_unique,
        mock_battery_config_coord,
    ):
        """Create SAXBatteryCoordinator instance with proper HA setup."""
        # Create coordinator with actual constructor signature
        coordinator = SAXBatteryCoordinator(
            hass=hass,  # Use real hass to avoid frame helper issues
            battery_id="battery_a",
            sax_data=mock_sax_data_coord_unique,
            modbus_api=mock_modbus_api_coord_unique,
            config_entry=mock_config_entry_coord_unique,
            battery_config=mock_battery_config_coord,
        )
        return coordinator  # noqa: RET504

    @pytest.fixture
    def real_switch_item_coord_unique(self, mock_modbus_api_coord_unique) -> ModbusItem:
        """Create real ModbusItem for switch testing."""
        # Create actual ModbusItem with switch type from enums
        switch_item = ModbusItem(
            name="sax_battery_switch",
            mtype=TypeConstants.SWITCH,
            device=DeviceConstants.SYS,
            address=10,
            battery_slave_id=1,
            data_type=ModbusClientMixin.DATATYPE.UINT16,
            factor=1.0,
            offset=0,
        )
        # Set the modbus API - this is how coordinator will call it
        switch_item.modbus_api = mock_modbus_api_coord_unique
        return switch_item

    @pytest.fixture
    def real_number_item_coord_unique(self, mock_modbus_api_coord_unique) -> ModbusItem:
        """Create real ModbusItem for number testing."""
        # Create actual ModbusItem with number type from enums
        number_item = ModbusItem(
            name="sax_max_charge",
            mtype=TypeConstants.NUMBER,
            device=DeviceConstants.SYS,
            address=20,
            battery_slave_id=1,
            data_type=ModbusClientMixin.DATATYPE.UINT16,
            factor=10.0,
            offset=0,
        )
        # Set the modbus API - this is how coordinator will call it
        number_item.modbus_api = mock_modbus_api_coord_unique
        return number_item

    @pytest.fixture
    def real_sensor_item_coord_unique(self, mock_modbus_api_coord_unique) -> ModbusItem:
        """Create real ModbusItem for sensor testing."""
        # Create actual ModbusItem with sensor type from enums
        sensor_item = ModbusItem(
            name="sax_temperature",
            mtype=TypeConstants.SENSOR,
            device=DeviceConstants.SYS,
            address=30,
            battery_slave_id=1,
            data_type=ModbusClientMixin.DATATYPE.INT16,
            factor=1.0,
            offset=0,
        )
        # Set the modbus API - this is how coordinator will call it
        sensor_item.modbus_api = mock_modbus_api_coord_unique
        return sensor_item

    async def test_update_success(
        self, sax_battery_coordinator_instance_unique, mock_sax_data_coord_unique
    ) -> None:
        """Test successful data update."""
        # Mock successful data fetch
        mock_sax_data_coord_unique.get_modbus_items_for_battery.return_value = []
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = []

        # Test update
        result = await sax_battery_coordinator_instance_unique._async_update_data()

        # Verify result
        assert isinstance(result, dict)
        assert (
            sax_battery_coordinator_instance_unique.last_update_success_time is not None
        )

    async def test_write_switch_value_success(
        self,
        sax_battery_coordinator_instance_unique,
        mock_modbus_api_coord_unique,
        real_switch_item_coord_unique,
    ) -> None:
        """Test successful switch value write."""
        # Mock successful write at the ModbusAPI level - this is where it actually happens
        mock_modbus_api_coord_unique.write_registers.return_value = True

        # Test write using actual coordinator method with real ModbusItem
        result = await sax_battery_coordinator_instance_unique.async_write_switch_value(
            real_switch_item_coord_unique, True
        )

        # Verify result - should succeed with real ModbusItem
        assert result is True
        # Verify the modbus API was called through the ModbusItem
        mock_modbus_api_coord_unique.write_registers.assert_called_once()

    async def test_write_switch_value_failure(
        self,
        sax_battery_coordinator_instance_unique,
        mock_modbus_api_coord_unique,
        real_switch_item_coord_unique,
    ) -> None:
        """Test switch value write failure."""
        # Mock write failure with specific exception
        mock_modbus_api_coord_unique.write_registers.side_effect = ModbusException(
            "Write failed"
        )

        # Test write should return False on exception
        result = await sax_battery_coordinator_instance_unique.async_write_switch_value(
            real_switch_item_coord_unique, True
        )

        # Verify result
        assert result is False

    async def test_write_number_value_success(
        self,
        sax_battery_coordinator_instance_unique,
        mock_modbus_api_coord_unique,
        real_number_item_coord_unique,
    ) -> None:
        """Test successful number value write."""
        # Mock successful write at the ModbusAPI level - this is where it actually happens
        mock_modbus_api_coord_unique.write_registers.return_value = True

        # Test write using actual coordinator method with real ModbusItem
        result = await sax_battery_coordinator_instance_unique.async_write_number_value(
            real_number_item_coord_unique, 15.5
        )

        # Verify result - should succeed with real ModbusItem
        assert result is True
        # Verify the modbus API was called through the ModbusItem
        mock_modbus_api_coord_unique.write_registers.assert_called_once()

    async def test_write_number_value_failure(
        self,
        sax_battery_coordinator_instance_unique,
        mock_modbus_api_coord_unique,
        real_number_item_coord_unique,
    ) -> None:
        """Test number value write failure."""
        # Mock write failure with specific exception
        mock_modbus_api_coord_unique.write_registers.side_effect = OSError(
            "Network error"
        )

        # Test write should return False on exception
        result = await sax_battery_coordinator_instance_unique.async_write_number_value(
            real_number_item_coord_unique, 15.5
        )

        # Verify result
        assert result is False

    async def test_coordinator_properties(
        self, sax_battery_coordinator_instance_unique
    ) -> None:
        """Test coordinator properties are properly set."""
        coordinator = sax_battery_coordinator_instance_unique

        # Verify basic properties
        assert coordinator.battery_id == "battery_a"
        assert coordinator.battery_config is not None
        assert coordinator.battery_config[CONF_BATTERY_HOST] == "192.168.1.100"
        assert coordinator.battery_config[CONF_BATTERY_PORT] == 502
        assert coordinator.battery_config[CONF_BATTERY_IS_MASTER] is True

    async def test_coordinator_data_handling(
        self,
        sax_battery_coordinator_instance_unique,
        mock_sax_data_coord_unique,
        real_sensor_item_coord_unique,
        mock_modbus_api_coord_unique,
    ) -> None:
        """Test coordinator data handling with various item types."""
        # Mock successful read at the ModbusAPI level
        mock_modbus_api_coord_unique.read_holding_registers.return_value = 42.5

        # Mock the SAX data to return our real test items
        mock_sax_data_coord_unique.get_modbus_items_for_battery.return_value = [
            real_sensor_item_coord_unique
        ]
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = []

        # Test update - coordinator should call async_read_value on each item
        result = await sax_battery_coordinator_instance_unique._async_update_data()

        # Verify data structure contains the sensor data
        assert isinstance(result, dict)
        # Verify the modbus API was called through the ModbusItem
        mock_modbus_api_coord_unique.read_holding_registers.assert_called_once()
        # Check that data was stored correctly
        assert "sax_temperature" in result
        assert result["sax_temperature"] == 42.5

    async def test_update_with_modbus_exception(
        self, sax_battery_coordinator_instance_unique, mock_sax_data_coord_unique
    ) -> None:
        """Test data update with ModbusException."""
        # Mock ModbusException during data fetch
        mock_sax_data_coord_unique.get_modbus_items_for_battery.side_effect = (
            ModbusException("Modbus communication error")
        )

        # Test update should raise UpdateFailed or handle gracefully
        with pytest.raises(
            UpdateFailed, match="Error communicating with battery battery_a"
        ):
            await sax_battery_coordinator_instance_unique._async_update_data()

    async def test_coordinator_initialization(
        self,
        hass: HomeAssistant,
        mock_config_entry_coord_unique,
        mock_sax_data_coord_unique,
        mock_modbus_api_coord_unique,
        mock_battery_config_coord,
    ) -> None:
        """Test coordinator initialization with various configurations."""
        # Test master battery configuration
        master_config = dict(mock_battery_config_coord)
        master_config[CONF_BATTERY_IS_MASTER] = True

        coordinator = SAXBatteryCoordinator(
            hass=hass,
            battery_id="battery_a",
            sax_data=mock_sax_data_coord_unique,
            modbus_api=mock_modbus_api_coord_unique,
            config_entry=mock_config_entry_coord_unique,
            battery_config=master_config,
        )

        # Verify initialization
        assert coordinator.battery_id == "battery_a"
        assert coordinator.battery_config[CONF_BATTERY_IS_MASTER] is True

        # Test slave battery configuration
        slave_config = dict(mock_battery_config_coord)
        slave_config[CONF_BATTERY_IS_MASTER] = False
        slave_config[CONF_BATTERY_PHASE] = "L2"

        slave_coordinator = SAXBatteryCoordinator(
            hass=hass,
            battery_id="battery_b",
            sax_data=mock_sax_data_coord_unique,
            modbus_api=mock_modbus_api_coord_unique,
            config_entry=mock_config_entry_coord_unique,
            battery_config=slave_config,
        )

        assert slave_coordinator.battery_id == "battery_b"
        assert slave_coordinator.battery_config[CONF_BATTERY_IS_MASTER] is False
        assert slave_coordinator.battery_config[CONF_BATTERY_PHASE] == "L2"

    @patch.object(SAXItem, "calculate_value")
    async def test_sax_item_data_handling(
        self,
        mock_calculate_value,
        sax_battery_coordinator_instance_unique,
        mock_sax_data_coord_unique,
        mock_modbus_api_coord_unique,
    ) -> None:
        """Test coordinator handling of SAXItem calculated values."""
        # Configure the mock to return the desired value
        mock_calculate_value.return_value = 75.5

        # Create a real SAXItem for testing
        sax_item = SAXItem(
            name="sax_combined_soc",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
        )

        # Mock the SAX data to return our test items
        mock_sax_data_coord_unique.get_modbus_items_for_battery.return_value = []
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = [sax_item]

        # Test update
        result = await sax_battery_coordinator_instance_unique._async_update_data()

        # Verify data structure contains the calculated data
        assert isinstance(result, dict)
        assert "sax_combined_soc" in result
        assert result["sax_combined_soc"] == 75.5
        # Verify the calculate_value method was called
        mock_calculate_value.assert_called_once()

    async def test_coordinator_smart_meter_handling(
        self,
        sax_battery_coordinator_instance_unique,
        mock_sax_data_coord_unique,
        mock_modbus_api_coord_unique,
    ) -> None:
        """Test coordinator smart meter data handling for master battery."""
        # Create a real smart meter item
        smart_meter_item = ModbusItem(
            name="smartmeter_total_power",
            mtype=TypeConstants.SENSOR,
            device=DeviceConstants.SM,
            address=40,
            battery_slave_id=1,
            data_type=ModbusClientMixin.DATATYPE.INT16,
            factor=1.0,
            offset=0,
        )
        smart_meter_item.modbus_api = mock_modbus_api_coord_unique

        # Mock smart meter data return and read result
        mock_sax_data_coord_unique.get_modbus_items_for_battery.return_value = []
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = []
        mock_sax_data_coord_unique.get_smart_meter_items.return_value = [
            smart_meter_item
        ]
        mock_sax_data_coord_unique.should_poll_smart_meter.return_value = True
        mock_modbus_api_coord_unique.read_holding_registers.return_value = 1500

        # Test update
        result = await sax_battery_coordinator_instance_unique._async_update_data()

        # Verify smart meter data was processed
        assert isinstance(result, dict)
        assert "smartmeter_total_power" in result
        assert result["smartmeter_total_power"] == 1500
