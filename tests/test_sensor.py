"""Test SAX Battery sensor platform."""

from __future__ import annotations

import logging
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from custom_components.sax_battery.const import (
    DOMAIN,
    SAX_COMBINED_SOC,
    SAX_CUMULATIVE_ENERGY_CONSUMED,
    SAX_CUMULATIVE_ENERGY_PRODUCED,
    SAX_ENERGY_CONSUMED,
    SAX_ENERGY_PRODUCED,
    SAX_SOC,
)
from custom_components.sax_battery.coordinator import SAXBatteryCoordinator
from custom_components.sax_battery.enums import DeviceConstants, TypeConstants
from custom_components.sax_battery.items import ModbusItem, SAXItem
from custom_components.sax_battery.sensor import (
    SAXBatteryCalculatedSensor,
    SAXBatteryModbusSensor,
    async_setup_entry,
    calculate_combined_soc,
    calculate_cumulative_energy_consumed,
    calculate_cumulative_energy_produced,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def create_mock_coordinator(data: dict[str, float | None]) -> MagicMock:
    """Create properly typed mock coordinator for tests."""
    mock_coordinator = MagicMock()
    mock_coordinator.data = data
    mock_coordinator.battery_id = "battery_a"
    # Create sax_data mock with get_device_info method
    mock_sax_data = MagicMock()
    mock_sax_data.get_device_info.return_value = {"name": "Test Battery"}
    mock_coordinator.sax_data = mock_sax_data
    mock_coordinator.last_update_success_time = MagicMock()
    return mock_coordinator


@pytest.fixture
def mock_coordinator_sensor():
    """Create mock coordinator for sensor tests."""
    return create_mock_coordinator({"sax_temperature": 25.5})


@pytest.fixture
def temperature_modbus_item_sensor():
    """Create temperature modbus item for testing."""
    return ModbusItem(
        name="sax_temperature",
        device=DeviceConstants.SYS,
        mtype=TypeConstants.SENSOR,
        address=40117,
        entitydescription=SensorEntityDescription(
            key="temperature",
            name="Sax Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
    )


@pytest.fixture
def power_modbus_item_sensor():
    """Create power modbus item for testing."""
    return ModbusItem(
        name="sax_power",
        device=DeviceConstants.SYS,
        mtype=TypeConstants.SENSOR,
        address=40001,
        entitydescription=SensorEntityDescription(
            key="power",
            name="Sax Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.WATT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
    )


@pytest.fixture
def percentage_modbus_item_sensor():
    """Create percentage modbus item for testing."""
    return ModbusItem(
        name="sax_soc",
        device=DeviceConstants.SYS,
        mtype=TypeConstants.SENSOR,
        address=40010,
        entitydescription=SensorEntityDescription(
            key="soc",
            name="Sax SOC",
            device_class=SensorDeviceClass.BATTERY,
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
    )


@pytest.fixture
def mock_config_entry_sensor():
    """Create mock config entry."""
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_id"
    mock_entry.data = {"battery_count": 1}
    return mock_entry


@pytest.fixture
def mock_sax_data_sensor():
    """Create mock SAX data."""
    return MagicMock()


class TestCalculationFunctions:
    """Test calculation functions for SAX Battery calculated sensors."""

    def test_calculate_combined_soc_single_battery(self) -> None:
        """Test combined SOC calculation with single battery."""
        mock_coordinator = create_mock_coordinator({SAX_SOC: 85.5})

        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coordinator)}
        result = calculate_combined_soc(coordinators)

        assert result == 85.5

    def test_calculate_combined_soc_multiple_batteries(self) -> None:
        """Test combined SOC calculation with multiple batteries."""
        mock_coord_a = create_mock_coordinator({SAX_SOC: 80.0})
        mock_coord_b = create_mock_coordinator({SAX_SOC: 90.0})

        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
        }
        result = calculate_combined_soc(coordinators)

        assert result == 85.0  # (80 + 90) / 2

    def test_calculate_combined_soc_missing_data(self) -> None:
        """Test combined SOC calculation with missing data."""
        mock_coordinator = create_mock_coordinator({})

        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coordinator)}
        result = calculate_combined_soc(coordinators)

        assert result is None

    def test_calculate_combined_soc_mixed_data(self) -> None:
        """Test combined SOC calculation with mixed valid/invalid data."""
        mock_coord_a = create_mock_coordinator({SAX_SOC: 75.0})
        mock_coord_b = create_mock_coordinator({SAX_SOC: None})
        mock_coord_c = create_mock_coordinator({SAX_SOC: 85.0})

        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
            "battery_c": cast(SAXBatteryCoordinator, mock_coord_c),
        }
        result = calculate_combined_soc(coordinators)

        assert result == 80.0  # (75 + 85) / 2

    def test_calculate_cumulative_energy_produced_single_battery(self) -> None:
        """Test cumulative energy produced calculation with single battery."""
        mock_coordinator = create_mock_coordinator({SAX_ENERGY_PRODUCED: 12500.0})

        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coordinator)}
        result = calculate_cumulative_energy_produced(coordinators)

        assert result == 12500.0

    def test_calculate_cumulative_energy_produced_multiple_batteries(self) -> None:
        """Test cumulative energy produced calculation with multiple batteries."""
        mock_coord_a = create_mock_coordinator({SAX_ENERGY_PRODUCED: 10000.0})
        mock_coord_b = create_mock_coordinator({SAX_ENERGY_PRODUCED: 15000.0})

        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
        }
        result = calculate_cumulative_energy_produced(coordinators)

        assert result == 25000.0

    def test_calculate_cumulative_energy_consumed_single_battery(self) -> None:
        """Test cumulative energy consumed calculation with single battery."""
        mock_coordinator = create_mock_coordinator({SAX_ENERGY_CONSUMED: 8500.0})

        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coordinator)}
        result = calculate_cumulative_energy_consumed(coordinators)

        assert result == 8500.0

    def test_calculate_cumulative_energy_consumed_multiple_batteries(self) -> None:
        """Test cumulative energy consumed calculation with multiple batteries."""
        mock_coord_a = create_mock_coordinator({SAX_ENERGY_CONSUMED: 7000.0})
        mock_coord_b = create_mock_coordinator({SAX_ENERGY_CONSUMED: 9000.0})

        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
        }
        result = calculate_cumulative_energy_consumed(coordinators)

        assert result == 16000.0


