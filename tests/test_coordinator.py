"""Test SAX Battery data update coordinator."""

from __future__ import annotations

import ast
import logging
import operator
from unittest.mock import AsyncMock, MagicMock

from pymodbus import ModbusException
import pytest

from custom_components.sax_battery.coordinator import (
    SAFE_OPERATIONS,
    SAXBatteryCoordinator,
)
from custom_components.sax_battery.enums import DeviceConstants, TypeConstants
from custom_components.sax_battery.items import ModbusItem
from custom_components.sax_battery.modbusobject import ModbusAPI
from custom_components.sax_battery.models import SAXBatteryData
from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class TestSAXBatteryCoordinator:
    """Test SAX Battery data update coordinator."""

    @pytest.fixture
    def mock_modbus_api_for_coordinator(self) -> MagicMock:
        """Create mock ModbusAPI instance."""
        api = MagicMock(spec=ModbusAPI)
        api.read_holding_registers = AsyncMock()
        api.write_holding_register = AsyncMock()
        api.connect = AsyncMock()
        api.close = MagicMock()
        return api

    @pytest.fixture
    def mock_smart_meter_data_for_coordinator(self) -> MagicMock:
        """Create mock smart meter data."""
        smart_meter = MagicMock()
        smart_meter.set_value = MagicMock()
        return smart_meter

    @pytest.fixture
    def mock_sax_data_for_coordinator(
        self, mock_smart_meter_data_for_coordinator
    ) -> MagicMock:
        """Create mock SAXBatteryData instance."""
        sax_data = MagicMock(spec=SAXBatteryData)
        sax_data.smart_meter_data = mock_smart_meter_data_for_coordinator
        sax_data.should_poll_smart_meter.return_value = True
        sax_data.get_smart_meter_items.return_value = []
        sax_data.batteries = {}
        return sax_data

    @pytest.fixture
    def coordinator_for_testing(
        self, hass, mock_sax_data_for_coordinator, mock_modbus_api_for_coordinator
    ) -> SAXBatteryCoordinator:
        """Create SAXBatteryCoordinator instance."""
        mock_config_entry = MagicMock(spec=ConfigEntry)
        return SAXBatteryCoordinator(
            hass=hass,
            battery_id="battery_a",
            sax_data=mock_sax_data_for_coordinator,
            modbus_api=mock_modbus_api_for_coordinator,
            config_entry=mock_config_entry,
        )

    @pytest.fixture
    def smart_meter_item_for_coordinator(self) -> ModbusItem:
        """Create a smart meter ModbusItem."""
        return ModbusItem(
            name="smartmeter_power",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.SENSOR,
            address=1000,
            battery_slave_id=1,
            factor=1.0,
        )

    async def test_update_smart_meter_data_success(
        self,
        coordinator_for_testing,
        mock_sax_data_for_coordinator,
        mock_modbus_api_for_coordinator,
        smart_meter_item_for_coordinator,
    ):
        """Test successful smart meter data update."""
        mock_sax_data_for_coordinator.get_smart_meter_items.return_value = [
            smart_meter_item_for_coordinator
        ]
        mock_modbus_api_for_coordinator.read_holding_registers.return_value = 1500

        data = {}
        await coordinator_for_testing._update_smart_meter_data(data)

        # Verify data was updated
        assert data["smartmeter_power"] == 1500.0

        # Verify modbus API was called correctly with new signature
        mock_modbus_api_for_coordinator.read_holding_registers.assert_called_once_with(
            count=1, modbus_item=smart_meter_item_for_coordinator
        )

        # Verify smart meter data was updated
        mock_sax_data_for_coordinator.smart_meter_data.set_value.assert_called_once_with(
            "smartmeter_power", 1500.0
        )

    async def test_update_smart_meter_data_modbus_exception(
        self,
        coordinator_for_testing,
        mock_sax_data_for_coordinator,
        mock_modbus_api_for_coordinator,
        smart_meter_item_for_coordinator,
    ):
        """Test smart meter data update with modbus exception."""
        mock_sax_data_for_coordinator.get_smart_meter_items.return_value = [
            smart_meter_item_for_coordinator
        ]
        mock_modbus_api_for_coordinator.read_holding_registers.side_effect = (
            ModbusException("Connection failed")
        )

        data = {}
        await coordinator_for_testing._update_smart_meter_data(data)

        # Should set None value on error
        assert data["smartmeter_power"] is None

    async def test_update_smart_meter_data_no_smart_meter(
        self, coordinator_for_testing, mock_sax_data_for_coordinator
    ):
        """Test smart meter data update when no smart meter data exists."""
        mock_sax_data_for_coordinator.smart_meter_data = None
        mock_sax_data_for_coordinator.get_smart_meter_items.return_value = []

        data = {}
        await coordinator_for_testing._update_smart_meter_data(data)

        # Should not crash and data should remain empty
        assert data == {}

    async def test_update_smart_meter_data_empty_response(
        self,
        coordinator_for_testing,
        mock_sax_data_for_coordinator,
        mock_modbus_api_for_coordinator,
        smart_meter_item_for_coordinator,
    ):
        """Test smart meter data update with empty modbus response."""
        mock_sax_data_for_coordinator.get_smart_meter_items.return_value = [
            smart_meter_item_for_coordinator
        ]
        mock_modbus_api_for_coordinator.read_holding_registers.return_value = None

        data = {}
        await coordinator_for_testing._update_smart_meter_data(data)

        # When response is None, the item is added to data with None value
        assert data["smartmeter_power"] is None

    async def test_update_smart_meter_data_with_factor(
        self,
        coordinator_for_testing,
        mock_sax_data_for_coordinator,
        mock_modbus_api_for_coordinator,
    ):
        """Test smart meter data update with factor applied."""
        item_with_factor = ModbusItem(
            name="smartmeter_voltage",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.SENSOR,
            address=1001,
            battery_slave_id=1,
            factor=10.0,
        )

        mock_sax_data_for_coordinator.get_smart_meter_items.return_value = [
            item_with_factor
        ]
        mock_modbus_api_for_coordinator.read_holding_registers.return_value = 2300

        data = {}
        await coordinator_for_testing._update_smart_meter_data(data)

        # Factor is not applied in coordinator - raw value is stored
        assert data["smartmeter_voltage"] == 2300.0

    async def test_update_smart_meter_data_oserror(
        self,
        coordinator_for_testing,
        mock_sax_data_for_coordinator,
        mock_modbus_api_for_coordinator,
        smart_meter_item_for_coordinator,
    ):
        """Test smart meter data update with OSError."""
        mock_sax_data_for_coordinator.get_smart_meter_items.return_value = [
            smart_meter_item_for_coordinator
        ]
        mock_modbus_api_for_coordinator.read_holding_registers.side_effect = OSError(
            "Network error"
        )

        data = {}
        await coordinator_for_testing._update_smart_meter_data(data)

        # Should set None value on error
        assert data["smartmeter_power"] is None

    async def test_update_smart_meter_data_timeout_error(
        self,
        coordinator_for_testing,
        mock_sax_data_for_coordinator,
        mock_modbus_api_for_coordinator,
        smart_meter_item_for_coordinator,
    ):
        """Test smart meter data update with TimeoutError."""
        mock_sax_data_for_coordinator.get_smart_meter_items.return_value = [
            smart_meter_item_for_coordinator
        ]
        mock_modbus_api_for_coordinator.read_holding_registers.side_effect = (
            TimeoutError("Timeout")
        )

        data = {}
        await coordinator_for_testing._update_smart_meter_data(data)

        # Should set None value on error
        assert data["smartmeter_power"] is None


