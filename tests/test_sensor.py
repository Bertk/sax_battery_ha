"""Test SAX Battery sensor platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.sax_battery.coordinator import SAXBatteryCoordinator
from custom_components.sax_battery.enums import DeviceConstants, TypeConstants
from custom_components.sax_battery.items import ModbusItem, SAXItem
from custom_components.sax_battery.sensor import (
    SAXBatteryCalcSensor,
    SAXBatteryModbusSensor,
    async_setup_entry,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_coordinator_sensor():
    """Create mock coordinator for sensor tests."""
    coordinator = MagicMock(spec=SAXBatteryCoordinator)
    coordinator.last_update_success = True
    coordinator.last_update_success_time = "2024-01-01T00:00:00+00:00"
    coordinator.data = {
        "sax_temperature": 25.5,
        "sax_soc": 85,
        "sax_power": 1500,
        # Use the original name without "(Calculated)" suffix
        "sax_combined_power": 3000,
    }

    # Mock the sax_data attribute and its methods
    mock_sax_data = MagicMock()
    mock_sax_data.get_device_info.return_value = {
        "identifiers": {("sax_battery", "battery_a")},
        "name": "SAX Battery A",
        "manufacturer": "SAX",
        "model": "SAX Battery",
    }
    coordinator.sax_data = mock_sax_data
    return coordinator


@pytest.fixture
def temperature_modbus_item():
    """Create temperature modbus item with proper entity description."""
    return ModbusItem(
        address=40117,
        name="sax_temperature",
        mtype=TypeConstants.SENSOR,
        device=DeviceConstants.SYS,
        battery_slave_id=40,
        factor=10.0,
        entitydescription=SensorEntityDescription(
            key="temperature",
            name="Sax Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            suggested_display_precision=1,
        ),
    )


@pytest.fixture
def percentage_modbus_item():
    """Create percentage modbus item with proper entity description."""
    return ModbusItem(
        address=46,
        name="sax_soc",
        mtype=TypeConstants.SENSOR,
        device=DeviceConstants.SYS,
        battery_slave_id=64,
        factor=1.0,
        entitydescription=SensorEntityDescription(
            key="soc",
            name="Sax SOC",
            device_class=SensorDeviceClass.BATTERY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
        ),
    )


@pytest.fixture
def power_modbus_item():
    """Create power modbus item with proper entity description."""
    return ModbusItem(
        address=47,
        name="sax_power",
        mtype=TypeConstants.SENSOR,
        device=DeviceConstants.SYS,
        battery_slave_id=64,
        factor=1.0,
        entitydescription=SensorEntityDescription(
            key="power",
            name="Sax Power",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPower.WATT,
        ),
    )


@pytest.fixture
def modbus_item_without_description():
    """Create modbus item without entity description."""
    return ModbusItem(
        address=100,
        name="sax_test_sensor",
        mtype=TypeConstants.SENSOR,
        device=DeviceConstants.SYS,
        entitydescription=None,
    )


@pytest.fixture
def calc_sax_item():
    """Create calculated SAX item with proper entity description."""
    return SAXItem(
        name="sax_combined_power",
        mtype=TypeConstants.SENSOR_CALC,
        device=DeviceConstants.SYS,
        entitydescription=SensorEntityDescription(
            key="combined_power",
            name="Sax Combined Power",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPower.WATT,
        ),
    )


@pytest.fixture
def mock_config_entry_sensor():
    """Create mock config entry for sensor tests."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {
        "host": "192.168.1.100",
        "port": 502,
    }
    return entry