class TestSAXBatteryModbusSensor:
    """Test SAX Battery modbus sensor."""

    def test_modbus_sensor_init(
        self, mock_coordinator_sensor, temperature_modbus_item_sensor
    ) -> None:
        """Test modbus sensor entity initialization."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item_sensor,
        )

        assert sensor._battery_id == "battery_a"
        assert sensor._modbus_item == temperature_modbus_item_sensor
        assert sensor.unique_id == "sax_battery_a_temperature"
        # Name format: Sax Battery A Temperature
        assert sensor.name == "Sax Battery A Temperature"

    def test_modbus_sensor_init_with_entity_description(
        self, mock_coordinator_sensor, temperature_modbus_item_sensor
    ) -> None:
        """Test modbus sensor initialization with entity description."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item_sensor,
        )

        # Test that entity description properties are accessible
        assert sensor.device_class == SensorDeviceClass.TEMPERATURE
        assert sensor.native_unit_of_measurement == UnitOfTemperature.CELSIUS
        assert sensor.state_class == SensorStateClass.MEASUREMENT

    def test_modbus_sensor_native_value(
        self, mock_coordinator_sensor, temperature_modbus_item_sensor
    ) -> None:
        """Test modbus sensor native value."""
        mock_coordinator_sensor.data["sax_temperature"] = 25.5

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item_sensor,
        )

        assert sensor.native_value == 25.5

    def test_modbus_sensor_native_value_missing_data(
        self, mock_coordinator_sensor, temperature_modbus_item_sensor
    ) -> None:
        """Test modbus sensor native value when data is missing."""
        mock_coordinator_sensor.data = {}

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item_sensor,
        )

        assert sensor.native_value is None

    def test_modbus_sensor_extra_state_attributes(
        self, mock_coordinator_sensor, temperature_modbus_item_sensor
    ) -> None:
        """Test modbus sensor extra state attributes."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item_sensor,
        )

        attributes = sensor.extra_state_attributes
        assert attributes is not None
        assert attributes["battery_id"] == "battery_a"
        assert attributes["modbus_address"] == 40117
        assert "last_update" in attributes
        assert "raw_value" in attributes

    def test_modbus_sensor_device_info(
        self, mock_coordinator_sensor, temperature_modbus_item_sensor
    ) -> None:
        """Test modbus sensor device info."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item_sensor,
        )

        device_info = sensor.device_info
        assert device_info is not None
        mock_coordinator_sensor.sax_data.get_device_info.assert_called_once_with(
            "battery_a"
        )

    def test_modbus_sensor_percentage_format(
        self, mock_coordinator_sensor, percentage_modbus_item_sensor
    ) -> None:
        """Test modbus sensor with percentage format."""
        mock_coordinator_sensor.data["sax_soc"] = 85

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=percentage_modbus_item_sensor,
        )

        assert sensor.native_value == 85
        assert sensor.native_unit_of_measurement == PERCENTAGE
        assert sensor.device_class == SensorDeviceClass.BATTERY
        assert sensor.name == "Sax Battery A SOC"

    def test_modbus_sensor_unique_id_removes_sax_prefix(
        self, mock_coordinator_sensor, power_modbus_item_sensor
    ) -> None:
        """Test modbus sensor unique ID removes sax prefix correctly."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_b",
            modbus_item=power_modbus_item_sensor,
        )

        # Should remove "sax_" from "sax_power" leaving "power"
        assert sensor.unique_id == "sax_battery_b_power"
        assert sensor.name == "Sax Battery B Power"

    def test_modbus_sensor_no_coordinator_data(
        self, mock_coordinator_sensor, temperature_modbus_item_sensor
    ) -> None:
        """Test modbus sensor with no coordinator data."""
        mock_coordinator_sensor.data = None

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item_sensor,
        )

        assert sensor.native_value is None


class TestSAXBatteryCalculatedSensor:
    """Test SAX Battery calculated sensor."""

    def test_calc_sensor_init(self) -> None:
        """Test calculated sensor entity initialization."""
        mock_coordinator = create_mock_coordinator({})

        calc_item = SAXItem(
            name=SAX_COMBINED_SOC,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key=SAX_COMBINED_SOC,
                name="Sax Combined SOC",
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=PERCENTAGE,
            ),
        )

        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coordinator)}

        sensor = SAXBatteryCalculatedSensor(
            coordinator=mock_coordinator,
            sax_item=calc_item,
            coordinators=coordinators,
        )

        assert sensor._sax_item == calc_item
        assert sensor._coordinators == coordinators
        # Unique ID should match the actual implementation
        assert sensor.unique_id == SAX_COMBINED_SOC
        # Name format: Sax Combined SOC (without battery prefix for system items)
        assert sensor.name == "Sax Combined SOC"

    def test_calc_sensor_combined_soc_calculation(self) -> None:
        """Test calculated sensor SOC calculation."""
        mock_coord_a = create_mock_coordinator({SAX_SOC: 80.0})
        mock_coord_b = create_mock_coordinator({SAX_SOC: 90.0})

        calc_item = SAXItem(
            name=SAX_COMBINED_SOC,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="sax_combined_soc",
                name="Sax Combined SOC",
                device_class=SensorDeviceClass.BATTERY,
            ),
        )

        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
        }

        sensor = SAXBatteryCalculatedSensor(
            coordinator=mock_coord_a,
            sax_item=calc_item,
            coordinators=coordinators,
        )

        assert sensor.native_value == 85.0  # (80 + 90) / 2

    def test_calc_sensor_cumulative_energy_produced_calculation(self) -> None:
        """Test calculated sensor cumulative energy produced calculation."""
        mock_coord_a = create_mock_coordinator({SAX_ENERGY_PRODUCED: 10000.0})
        mock_coord_b = create_mock_coordinator({SAX_ENERGY_PRODUCED: 15000.0})

        calc_item = SAXItem(
            name=SAX_CUMULATIVE_ENERGY_PRODUCED,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="cumulative_energy_produced",
                name="Sax Cumulative Energy Produced",
                device_class=SensorDeviceClass.ENERGY,
                native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            ),
        )

        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
        }

        sensor = SAXBatteryCalculatedSensor(
            coordinator=mock_coord_a,
            sax_item=calc_item,
            coordinators=coordinators,
        )

        assert sensor.native_value == 25000.0  # 10000 + 15000

    def test_calc_sensor_cumulative_energy_consumed_calculation(self) -> None:
        """Test calculated sensor cumulative energy consumed calculation."""
        mock_coord_a = create_mock_coordinator({SAX_ENERGY_CONSUMED: 8000.0})
        mock_coord_b = create_mock_coordinator({SAX_ENERGY_CONSUMED: 12000.0})

        calc_item = SAXItem(
            name=SAX_CUMULATIVE_ENERGY_CONSUMED,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="cumulative_energy_consumed",
                name="Sax Cumulative Energy Consumed",
                device_class=SensorDeviceClass.ENERGY,
                native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            ),
        )

        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
        }

        sensor = SAXBatteryCalculatedSensor(
            coordinator=mock_coord_a,
            sax_item=calc_item,
            coordinators=coordinators,
        )

        assert sensor.native_value == 20000.0  # 8000 + 12000

    def test_calc_sensor_fallback_to_coordinator_data(self) -> None:
        """Test calculated sensor fallback to coordinator data for unknown items."""
        mock_coordinator = create_mock_coordinator({"sax_unknown_item": 42.0})

        calc_item = SAXItem(
            name="sax_unknown_item",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="unknown_item",
                name="Sax Unknown Item",
            ),
        )

        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coordinator)}

        sensor = SAXBatteryCalculatedSensor(
            coordinator=mock_coordinator,
            sax_item=calc_item,
            coordinators=coordinators,
        )

        assert sensor.native_value == 42.0

    def test_calc_sensor_extra_state_attributes(self) -> None:
        """Test calculated sensor extra state attributes."""
        mock_coordinator = create_mock_coordinator({})

        calc_item = SAXItem(
            name=SAX_COMBINED_SOC,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="combined_soc",
                name="Sax Combined SOC",
            ),
        )

        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coordinator),
            "battery_b": cast(SAXBatteryCoordinator, create_mock_coordinator({})),
        }

        sensor = SAXBatteryCalculatedSensor(
            coordinator=mock_coordinator,
            sax_item=calc_item,
            coordinators=coordinators,
        )

        attributes = sensor.extra_state_attributes
        assert attributes is not None
        assert attributes["battery_id"] == "battery_a"
        assert attributes["calculation_type"] == "function_based"
        assert attributes["calculation_function"] == SAX_COMBINED_SOC
        assert attributes["battery_count"] == 2
        assert "last_update" in attributes

    def test_calc_sensor_native_value_missing_data(self) -> None:
        """Test calculated sensor native value when calculation function returns None."""
        mock_coordinator = create_mock_coordinator({})

        calc_item = SAXItem(
            name=SAX_COMBINED_SOC,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="combined_soc",
                name="Sax Combined SOC",
            ),
        )

        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coordinator)}

        sensor = SAXBatteryCalculatedSensor(
            coordinator=mock_coordinator,
            sax_item=calc_item,
            coordinators=coordinators,
        )

        assert sensor.native_value is None


class TestSensorEntityConfiguration:
    """Test sensor entity configuration variations."""

    def test_sensor_name_formatting_different_batteries(
        self, mock_coordinator_sensor, temperature_modbus_item_sensor
    ) -> None:
        """Test sensor name formatting for different battery IDs."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_c",
            modbus_item=temperature_modbus_item_sensor,
        )

        assert sensor.name == "Sax Battery C Temperature"
        assert sensor.unique_id == "sax_battery_c_temperature"

    def test_sensor_name_handles_entity_description_prefix(
        self, mock_coordinator_sensor
    ) -> None:
        """Test sensor name handling when entity description has Sax prefix."""
        item_with_sax_prefix = ModbusItem(
            name="sax_custom_sensor",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.SENSOR,
            entitydescription=SensorEntityDescription(
                key="custom_sensor",
                name="Sax Custom Power Sensor",  # Has "Sax " prefix
            ),
        )

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=item_with_sax_prefix,
        )

        # Should remove "Sax " from entity description name and add battery info
        assert sensor.name == "Sax Battery A Custom Power Sensor"

    def test_sensor_extra_state_attributes_no_data(
        self, mock_coordinator_sensor, temperature_modbus_item_sensor
    ) -> None:
        """Test extra state attributes when no coordinator data."""
        mock_coordinator_sensor.data = None

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item_sensor,
        )

        attributes = sensor.extra_state_attributes
        assert attributes is not None
        assert attributes["battery_id"] == "battery_a"
        assert attributes["raw_value"] is None

    def test_sensor_with_no_coordinator_data(
        self, mock_coordinator_sensor, temperature_modbus_item_sensor
    ) -> None:
        """Test sensor behavior with no coordinator data."""
        mock_coordinator_sensor.data = None

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item_sensor,
        )

        assert sensor.native_value is None


