"""Test SAX Battery coordinator."""

from __future__ import annotations

from datetime import datetime
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

    # @pytest.fixture
    # def mock_modbus_api_coord_unique(self) -> MagicMock:
    #     """Create mock Modbus API for coordinator tests."""
    #     api = MagicMock()
    #     # Based on actual implementation - use write_registers method
    #     api.write_registers = AsyncMock(return_value=True)
    #     api.read_holding_registers = AsyncMock()
    #     return api

    @pytest.fixture
    def mock_modbus_api_coord_unique_fixed(self) -> MagicMock:
        """Create properly mocked Modbus API for coordinator tests with async support."""
        api = MagicMock()
        # Mock async methods properly
        api.connect = AsyncMock(return_value=True)
        api.reconnect_on_error = AsyncMock(return_value=True)
        api.should_force_reconnect = MagicMock(
            return_value=False
        )  # Default to healthy connection
        api.close = MagicMock()
        api.connection_health = {"health_status": "good"}

        # Mock read/write methods
        api.read_holding_registers = AsyncMock()
        api.write_registers = AsyncMock(return_value=True)
        api.write_nominal_power = AsyncMock(return_value=True)
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

    # @pytest.fixture
    # async def sax_battery_coordinator_instance_unique(
    #     self,
    #     hass: HomeAssistant,  # Use real hass from test framework
    #     mock_config_entry_coord_unique,
    #     mock_sax_data_coord_unique,
    #     mock_modbus_api_coord_unique,
    #     mock_battery_config_coord,
    # ):
    #     """Create SAXBatteryCoordinator instance with proper HA setup."""
    #     # Create coordinator with actual constructor signature
    #     coordinator = SAXBatteryCoordinator(
    #         hass=hass,  # Use real hass to avoid frame helper issues
    #         battery_id="battery_a",
    #         sax_data=mock_sax_data_coord_unique,
    #         modbus_api=mock_modbus_api_coord_unique,
    #         config_entry=mock_config_entry_coord_unique,
    #         battery_config=mock_battery_config_coord,
    #     )
    #     return coordinator

    @pytest.fixture
    async def sax_battery_coordinator_instance_fixed(
        self,
        hass: HomeAssistant,
        mock_config_entry_coord_unique,
        mock_sax_data_coord_unique,
        mock_modbus_api_coord_unique_fixed,
        mock_battery_config_coord,
    ):
        """Create SAXBatteryCoordinator instance with properly mocked async methods."""
        coordinator = SAXBatteryCoordinator(
            hass=hass,
            battery_id="battery_a",
            sax_data=mock_sax_data_coord_unique,
            modbus_api=mock_modbus_api_coord_unique_fixed,
            config_entry=mock_config_entry_coord_unique,
            battery_config=mock_battery_config_coord,
        )
        return coordinator  # noqa: RET504

    @pytest.fixture
    def real_switch_item_coord_unique(
        self, mock_modbus_api_coord_unique_fixed
    ) -> ModbusItem:
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
        switch_item.modbus_api = mock_modbus_api_coord_unique_fixed
        return switch_item

    @pytest.fixture
    def real_number_item_coord_unique(
        self, mock_modbus_api_coord_unique_fixed
    ) -> ModbusItem:
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
        number_item.modbus_api = mock_modbus_api_coord_unique_fixed
        return number_item

    @pytest.fixture
    def real_sensor_item_coord_unique(
        self, mock_modbus_api_coord_unique_fixed
    ) -> ModbusItem:
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
        sensor_item.modbus_api = mock_modbus_api_coord_unique_fixed
        return sensor_item

    async def test_update_success(
        self, sax_battery_coordinator_instance_fixed, mock_sax_data_coord_unique
    ) -> None:
        """Test successful data update with fixed async mocking."""
        # Mock successful data fetch
        mock_sax_data_coord_unique.get_modbus_items_for_battery.return_value = []
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = []

        # Test update
        result = await sax_battery_coordinator_instance_fixed._async_update_data()

        # Verify result
        assert isinstance(result, dict)
        # Security: Verify timestamp is set after successful update
        assert (
            sax_battery_coordinator_instance_fixed.last_update_success_time is not None
        )
        assert isinstance(
            sax_battery_coordinator_instance_fixed.last_update_success_time, datetime
        )

    async def test_write_switch_value_success(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_modbus_api_coord_unique_fixed,
        real_switch_item_coord_unique,
    ) -> None:
        """Test successful switch value write."""
        # Mock successful write at the ModbusAPI level - this is where it actually happens
        mock_modbus_api_coord_unique_fixed.write_registers.return_value = True

        # Test write using actual coordinator method with real ModbusItem
        result = await sax_battery_coordinator_instance_fixed.async_write_switch_value(
            real_switch_item_coord_unique, True
        )

        # Verify result - should succeed with real ModbusItem
        assert result is True
        # Verify the modbus API was called through the ModbusItem
        mock_modbus_api_coord_unique_fixed.write_registers.assert_called_once()

    async def test_write_switch_value_failure(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_modbus_api_coord_unique_fixed,
        real_switch_item_coord_unique,
    ) -> None:
        """Test switch value write failure."""
        # Mock write failure with specific exception
        mock_modbus_api_coord_unique_fixed.write_registers.side_effect = (
            ModbusException("Write failed")
        )

        # Test write should return False on exception
        result = await sax_battery_coordinator_instance_fixed.async_write_switch_value(
            real_switch_item_coord_unique, True
        )

        # Verify result
        assert result is False

    async def test_write_number_value_success(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_modbus_api_coord_unique_fixed,
        real_number_item_coord_unique,
    ) -> None:
        """Test successful number value write."""
        # Mock successful write at the ModbusAPI level - this is where it actually happens
        mock_modbus_api_coord_unique_fixed.write_registers.return_value = True

        # Test write using actual coordinator method with real ModbusItem
        result = await sax_battery_coordinator_instance_fixed.async_write_number_value(
            real_number_item_coord_unique, 15.5
        )

        # Verify result - should succeed with real ModbusItem
        assert result is True
        # Verify the modbus API was called through the ModbusItem
        mock_modbus_api_coord_unique_fixed.write_registers.assert_called_once()

    async def test_write_number_value_failure(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_modbus_api_coord_unique_fixed,
        real_number_item_coord_unique,
    ) -> None:
        """Test number value write failure."""
        # Mock write failure with specific exception
        mock_modbus_api_coord_unique_fixed.write_registers.side_effect = OSError(
            "Network error"
        )

        # Test write should return False on exception
        result = await sax_battery_coordinator_instance_fixed.async_write_number_value(
            real_number_item_coord_unique, 15.5
        )

        # Verify result
        assert result is False

    async def test_coordinator_properties(
        self, sax_battery_coordinator_instance_fixed
    ) -> None:
        """Test coordinator properties are properly set."""
        coordinator = sax_battery_coordinator_instance_fixed

        # Verify basic properties
        assert coordinator.battery_id == "battery_a"
        assert coordinator.battery_config is not None
        assert coordinator.battery_config[CONF_BATTERY_HOST] == "192.168.1.100"
        assert coordinator.battery_config[CONF_BATTERY_PORT] == 502
        assert coordinator.battery_config[CONF_BATTERY_IS_MASTER] is True

    async def test_coordinator_initialization(
        self,
        hass: HomeAssistant,
        mock_config_entry_coord_unique,
        mock_sax_data_coord_unique,
        mock_modbus_api_coord_unique_fixed,
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
            modbus_api=mock_modbus_api_coord_unique_fixed,
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
            modbus_api=mock_modbus_api_coord_unique_fixed,
            config_entry=mock_config_entry_coord_unique,
            battery_config=slave_config,
        )

        assert slave_coordinator.battery_id == "battery_b"
        assert slave_coordinator.battery_config[CONF_BATTERY_IS_MASTER] is False
        assert slave_coordinator.battery_config[CONF_BATTERY_PHASE] == "L2"

    # New comprehensive tests for _update_calculated_values
    async def test_update_calculated_values_success(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_sax_data_coord_unique,
    ) -> None:
        """Test successful calculation of SAXItem values."""
        # Create test SAXItems with mock calculations
        sax_item_1 = SAXItem(
            name="sax_combined_soc",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
        )
        sax_item_1.calculate_value = MagicMock(return_value=75.5)
        sax_item_1.coordinators = {}

        sax_item_2 = SAXItem(
            name="sax_cumulative_energy",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
        )
        sax_item_2.calculate_value = MagicMock(return_value=1500.0)
        sax_item_2.coordinators = {}

        # Mock the SAX data to return our test items
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = [
            sax_item_1,
            sax_item_2,
        ]

        # Create test data dictionary
        data = {"existing_key": "existing_value"}

        # Test the method directly
        sax_battery_coordinator_instance_fixed._update_calculated_values(data)

        # Verify calculated values were added to data
        assert "sax_combined_soc" in data
        assert data["sax_combined_soc"] == 75.5
        assert "sax_cumulative_energy" in data
        assert data["sax_cumulative_energy"] == 1500.0
        assert "existing_key" in data  # Existing data preserved

        # Verify calculate_value was called on both items
        sax_item_1.calculate_value.assert_called_once()
        sax_item_2.calculate_value.assert_called_once()

    async def test_update_calculated_values_with_none_results(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_sax_data_coord_unique,
    ) -> None:
        """Test handling of SAXItems that return None from calculations."""
        # Create test SAXItem that returns None
        sax_item = SAXItem(
            name="sax_unavailable_data",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
        )
        sax_item.calculate_value = MagicMock(return_value=None)
        sax_item.coordinators = {}

        # Mock the SAX data
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = [sax_item]

        # Create test data dictionary
        data: dict[str, Any] = {}

        # Test the method
        sax_battery_coordinator_instance_fixed._update_calculated_values(data)

        # Verify None value was properly handled
        assert "sax_unavailable_data" in data
        assert data["sax_unavailable_data"] is None
        sax_item.calculate_value.assert_called_once()

    async def test_update_calculated_values_with_calculation_errors(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_sax_data_coord_unique,
    ) -> None:
        """Test handling of calculation errors (ValueError, TypeError, ZeroDivisionError)."""
        # Create SAXItems that raise different types of errors
        sax_item_value_error = SAXItem(
            name="sax_value_error",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
        )
        sax_item_value_error.calculate_value = MagicMock(
            side_effect=ValueError("Invalid value for calculation")
        )
        sax_item_value_error.coordinators = {}

        sax_item_type_error = SAXItem(
            name="sax_type_error",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
        )
        sax_item_type_error.calculate_value = MagicMock(
            side_effect=TypeError("Type mismatch in calculation")
        )
        sax_item_type_error.coordinators = {}

        sax_item_zero_div_error = SAXItem(
            name="sax_zero_div_error",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
        )
        sax_item_zero_div_error.calculate_value = MagicMock(
            side_effect=ZeroDivisionError("Division by zero")
        )
        sax_item_zero_div_error.coordinators = {}

        # Mock the SAX data
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = [
            sax_item_value_error,
            sax_item_type_error,
            sax_item_zero_div_error,
        ]

        # Create test data dictionary
        data: dict[str, Any] = {}

        # Test the method - should handle errors gracefully
        sax_battery_coordinator_instance_fixed._update_calculated_values(data)

        # Verify all items have None values due to errors
        assert "sax_value_error" in data
        assert data["sax_value_error"] is None
        assert "sax_type_error" in data
        assert data["sax_type_error"] is None
        assert "sax_zero_div_error" in data
        assert data["sax_zero_div_error"] is None

        # Verify all calculate_value methods were called
        sax_item_value_error.calculate_value.assert_called_once()
        sax_item_type_error.calculate_value.assert_called_once()
        sax_item_zero_div_error.calculate_value.assert_called_once()

    async def test_update_calculated_values_coordinator_setup(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_sax_data_coord_unique,
    ) -> None:
        """Test that coordinators are properly set up for SAXItems."""
        # Create SAXItem without coordinators set
        sax_item = SAXItem(
            name="sax_test_coordination",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
        )
        sax_item.calculate_value = MagicMock(return_value=42.0)
        sax_item.set_coordinators = MagicMock()
        # Simulate missing coordinators attribute
        del sax_item.coordinators

        # Mock the SAX data
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = [sax_item]
        mock_sax_data_coord_unique.coordinators = {
            "battery_a": sax_battery_coordinator_instance_fixed
        }

        # Create test data dictionary
        data: dict[str, Any] = {}

        # Test the method
        sax_battery_coordinator_instance_fixed._update_calculated_values(data)

        # Verify set_coordinators was called
        sax_item.set_coordinators.assert_called_once_with(
            mock_sax_data_coord_unique.coordinators
        )

        # Verify calculation proceeded normally
        assert "sax_test_coordination" in data
        assert data["sax_test_coordination"] == 42.0

    async def test_update_calculated_values_mixed_item_types(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_sax_data_coord_unique,
    ) -> None:
        """Test handling of mixed item types (only SAXItems should be processed)."""
        # Create a real SAXItem
        sax_item = SAXItem(
            name="sax_valid_item",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
        )
        sax_item.calculate_value = MagicMock(return_value=100.0)
        sax_item.coordinators = {}

        # Create a non-SAXItem object
        non_sax_item = MagicMock()
        non_sax_item.name = "non_sax_item"

        # Mock the SAX data to return mixed types
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = [
            sax_item,
            non_sax_item,
        ]

        # Create test data dictionary
        data: dict[str, Any] = {}

        # Test the method
        sax_battery_coordinator_instance_fixed._update_calculated_values(data)

        # Verify only SAXItem was processed
        assert "sax_valid_item" in data
        assert data["sax_valid_item"] == 100.0
        assert "non_sax_item" not in data

        # Verify calculate_value was only called on SAXItem
        sax_item.calculate_value.assert_called_once()

    async def test_update_calculated_values_empty_items_list(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_sax_data_coord_unique,
    ) -> None:
        """Test handling of empty SAXItems list."""
        # Mock empty SAX items list
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = []

        # Create test data dictionary with existing data
        data = {"existing_key": "existing_value"}

        # Test the method
        sax_battery_coordinator_instance_fixed._update_calculated_values(data)

        # Verify existing data is preserved and no new data added
        assert len(data) == 1
        assert "existing_key" in data
        assert data["existing_key"] == "existing_value"

    async def test_update_calculated_values_with_unexpected_exception(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_sax_data_coord_unique,
    ) -> None:
        """Test handling of unexpected exceptions during calculation updates."""
        # Mock get_sax_items_for_battery to raise an unexpected exception
        mock_sax_data_coord_unique.get_sax_items_for_battery.side_effect = RuntimeError(
            "Unexpected runtime error"
        )

        # Create test data dictionary
        data = {"existing_key": "existing_value"}

        # Test the method - should handle exception gracefully and not crash
        sax_battery_coordinator_instance_fixed._update_calculated_values(data)

        # Verify existing data is preserved (no changes made due to exception)
        assert "existing_key" in data
        assert data["existing_key"] == "existing_value"

    async def test_update_calculated_values_performance_optimization(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_sax_data_coord_unique,
    ) -> None:
        """Test performance optimization with multiple SAXItems."""
        # Create multiple SAXItems to test batch processing
        sax_items = []
        for i in range(5):
            sax_item = SAXItem(
                name=f"sax_item_{i}",
                mtype=TypeConstants.SENSOR_CALC,
                device=DeviceConstants.SYS,
            )
            sax_item.calculate_value = MagicMock(return_value=float(i * 10))
            sax_item.coordinators = {}
            sax_items.append(sax_item)

        # Mock the SAX data
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = sax_items

        # Create test data dictionary
        data: dict[str, Any] = {}

        # Test the method
        sax_battery_coordinator_instance_fixed._update_calculated_values(data)

        # Verify all items were processed efficiently
        assert len(data) == 5
        for i in range(5):
            assert f"sax_item_{i}" in data
            assert data[f"sax_item_{i}"] == float(i * 10)
            sax_items[i].calculate_value.assert_called_once()

    async def test_coordinator_data_handling(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_sax_data_coord_unique,
        real_sensor_item_coord_unique,
        mock_modbus_api_coord_unique_fixed,
    ) -> None:
        """Test coordinator data handling with fixed async mocking."""
        # Mock successful read at the ModbusAPI level
        mock_modbus_api_coord_unique_fixed.read_holding_registers.return_value = 42.5

        # Update the sensor item to use the fixed API
        real_sensor_item_coord_unique.modbus_api = mock_modbus_api_coord_unique_fixed

        # Mock the SAX data to return our real test items
        mock_sax_data_coord_unique.get_modbus_items_for_battery.return_value = [
            real_sensor_item_coord_unique
        ]
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = []

        # Test update
        result = await sax_battery_coordinator_instance_fixed._async_update_data()

        # Verify data structure contains the sensor data
        assert isinstance(result, dict)
        # Check that data was stored correctly
        assert "sax_temperature" in result
        assert result["sax_temperature"] == 42.5

    async def test_update_with_modbus_exception(
        self, sax_battery_coordinator_instance_fixed, mock_sax_data_coord_unique
    ) -> None:
        """Test data update with ModbusException with fixed async mocking."""
        # Mock ModbusException during battery data fetch (not during connection)
        mock_sax_data_coord_unique.get_modbus_items_for_battery.return_value = []
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = []

        # Mock the _update_battery_data method to raise ModbusException
        with patch.object(  # noqa: SIM117
            sax_battery_coordinator_instance_fixed,
            "_update_battery_data",
            side_effect=ModbusException("Modbus communication error"),
        ):
            # Test update should raise UpdateFailed
            with pytest.raises(
                UpdateFailed, match="Error communicating with battery battery_a"
            ):
                await sax_battery_coordinator_instance_fixed._async_update_data()

    @patch.object(SAXItem, "calculate_value")
    async def test_sax_item_data_handling(
        self,
        mock_calculate_value,
        sax_battery_coordinator_instance_fixed,
        mock_sax_data_coord_unique,
        mock_modbus_api_coord_unique_fixed,
    ) -> None:
        """Test coordinator handling of SAXItem calculated values with fixed async mocking."""
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
        result = await sax_battery_coordinator_instance_fixed._async_update_data()

        # Verify data structure contains the calculated data
        assert isinstance(result, dict)
        assert "sax_combined_soc" in result
        assert result["sax_combined_soc"] == 75.5
        # Verify the calculate_value method was called
        mock_calculate_value.assert_called_once()

    async def test_coordinator_smart_meter_handling(
        self,
        sax_battery_coordinator_instance_fixed,
        mock_sax_data_coord_unique,
        mock_modbus_api_coord_unique_fixed,
    ) -> None:
        """Test coordinator smart meter data handling for master battery with fixed async mocking."""
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
        smart_meter_item.modbus_api = mock_modbus_api_coord_unique_fixed

        # Mock smart meter data return and read result
        mock_sax_data_coord_unique.get_modbus_items_for_battery.return_value = []
        mock_sax_data_coord_unique.get_sax_items_for_battery.return_value = []
        mock_sax_data_coord_unique.get_smart_meter_items.return_value = [
            smart_meter_item
        ]
        mock_sax_data_coord_unique.should_poll_smart_meter.return_value = True
        mock_modbus_api_coord_unique_fixed.read_holding_registers.return_value = 1500

        # Test update
        result = await sax_battery_coordinator_instance_fixed._async_update_data()

        # Verify smart meter data was processed
        assert isinstance(result, dict)
        assert "smartmeter_total_power" in result
        assert result["smartmeter_total_power"] == 1500