class TestSAXBatteryModbusSensor:
    """Test SAX Battery modbus sensor."""

    def test_modbus_sensor_init(
        self, mock_coordinator_sensor, temperature_modbus_item
    ) -> None:
        """Test modbus sensor entity initialization."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item,
        )

        assert sensor._battery_id == "battery_a"
        assert sensor._modbus_item == temperature_modbus_item
        assert sensor.unique_id == "sax_battery_a_temperature"
        assert sensor.name == "Sax Battery A Temperature"

    def test_modbus_sensor_init_with_entity_description(
        self, mock_coordinator_sensor, temperature_modbus_item
    ) -> None:
        """Test modbus sensor initialization with entity description."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item,
        )

        # Test that entity description properties are accessible
        assert sensor.device_class == SensorDeviceClass.TEMPERATURE
        assert sensor.native_unit_of_measurement == UnitOfTemperature.CELSIUS
        assert sensor.state_class == SensorStateClass.MEASUREMENT

    def test_modbus_sensor_native_value(
        self, mock_coordinator_sensor, temperature_modbus_item
    ) -> None:
        """Test modbus sensor native value."""
        mock_coordinator_sensor.data["sax_temperature"] = 25.5

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item,
        )

        assert sensor.native_value == 25.5

    def test_modbus_sensor_native_value_missing_data(
        self, mock_coordinator_sensor, temperature_modbus_item
    ) -> None:
        """Test modbus sensor native value when data is missing."""
        mock_coordinator_sensor.data = {}

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item,
        )

        assert sensor.native_value is None

    def test_modbus_sensor_extra_state_attributes(
        self, mock_coordinator_sensor, temperature_modbus_item
    ) -> None:
        """Test modbus sensor extra state attributes."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item,
        )

        attributes = sensor.extra_state_attributes
        assert attributes is not None
        assert attributes["battery_id"] == "battery_a"
        assert attributes["modbus_address"] == 40117
        assert "last_update" in attributes

    def test_modbus_sensor_device_info(
        self, mock_coordinator_sensor, temperature_modbus_item
    ) -> None:
        """Test modbus sensor device info."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item,
        )

        device_info = sensor.device_info
        assert device_info is not None
        mock_coordinator_sensor.sax_data.get_device_info.assert_called_once_with(
            "battery_a"
        )

    def test_modbus_sensor_percentage_format(
        self, mock_coordinator_sensor, percentage_modbus_item
    ) -> None:
        """Test modbus sensor with percentage format."""
        mock_coordinator_sensor.data["sax_soc"] = 85

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=percentage_modbus_item,
        )

        assert sensor.native_value == 85
        assert sensor.native_unit_of_measurement == PERCENTAGE
        assert sensor.device_class == SensorDeviceClass.BATTERY
        assert sensor.name == "Sax Battery A SOC"

    def test_modbus_sensor_unique_id_removes_sax_prefix(
        self, mock_coordinator_sensor, power_modbus_item
    ) -> None:
        """Test modbus sensor unique ID removes sax prefix correctly."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_b",
            modbus_item=power_modbus_item,
        )

        # Should remove "sax_" from "sax_power" leaving "power"
        assert sensor.unique_id == "sax_battery_b_power"
        assert sensor.name == "Sax Battery B Power"


class TestSAXBatteryCalcSensor:
    """Test SAX Battery calculated sensor."""

    def test_calc_sensor_init(self, mock_coordinator_sensor, calc_sax_item) -> None:
        """Test calculated sensor entity initialization."""
        sensor = SAXBatteryCalcSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            sax_item=calc_sax_item,
        )

        assert sensor._battery_id == "battery_a"
        assert sensor._sax_item == calc_sax_item
        # Unique ID should NOT include "(Calculated)" suffix
        assert sensor.unique_id == "sax_battery_a_combined_power"
        # Display name SHOULD include "(Calculated)" suffix
        assert sensor.name == "Sax Battery A Combined Power (Calculated)"

    def test_calc_sensor_init_with_entity_description(
        self, mock_coordinator_sensor, calc_sax_item
    ) -> None:
        """Test calculated sensor initialization with entity description."""
        sensor = SAXBatteryCalcSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            sax_item=calc_sax_item,
        )

        # Test that entity description properties are accessible
        assert sensor.device_class == SensorDeviceClass.POWER
        assert sensor.native_unit_of_measurement == UnitOfPower.WATT
        assert sensor.state_class == SensorStateClass.MEASUREMENT

    def test_calc_sensor_native_value(
        self, mock_coordinator_sensor, calc_sax_item
    ) -> None:
        """Test calculated sensor native value."""
        # The key in coordinator data should match the original SAXItem name
        mock_coordinator_sensor.data["sax_combined_power"] = 3000

        sensor = SAXBatteryCalcSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            sax_item=calc_sax_item,
        )

        assert sensor.native_value == 3000

    def test_calc_sensor_native_value_missing_data(
        self, mock_coordinator_sensor, calc_sax_item
    ) -> None:
        """Test calculated sensor native value when data is missing."""
        mock_coordinator_sensor.data = {}

        sensor = SAXBatteryCalcSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            sax_item=calc_sax_item,
        )

        assert sensor.native_value is None

    def test_calc_sensor_extra_state_attributes(
        self, mock_coordinator_sensor, calc_sax_item
    ) -> None:
        """Test calculated sensor extra state attributes."""
        sensor = SAXBatteryCalcSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            sax_item=calc_sax_item,
        )

        attributes = sensor.extra_state_attributes
        assert attributes is not None
        assert attributes["battery_id"] == "battery_a"
        assert attributes["calculation_type"] == "sax_item"
        assert "last_update" in attributes

    def test_calc_sensor_name_with_calculated_suffix(
        self, mock_coordinator_sensor
    ) -> None:
        """Test calculated sensor name includes (Calculated) suffix properly."""
        calc_item = SAXItem(
            name="sax_test_power",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="test_power",
                name="Sax Test Power",
            ),
        )

        sensor = SAXBatteryCalcSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            sax_item=calc_item,
        )

        # Display name should include the "(Calculated)" suffix
        assert sensor.name == "Sax Battery A Test Power (Calculated)"
        # Unique ID should NOT include the "(Calculated)" suffix
        assert sensor.unique_id == "sax_battery_a_test_power"


class TestSensorPlatformSetup:
    """Test sensor platform setup."""

    async def test_async_setup_entry_success(
        self, hass: HomeAssistant, mock_config_entry_sensor, mock_sax_data
    ) -> None:
        """Test successful setup of sensor entries."""
        # Mock coordinators
        mock_coordinator = MagicMock(spec=SAXBatteryCoordinator)
        mock_sax_data.coordinators = {"battery_a": mock_coordinator}

        # Mock sensor items for battery with proper entity descriptions
        mock_modbus_item = ModbusItem(
            name="sax_test_sensor",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.SENSOR,
            entitydescription=SensorEntityDescription(
                key="test_sensor",
                name="Test Sensor",
                device_class=SensorDeviceClass.POWER,
            ),
        )
        mock_sax_item = SAXItem(
            name="sax_test_calc",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="test_calc",
                name="Test Calculated Sensor",
                device_class=SensorDeviceClass.ENERGY,
            ),
        )

        mock_sax_data.get_modbus_items_for_battery.return_value = [mock_modbus_item]
        mock_sax_data.get_sax_items_for_battery.return_value = [mock_sax_item]

        # Store mock data in hass
        hass.data["sax_battery"] = {
            mock_config_entry_sensor.entry_id: {
                "coordinators": {"battery_a": mock_coordinator},
                "sax_data": mock_sax_data,
            }
        }

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        await async_setup_entry(hass, mock_config_entry_sensor, mock_add_entities)

        # Should have created two entities - one modbus, one calculated
        assert len(entities) == 2
        assert isinstance(entities[0], SAXBatteryModbusSensor)
        assert isinstance(entities[1], SAXBatteryCalcSensor)

    async def test_async_setup_entry_no_coordinators(
        self, hass: HomeAssistant, mock_config_entry_sensor, mock_sax_data
    ) -> None:
        """Test setup with no coordinators."""
        mock_sax_data.coordinators = {}

        # Store mock data in hass
        hass.data["sax_battery"] = {mock_config_entry_sensor.entry_id: mock_sax_data}

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        await async_setup_entry(hass, mock_config_entry_sensor, mock_add_entities)

        # Should have no entities when no coordinators
        assert len(entities) == 0

    async def test_async_setup_entry_no_sensor_items(
        self, hass: HomeAssistant, mock_config_entry_sensor, mock_sax_data
    ) -> None:
        """Test setup with no sensor items."""
        # Mock coordinator but no sensor items
        mock_coordinator = MagicMock(spec=SAXBatteryCoordinator)
        mock_sax_data.coordinators = {"battery_a": mock_coordinator}
        mock_sax_data.get_modbus_items_for_battery.return_value = []
        mock_sax_data.get_sax_items_for_battery.return_value = []

        # Store mock data in hass
        hass.data["sax_battery"] = {
            mock_config_entry_sensor.entry_id: {
                "coordinators": {"battery_a": mock_coordinator},
                "sax_data": mock_sax_data,
            }
        }

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        await async_setup_entry(hass, mock_config_entry_sensor, mock_add_entities)

        # Should have no entities when no sensor items
        assert len(entities) == 0

    async def test_async_setup_entry_mixed_item_types(
        self, hass: HomeAssistant, mock_config_entry_sensor, mock_sax_data
    ) -> None:
        """Test setup with mixed item types - only sensor items should be created."""
        # Mock coordinator
        mock_coordinator = MagicMock(spec=SAXBatteryCoordinator)
        mock_sax_data.coordinators = {"battery_a": mock_coordinator}

        # Mock mixed items - only sensors should be created
        sensor_item = ModbusItem(
            name="sax_test_sensor",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.SENSOR,
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
            name="sax_test_calc",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=SensorEntityDescription(
                key="test_calc",
                name="Test Calc",
            ),
        )
        non_calc_item = SAXItem(
            name="sax_test_switch_sax",
            mtype=TypeConstants.SWITCH,
            device=DeviceConstants.SYS,
        )

        mock_sax_data.get_modbus_items_for_battery.return_value = [
            sensor_item,
            switch_item,
        ]
        mock_sax_data.get_sax_items_for_battery.return_value = [
            calc_item,
            non_calc_item,
        ]

        # Store mock data in hass
        hass.data["sax_battery"] = {
            mock_config_entry_sensor.entry_id: {
                "coordinators": {"battery_a": mock_coordinator},
                "sax_data": mock_sax_data,
            }
        }

        entities = []

        def mock_add_entities(new_entities, update_before_add=False):
            entities.extend(new_entities)

        await async_setup_entry(hass, mock_config_entry_sensor, mock_add_entities)

        # Should have created only sensor entities
        assert len(entities) == 2
        assert isinstance(entities[0], SAXBatteryModbusSensor)
        assert isinstance(entities[1], SAXBatteryCalcSensor)
        assert entities[0]._modbus_item == sensor_item
        assert entities[1]._sax_item == calc_item


class TestSensorEntityConfiguration:
    """Test sensor entity configuration variations."""

    def test_sensor_name_formatting_different_batteries(
        self, mock_coordinator_sensor, temperature_modbus_item
    ) -> None:
        """Test sensor name formatting for different battery IDs."""
        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_c",
            modbus_item=temperature_modbus_item,
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

    def test_sensor_with_no_coordinator_data(
        self, mock_coordinator_sensor, temperature_modbus_item
    ) -> None:
        """Test sensor behavior with no coordinator data."""
        mock_coordinator_sensor.data = None

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item,
        )

        assert sensor.native_value is None

    def test_sensor_extra_state_attributes_no_data(
        self, mock_coordinator_sensor, temperature_modbus_item
    ) -> None:
        """Test extra state attributes when no coordinator data."""
        mock_coordinator_sensor.data = None

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item,
        )

        attributes = sensor.extra_state_attributes
        assert attributes is not None
        assert attributes["battery_id"] == "battery_a"
        assert attributes["modbus_address"] == 40117
        assert "last_update" in attributes