class TestSensorErrorHandling:
    """Test sensor error handling and edge cases."""

    def test_modbus_sensor_handles_missing_entity_description(
        self, mock_coordinator_sensor
    ) -> None:
        """Test modbus sensor with missing entity description."""
        item_no_desc = ModbusItem(
            name="sax_no_desc",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.SENSOR,
            # No entitydescription set
        )

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=item_no_desc,
        )

        # Should handle missing entity description gracefully
        assert sensor.unique_id == "sax_battery_a_no_desc"
        assert sensor.name == "Sax Battery A no_desc"

    def test_calculated_sensor_system_device_info(self) -> None:
        """Test calculated sensor uses system device info."""
        mock_coordinator = create_mock_coordinator({})

        calc_item = SAXItem(
            name=SAX_COMBINED_SOC,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="combined_soc",
                name="Sax Combined SOC",
            ),
        )

        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coordinator)}

        sensor = SAXBatteryCalculatedSensor(  # noqa: F841
            coordinator=mock_coordinator,
            sax_item=calc_item,
            coordinators=coordinators,
        )

        # Verify it calls get_device_info with "system"
        mock_coordinator.sax_data.get_device_info.assert_called_once_with("system")

    def test_calculation_functions_handle_empty_coordinators(self) -> None:
        """Test calculation functions with empty coordinator dict."""
        assert calculate_combined_soc({}) is None
        assert calculate_cumulative_energy_produced({}) is None
        assert calculate_cumulative_energy_consumed({}) is None

    def test_calculation_functions_handle_none_values(self) -> None:
        """Test calculation functions with None data values."""
        mock_coordinator = create_mock_coordinator({SAX_SOC: None})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coordinator)}

        assert calculate_combined_soc(coordinators) is None


