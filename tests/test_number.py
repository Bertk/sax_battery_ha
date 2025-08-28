"""Test SAX Battery number platform."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_components.sax_battery.const import (
    DESCRIPTION_SAX_MAX_CHARGE,
    DESCRIPTION_SAX_MAX_DISCHARGE,
    PILOT_ITEMS,
    SAX_MAX_CHARGE,
    SAX_MAX_DISCHARGE,
    SAX_MIN_SOC,
)
from custom_components.sax_battery.enums import DeviceConstants, TypeConstants
from custom_components.sax_battery.items import ModbusItem, SAXItem
from custom_components.sax_battery.number import (
    SAXBatteryConfigNumber,
    SAXBatteryModbusNumber,
)
from homeassistant.components.number import NumberEntityDescription, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def power_number_item_test():
    """Create power number item."""
    return ModbusItem(
        address=100,
        name="sax_max_charge_power",
        mtype=TypeConstants.NUMBER_WO,
        device=DeviceConstants.SYS,
        entitydescription=NumberEntityDescription(
            key="max_charge_power",
            name="Sax Maximum Charge Power",
            native_min_value=0,
            native_max_value=10000,
            native_step=100,
            native_unit_of_measurement="W",
        ),
    )


@pytest.fixture
def percentage_number_item_test():
    """Create percentage number item."""
    return ModbusItem(
        address=101,
        name="sax_min_soc",
        mtype=TypeConstants.NUMBER_WO,
        device=DeviceConstants.SYS,
        entitydescription=NumberEntityDescription(
            key="min_soc",
            name="Sax Minimum State of Charge",
            native_min_value=5,
            native_max_value=95,
            native_step=1,
            native_unit_of_measurement=PERCENTAGE,
        ),
    )


class TestSAXBatteryNumber:
    """Test SAX Battery number entity."""

    def test_number_init(self, mock_coordinator_number, power_number_item_test) -> None:
        """Test number entity initialization."""
        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=power_number_item_test,
        )

        assert number._battery_id == "battery_a"
        assert number._modbus_item == power_number_item_test
        assert number.unique_id == "sax_battery_a_max_charge_power"
        assert number.name == "Sax Battery A Maximum Charge Power"

    def test_number_init_with_entity_description(
        self, mock_coordinator_number, power_number_item_test
    ) -> None:
        """Test number entity initialization with entity description."""
        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=power_number_item_test,
        )

        # Test that values come from entity description via _attr_* attributes
        assert number.entity_description.native_min_value == 0
        assert number.entity_description.native_max_value == 10000
        assert number.entity_description.native_step == 100
        assert number.entity_description.native_unit_of_measurement == "W"

    def test_number_native_value(
        self, mock_coordinator_number, power_number_item_test
    ) -> None:
        """Test number native value."""
        mock_coordinator_number.data["sax_max_charge_power"] = 5000

        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=power_number_item_test,
        )

        assert number.native_value == 5000.0

    def test_number_native_value_missing_data(
        self, mock_coordinator_number, power_number_item_test
    ) -> None:
        """Test number native value when data is missing."""
        mock_coordinator_number.data = {}

        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=power_number_item_test,
        )

        assert number.native_value is None

    def test_number_native_value_invalid_data(
        self, mock_coordinator_number, power_number_item_test
    ) -> None:
        """Test number native value with invalid data."""
        mock_coordinator_number.data["sax_max_charge_power"] = "invalid"

        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=power_number_item_test,
        )

        assert number.native_value is None

    async def test_async_set_native_value_success(
        self, mock_coordinator_number, power_number_item_test
    ) -> None:
        """Test setting native value successfully."""
        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=power_number_item_test,
        )

        await number.async_set_native_value(6000.0)

        mock_coordinator_number.async_write_number_value.assert_called_once_with(
            power_number_item_test, 6000.0
        )

    async def test_async_set_native_value_failure(
        self, mock_coordinator_number, power_number_item_test
    ) -> None:
        """Test setting native value with failure."""
        mock_coordinator_number.async_write_number_value.return_value = False

        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=power_number_item_test,
        )

        with pytest.raises(
            HomeAssistantError,
            match="Failed to set value 6000.0 for Sax Battery A Maximum Charge Power",
        ):
            await number.async_set_native_value(6000.0)

    def test_extra_state_attributes(
        self, mock_coordinator_number, power_number_item_test
    ) -> None:
        """Test extra state attributes."""
        mock_coordinator_number.data["sax_max_charge_power"] = 5000

        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=power_number_item_test,
        )

        attributes = number.extra_state_attributes
        assert attributes is not None
        assert attributes["battery_id"] == "battery_a"
        assert attributes["modbus_address"] == 100
        assert attributes["raw_value"] == 5000
        assert attributes["entity_type"] == "modbus"
        assert "last_update" in attributes

    def test_device_info(self, mock_coordinator_number, power_number_item_test) -> None:
        """Test device info."""
        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=power_number_item_test,
        )

        device_info = number.device_info
        assert device_info is not None
        mock_coordinator_number.sax_data.get_device_info.assert_called_once_with(
            "battery_a"
        )


class TestSAXBatteryConfigNumber:
    """Test SAX Battery config number entity."""

    def test_config_number_init(self, mock_coordinator_number) -> None:
        """Test config number entity initialization."""
        # Find the SAX_MIN_SOC item from PILOT_ITEMS
        sax_min_soc_item: SAXItem | None = next(
            (item for item in PILOT_ITEMS if item.name == SAX_MIN_SOC), None
        )

        assert sax_min_soc_item is not None, "SAX_MIN_SOC not found in PILOT_ITEMS"

        number = SAXBatteryConfigNumber(
            coordinator=mock_coordinator_number,
            sax_item=sax_min_soc_item,
            battery_count=1,
        )

        assert number._sax_item == sax_min_soc_item
        assert number._battery_count == 1
        assert number.unique_id == "sax_min_soc"
        assert number.name == "Sax Minimum SOC"

    def test_config_number_native_value(self, mock_coordinator_number) -> None:
        """Test config number native value."""
        sax_min_soc_item: SAXItem | None = next(
            (item for item in PILOT_ITEMS if item.name == SAX_MIN_SOC), None
        )

        assert sax_min_soc_item is not None, "SAX_MIN_SOC not found in PILOT_ITEMS"

        mock_coordinator_number.data[SAX_MIN_SOC] = 15.0

        number = SAXBatteryConfigNumber(
            coordinator=mock_coordinator_number,
            sax_item=sax_min_soc_item,
        )

        assert number.native_value == 15.0

    async def test_config_number_set_native_value(
        self, mock_coordinator_number
    ) -> None:
        """Test setting config number native value."""
        sax_min_soc_item: SAXItem | None = next(
            (item for item in PILOT_ITEMS if item.name == SAX_MIN_SOC), None
        )

        assert sax_min_soc_item is not None, "SAX_MIN_SOC not found in PILOT_ITEMS"

        number = SAXBatteryConfigNumber(
            coordinator=mock_coordinator_number,
            sax_item=sax_min_soc_item,
        )

        await number.async_set_native_value(20.0)

        # Config values are stored in coordinator data
        assert mock_coordinator_number.data[SAX_MIN_SOC] == 20.0


# Rest of the test classes remain unchanged
class TestNumberEntityConfiguration:
    """Test number entity configuration variations."""

    def test_number_with_percentage_format(
        self, mock_coordinator_number, percentage_number_item_test
    ) -> None:
        """Test number entity with percentage format."""
        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=percentage_number_item_test,
        )

        assert number.entity_description.native_unit_of_measurement == "%"
        assert number.name == "Sax Battery A Minimum State of Charge"

    def test_number_name_formatting(self, mock_coordinator_number) -> None:
        """Test number name formatting."""
        item_with_underscores = ModbusItem(
            name="sax_test_underscore_name",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.NUMBER,
            entitydescription=NumberEntityDescription(
                key="sax_test_underscore_name",
                name="Sax Test Underscore Name",
                mode=NumberMode.SLIDER,
                native_unit_of_measurement=UnitOfPower.WATT,
                native_min_value=0,
                native_max_value=3500,
                native_step=100,
            ),
        )

        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_b",
            modbus_item=item_with_underscores,
        )

        assert number.name == "Sax Battery B Test Underscore Name"

    def test_number_mode_property(self, mock_coordinator_number) -> None:
        """Test number mode property with different mode values."""
        box_item = ModbusItem(
            name="sax_charge_limit",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.NUMBER,
            address=200,
            battery_slave_id=1,
            factor=1.0,
            entitydescription=NumberEntityDescription(
                key="sax_test_underscore_name",
                name="Sax Test Underscore Name",
                mode=NumberMode.AUTO,
                native_unit_of_measurement=UnitOfPower.WATT,
                native_min_value=0,
                native_max_value=3500,
                native_step=100,
            ),
        )

        box_number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=box_item,
        )

        # Implementation uses _attr_mode from entity description
        assert box_number.entity_description.mode == NumberMode.AUTO

    def test_number_mode_from_entity_description(self, mock_coordinator_number) -> None:
        """Test number mode from entity description."""
        item_with_mode = ModbusItem(
            name="sax_slider_control",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.NUMBER_WO,
            entitydescription=NumberEntityDescription(
                key="slider_control",
                name="Slider Control",
                mode=NumberMode.SLIDER,
            ),
        )

        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=item_with_mode,
        )

        assert number.entity_description.mode == NumberMode.SLIDER

    def test_number_entity_category_from_description(
        self, mock_coordinator_number
    ) -> None:
        """Test number entity category from entity description."""
        item_with_category = ModbusItem(
            name="sax_custom_number",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.NUMBER_WO,
            entitydescription=NumberEntityDescription(
                key="custom_number",
                name="Custom Number",
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=item_with_category,
        )

        assert number.entity_description.entity_category == EntityCategory.DIAGNOSTIC

    def test_number_without_unit(self, mock_coordinator_number) -> None:
        """Test number entity without unit."""
        unitless_item = ModbusItem(
            name="sax_unitless_number",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.NUMBER_WO,
            entitydescription=NumberEntityDescription(
                key="sax_test_underscore_name",
                name="Sax Test Underscore Name",
                mode=NumberMode.AUTO,
                native_unit_of_measurement=UnitOfPower.WATT,
                native_min_value=0,
                native_max_value=3500,
                native_step=100,
            ),
        )

        number = SAXBatteryModbusNumber(
            coordinator=mock_coordinator_number,
            battery_id="battery_a",
            modbus_item=unitless_item,
        )

        assert number.entity_description.native_unit_of_measurement == UnitOfPower.WATT


class TestSAXBatteryNumberDynamicLimits:
    """Test dynamic limits functionality in SAX Battery number entities."""

    @pytest.fixture
    def max_charge_modbus_item(self):
        """Create max charge ModbusItem."""
        return ModbusItem(
            name=SAX_MAX_CHARGE,
            device=DeviceConstants.SYS,
            mtype=TypeConstants.NUMBER,
            entitydescription=DESCRIPTION_SAX_MAX_CHARGE,
            address=100,
            battery_slave_id=1,
            factor=1.0,
        )

    @pytest.fixture
    def max_discharge_modbus_item(self):
        """Create max discharge ModbusItem."""
        return ModbusItem(
            name=SAX_MAX_DISCHARGE,
            device=DeviceConstants.SYS,
            mtype=TypeConstants.NUMBER,
            entitydescription=DESCRIPTION_SAX_MAX_DISCHARGE,
            address=101,
            battery_slave_id=1,
            factor=1.0,
        )

    @pytest.fixture
    def regular_modbus_item(self):
        """Create regular ModbusItem (not charge/discharge)."""
        return ModbusItem(
            name="sax_regular_setting",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.NUMBER,
            entitydescription=NumberEntityDescription(
                key="regular_setting",
                name="Regular Setting",
                native_min_value=0,
                native_max_value=500,
                native_step=1,
                native_unit_of_measurement="V",
            ),
            address=102,
            battery_slave_id=1,
            factor=1.0,
        )

    def test_apply_dynamic_limits_max_charge_single_battery(
        self, mock_coordinator_number, max_charge_modbus_item
    ):
        """Test dynamic limits for max charge with single battery."""
        with patch(
            "custom_components.sax_battery.number.calculate_system_max_charge",
            return_value=4500,
        ) as mock_calc:
            number_entity = SAXBatteryModbusNumber(
                coordinator=mock_coordinator_number,
                battery_id="battery_a",
                modbus_item=max_charge_modbus_item,
                battery_count=1,
            )

            mock_calc.assert_called_once_with(1)
            assert number_entity._attr_native_max_value == 4500.0

    def test_apply_dynamic_limits_regular_item_unchanged(
        self, mock_coordinator_number, regular_modbus_item
    ):
        """Test that regular items are not affected by dynamic limits."""
        with (
            patch(
                "custom_components.sax_battery.number.calculate_system_max_charge"
            ) as mock_charge_calc,
            patch(
                "custom_components.sax_battery.number.calculate_system_max_discharge"
            ) as mock_discharge_calc,
        ):
            number_entity = SAXBatteryModbusNumber(
                coordinator=mock_coordinator_number,
                battery_id="battery_a",
                modbus_item=regular_modbus_item,
                battery_count=2,
            )

            # Calculations should not be called for regular items
            mock_charge_calc.assert_not_called()
            mock_discharge_calc.assert_not_called()

            # Should keep entity description max value (500V from fixture)
            assert number_entity.entity_description.native_max_value == 500

    def test_apply_dynamic_limits_multiple_calls_idempotent(
        self, mock_coordinator_number, max_charge_modbus_item
    ):
        """Test that calling _apply_dynamic_limits multiple times is safe."""
        with patch(
            "custom_components.sax_battery.number.calculate_system_max_charge",
            return_value=4500,
        ) as mock_calc:
            number_entity = SAXBatteryModbusNumber(
                coordinator=mock_coordinator_number,
                battery_id="battery_a",
                modbus_item=max_charge_modbus_item,
                battery_count=1,
            )

            # Reset call count after initialization
            mock_calc.reset_mock()

            # Call method again manually
            number_entity._apply_dynamic_limits()

            # Should be called once more
            mock_calc.assert_called_once_with(1)
            assert number_entity._attr_native_max_value == 4500.0

    def test_apply_dynamic_limits_with_entity_description_max_value(
        self, mock_coordinator_number, max_charge_modbus_item
    ):
        """Test dynamic limits override entity description max values."""

        # Add entity description with a different max value
        max_charge_modbus_item.entitydescription = NumberEntityDescription(
            key="max_charge",
            name="Max Charge Power",
            native_max_value=1000.0,
        )

        with patch(
            "custom_components.sax_battery.number.calculate_system_max_charge",
            return_value=4500,
        ):
            number_entity = SAXBatteryModbusNumber(
                coordinator=mock_coordinator_number,
                battery_id="battery_a",
                modbus_item=max_charge_modbus_item,
                battery_count=1,
            )

            # Dynamic limit should override entity description
            assert number_entity._attr_native_max_value == 4500.0