class TestSafeEvalExpression:
    """Test safe expression evaluation."""

    @pytest.fixture
    def coordinator_for_eval_testing(
        self, hass, mock_modbus_api, mock_sax_data
    ) -> SAXBatteryCoordinator:
        """Create coordinator for testing."""
        mock_config_entry = MagicMock(spec=ConfigEntry)
        return SAXBatteryCoordinator(
            hass=hass,
            battery_id="battery_a",
            sax_data=mock_sax_data,
            modbus_api=mock_modbus_api,
            config_entry=mock_config_entry,
        )

    def test_safe_eval_simple_addition(self, coordinator_for_eval_testing):
        """Test simple addition."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 + val_2", {"val_1": 10, "val_2": 5}
        )
        assert result == 15

    def test_safe_eval_simple_subtraction(self, coordinator_for_eval_testing):
        """Test simple subtraction."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 - val_2", {"val_1": 10, "val_2": 3}
        )
        assert result == 7

    def test_safe_eval_multiplication(self, coordinator_for_eval_testing):
        """Test multiplication."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 * val_2", {"val_1": 4, "val_2": 5}
        )
        assert result == 20

    def test_safe_eval_division(self, coordinator_for_eval_testing):
        """Test division."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 / val_2", {"val_1": 20, "val_2": 4}
        )
        assert result == 5

    def test_safe_eval_unary_minus(self, coordinator_for_eval_testing):
        """Test unary minus."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "-val_1", {"val_1": 10}
        )
        assert result == -10

    def test_safe_eval_unary_plus(self, coordinator_for_eval_testing):
        """Test unary plus."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "+val_1", {"val_1": 10}
        )
        assert result == 10

    def test_safe_eval_complex_expression(self, coordinator_for_eval_testing):
        """Test complex expression."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 + val_2 * val_3", {"val_1": 2, "val_2": 3, "val_3": 4}
        )
        assert result == 14  # 2 + (3 * 4)

    def test_safe_eval_with_constants(self, coordinator_for_eval_testing):
        """Test with numeric constants."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 + 5", {"val_1": 10}
        )
        assert result == 15

    def test_safe_eval_parentheses(self, coordinator_for_eval_testing):
        """Test with parentheses."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "(val_1 + val_2) * val_3", {"val_1": 2, "val_2": 3, "val_3": 4}
        )
        assert result == 20  # (2 + 3) * 4

    def test_safe_eval_nested_operations(self, coordinator_for_eval_testing):
        """Test nested operations."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 * (val_2 + val_3) / val_4",
            {"val_1": 6, "val_2": 2, "val_3": 4, "val_4": 3},
        )
        assert result == 12  # 6 * (2 + 4) / 3

    def test_safe_eval_division_by_zero(self, coordinator_for_eval_testing):
        """Test division by zero handling."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 / val_2", {"val_1": 10, "val_2": 0}
        )
        assert result is None

    def test_safe_eval_unknown_variable(self, coordinator_for_eval_testing):
        """Test unknown variable handling."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 + unknown", {"val_1": 10}
        )
        assert result is None

    def test_safe_eval_syntax_error(self, coordinator_for_eval_testing):
        """Test syntax error handling."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 +", {"val_1": 10}
        )
        assert result is None

    def test_safe_eval_empty_expression(self, coordinator_for_eval_testing):
        """Test empty expression."""
        result = coordinator_for_eval_testing._safe_eval_expression("", {"val_1": 10})
        assert result is None

    def test_safe_eval_non_numeric_constant(self, coordinator_for_eval_testing):
        """Test non-numeric constant handling."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 + 'text'", {"val_1": 10}
        )
        assert result is None

    def test_safe_eval_float_conversion(self, coordinator_for_eval_testing):
        """Test float conversion."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 / val_2", {"val_1": 7, "val_2": 2}
        )
        assert result == 3.5

    def test_safe_eval_float_variables(self, coordinator_for_eval_testing):
        """Test with float variables."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 + val_2", {"val_1": 10.5, "val_2": 2.3}
        )
        assert result == 12.8

    def test_safe_eval_type_error_handling(self, coordinator_for_eval_testing):
        """Test type error handling."""
        result = coordinator_for_eval_testing._safe_eval_expression(
            "val_1 & val_2", {"val_1": 10, "val_2": 5}
        )
        assert result is None

    def test_safe_operations_mapping(self):
        """Test SAFE_OPERATIONS mapping."""
        assert ast.Add in SAFE_OPERATIONS
        assert ast.Sub in SAFE_OPERATIONS
        assert ast.Mult in SAFE_OPERATIONS
        assert ast.Div in SAFE_OPERATIONS
        assert ast.USub in SAFE_OPERATIONS
        assert ast.UAdd in SAFE_OPERATIONS

        assert SAFE_OPERATIONS[ast.Add] == operator.add
        assert SAFE_OPERATIONS[ast.Sub] == operator.sub
        assert SAFE_OPERATIONS[ast.Mult] == operator.mul
        assert SAFE_OPERATIONS[ast.Div] == operator.truediv
        assert SAFE_OPERATIONS[ast.USub] == operator.neg
        assert SAFE_OPERATIONS[ast.UAdd] == operator.pos