class TestSensorPlatformSetup:
    """Test sensor platform setup."""

    async def test_async_setup_entry_success(
        self, hass: HomeAssistant, mock_config_entry_sensor, mock_sax_data_sensor
    ) -> None:
        """Test successful setup of sensor entries."""
        # Mock coordinators
        mock_coordinator = MagicMock(spec=SAXBatteryCoordinator)
        mock_coordinator.sax_data = MagicMock()
        mock_coordinator.sax_data.get_device_info.return_value = {
            "name": "Test Battery"
        }

        # Mock sensor items for battery with proper entity descriptions
        mock_modbus_item = ModbusItem(
            name="sax_test_sensor",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.SENSOR,
            address=100,
            entitydescription=SensorEntityDescription(
                key="test_sensor",
                name="Test Sensor",
                device_class=SensorDeviceClass.POWER,
            ),
        )
        mock_sax_item = SAXItem(
            name=SAX_COMBINED_SOC,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="combined_soc",
                name="Sax Combined SOC",
                device_class=SensorDeviceClass.BATTERY,
            ),
        )

        # Mock the filter functions to return our test items
        def mock_filter_items_by_type(items, item_type, config_entry, battery_id):
            if item_type == TypeConstants.SENSOR:
                return [mock_modbus_item]
            return []

        def mock_filter_sax_items_by_type(items, item_type):
            if item_type == TypeConstants.SENSOR:
                return [mock_sax_item]
            return []

        mock_sax_data_sensor.get_modbus_items_for_battery.return_value = [
            mock_modbus_item
        ]
        mock_sax_data_sensor.get_sax_items_for_battery.return_value = [mock_sax_item]

        # Store mock data in hass
        hass.data[DOMAIN] = {
            mock_config_entry_sensor.entry_id: {
                "coordinators": {"battery_a": mock_coordinator},
                "sax_data": mock_sax_data_sensor,
            }
        }

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        # Patch the filter functions to ensure they return our test items
        with (
            patch(
                "custom_components.sax_battery.sensor.filter_items_by_type",
                side_effect=mock_filter_items_by_type,
            ),
            patch(
                "custom_components.sax_battery.sensor.filter_sax_items_by_type",
                side_effect=mock_filter_sax_items_by_type,
            ),
        ):
            await async_setup_entry(hass, mock_config_entry_sensor, mock_add_entities)

        # Should have created two entities - one modbus, one calculated
        assert len(entities) == 2
        assert isinstance(entities[0], SAXBatteryModbusSensor)
        assert isinstance(entities[1], SAXBatteryCalculatedSensor)

    async def test_async_setup_entry_no_coordinators(
        self, hass: HomeAssistant, mock_config_entry_sensor, mock_sax_data_sensor
    ) -> None:
        """Test setup with no coordinators."""
        # Store mock data in hass with no coordinators structure
        hass.data[DOMAIN] = {
            mock_config_entry_sensor.entry_id: {
                "coordinators": {},
                "sax_data": mock_sax_data_sensor,
            }
        }

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        await async_setup_entry(hass, mock_config_entry_sensor, mock_add_entities)

        # Should have no entities when no coordinators
        assert len(entities) == 0

    async def test_async_setup_entry_no_sensor_items(
        self, hass: HomeAssistant, mock_config_entry_sensor, mock_sax_data_sensor
    ) -> None:
        """Test setup with no sensor items."""
        # Mock coordinator but no sensor items
        mock_coordinator = MagicMock(spec=SAXBatteryCoordinator)
        mock_coordinator.sax_data = MagicMock()
        mock_coordinator.sax_data.get_device_info.return_value = {
            "name": "Test Battery"
        }

        mock_sax_data_sensor.get_modbus_items_for_battery.return_value = []
        mock_sax_data_sensor.get_sax_items_for_battery.return_value = []

        # Store mock data in hass
        hass.data[DOMAIN] = {
            mock_config_entry_sensor.entry_id: {
                "coordinators": {"battery_a": mock_coordinator},
                "sax_data": mock_sax_data_sensor,
            }
        }

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        await async_setup_entry(hass, mock_config_entry_sensor, mock_add_entities)

        # Should have no entities when no sensor items
        assert len(entities) == 0

    async def test_async_setup_entry_mixed_item_types(
        self, hass: HomeAssistant, mock_config_entry_sensor, mock_sax_data_sensor
    ) -> None:
        """Test setup with mixed item types - only sensor items should be created."""
        # Mock coordinator
        mock_coordinator = MagicMock(spec=SAXBatteryCoordinator)
        mock_coordinator.sax_data = MagicMock()
        mock_coordinator.sax_data.get_device_info.return_value = {
            "name": "Test Battery"
        }

        # Mock mixed items - only sensors should be created
        sensor_item = ModbusItem(
            name="sax_test_sensor",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.SENSOR,
            address=100,
            entitydescription=SensorEntityDescription(
                key="test_sensor",
                name="Test Sensor",
            ),
        )
        switch_item = ModbusItem(
            name="sax_test_switch",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.SWITCH,
        )
        calc_item = SAXItem(
            name=SAX_COMBINED_SOC,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="combined_soc",
                name="Sax Combined SOC",
            ),
        )
        non_calc_item = SAXItem(
            name="sax_test_switch_sax",
            mtype=TypeConstants.SWITCH,
            device=DeviceConstants.SYS,
        )

        # Mock the filter functions to return appropriate items
        def mock_filter_items_by_type(items, item_type, config_entry, battery_id):
            if item_type == TypeConstants.SENSOR:
                return [sensor_item]
            return []

        def mock_filter_sax_items_by_type(items, item_type):
            if item_type == TypeConstants.SENSOR:
                return [calc_item]
            return []

        mock_sax_data_sensor.get_modbus_items_for_battery.return_value = [
            sensor_item,
            switch_item,
        ]
        mock_sax_data_sensor.get_sax_items_for_battery.return_value = [
            calc_item,
            non_calc_item,
        ]

        # Store mock data in hass
        hass.data[DOMAIN] = {
            mock_config_entry_sensor.entry_id: {
                "coordinators": {"battery_a": mock_coordinator},
                "sax_data": mock_sax_data_sensor,
            }
        }

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        # Patch the filter functions to ensure they return filtered items
        with (
            patch(
                "custom_components.sax_battery.sensor.filter_items_by_type",
                side_effect=mock_filter_items_by_type,
            ),
            patch(
                "custom_components.sax_battery.sensor.filter_sax_items_by_type",
                side_effect=mock_filter_sax_items_by_type,
            ),
        ):
            await async_setup_entry(hass, mock_config_entry_sensor, mock_add_entities)

        # Should have created only sensor entities
        assert len(entities) == 2
        assert isinstance(entities[0], SAXBatteryModbusSensor)
        assert isinstance(entities[1], SAXBatteryCalculatedSensor)
        assert entities[0]._modbus_item == sensor_item
        assert entities[1]._sax_item == calc_item
