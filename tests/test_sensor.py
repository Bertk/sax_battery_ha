"""Test SAX Battery sensor platform."""

from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from custom_components.sax_battery.const import (
    CONF_BATTERY_ENABLED,
    CONF_BATTERY_HOST,
    CONF_BATTERY_IS_MASTER,
    CONF_BATTERY_PHASE,
    CONF_BATTERY_PORT,
    DESCRIPTION_BMS_UNAVAILABILITY_RATE,
    DESCRIPTION_SAX_COMBINED_SOC,
    DESCRIPTION_SAX_CUMULATIVE_ENERGY_CONSUMED,
    DESCRIPTION_SAX_CUMULATIVE_ENERGY_PRODUCED,
    DESCRIPTION_SAX_POWER,
    DESCRIPTION_SAX_SOC,
    DESCRIPTION_SAX_TEMPERATURE,
    DESCRIPTION_TXID_ERROR_RATE,
    DOMAIN,
    SAX_COMBINED_SOC,
    SAX_CUMULATIVE_ENERGY_CONSUMED,
    SAX_CUMULATIVE_ENERGY_PRODUCED,
    SAX_TEMPERATURE,
    SAXDeviceInfo,
)
from custom_components.sax_battery.coordinator import SAXBatteryCoordinator
from custom_components.sax_battery.entity_keys import (
    BMS_UNAVAILABILITY_RATE,
    SAX_POWER,
    SAX_SOC,
    TXID_ERROR_RATE,
)
from custom_components.sax_battery.enums import DeviceConstants, TypeConstants
from custom_components.sax_battery.items import ModbusItem, SAXItem
from custom_components.sax_battery.models import SAXBatteryData
from custom_components.sax_battery.sensor import (
    SAXBatteryCalculatedSensor,
    SAXBatteryCoordinatorCycleSensor,
    SAXBatteryModbusSensor,
    async_setup_entry,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    STATE_UNAVAILABLE,
    UnitOfEnergy,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import async_generate_entity_id

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
def mock_coordinator_sensor(mock_config_entry):
    """Fixture for coordinator with sensor configuration."""
    coordinator = MagicMock(spec=SAXBatteryCoordinator)
    coordinator.name = DOMAIN
    coordinator.config_entry = mock_config_entry
    coordinator.data = {}
    coordinator.last_update_success = True
    coordinator.battery_config = {
        CONF_BATTERY_HOST: "192.168.1.100",
        CONF_BATTERY_PORT: 502,
        CONF_BATTERY_IS_MASTER: True,
        CONF_BATTERY_PHASE: "L1",
    }

    # Add hass attribute (required for SAXBatteryData initialization)
    coordinator.hass = MagicMock()

    # Mock sax_data with get_unique_id_for_item that returns proper strings
    mock_sax_data = MagicMock()

    # Configure get_unique_id_for_item to return expected format
    def mock_get_unique_id(item, battery_id=None):
        """Mock unique_id generation matching SAXBatteryData pattern."""
        # Remove sax_ prefix from item name
        item_name = item.name.removeprefix("sax_")

        if battery_id:
            # Per-battery entity: sax_battery_a_temperature
            return f"sax_{battery_id}_{item_name}"
        else:  # noqa: RET505
            # Cluster entity: sax_combined_soc
            return f"sax_{item_name}"

    mock_sax_data.get_unique_id_for_item = MagicMock(side_effect=mock_get_unique_id)

    mock_sax_data.get_device_info = MagicMock(
        return_value=SAXDeviceInfo(
            manufacturer="SAX",
            model="Battery System",
            sw_version="1.0",
        )
    )

    mock_sax_data.get_entity_id_for_item = MagicMock(return_value="sensor.test_entity")

    coordinator.sax_data = mock_sax_data

    return coordinator


@pytest.fixture
def temperature_modbus_item_sensor():
    """Create temperature modbus item for testing."""
    return ModbusItem(
        name=SAX_TEMPERATURE,
        device=DeviceConstants.BESS,
        mtype=TypeConstants.SENSOR,
        address=40117,
        entitydescription=DESCRIPTION_SAX_TEMPERATURE,
    )


@pytest.fixture
def power_modbus_item_sensor():
    """Create power modbus item for testing."""
    return ModbusItem(
        name=SAX_POWER,
        device=DeviceConstants.BESS,
        mtype=TypeConstants.SENSOR,
        address=40001,
        entitydescription=DESCRIPTION_SAX_POWER,
    )


@pytest.fixture
def percentage_modbus_item_sensor():
    """Create percentage modbus item for testing."""
    return ModbusItem(
        name=SAX_SOC,
        device=DeviceConstants.BESS,
        mtype=TypeConstants.SENSOR,
        address=40010,
        entitydescription=DESCRIPTION_SAX_SOC,
    )


@pytest.fixture
def mock_config_entry_sensor():
    """Create mock config entry for sensor tests."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry_sensor"
    config_entry.data = {
        "host": "192.168.1.100",
        "port": 502,
        "batteries": {"battery_a": {"role": "master"}},
    }
    config_entry.options = {}
    return config_entry


@pytest.fixture
def mock_sax_data_sensor():
    """Create mock SAX data."""
    return MagicMock()


class TestSAXBatteryModbusSensor:
    """Test SAX Battery modbus sensor."""

    @pytest.fixture
    def mock_config_entry_sensor(self) -> MagicMock:
        """Create mock config entry for sensor tests."""
        config_entry = MagicMock()
        config_entry.entry_id = "test_sensor_entry"
        config_entry.data = {"control_power": False, "limit_power": False}
        return config_entry

    @pytest.fixture
    def mock_sax_data_sensor(self) -> MagicMock:
        """Create mock SAX data for sensor tests."""
        sax_data = MagicMock()
        sax_data.get_modbus_items_for_battery.return_value = []
        sax_data.get_sax_items_for_battery.return_value = []
        return sax_data

    @pytest.fixture
    def mock_battery_config_sensor(self) -> dict[str, Any]:
        """Create mock battery configuration for sensor tests."""
        return {
            CONF_BATTERY_HOST: "192.168.1.100",
            CONF_BATTERY_PORT: 502,
            CONF_BATTERY_ENABLED: True,
            CONF_BATTERY_PHASE: "L1",
            CONF_BATTERY_IS_MASTER: True,
        }

    async def test_async_setup_entry_with_entity_id_generation(
        self,
        hass: HomeAssistant,
        mock_config_entry_sensor,
        mock_sax_data_sensor,
        mock_battery_config_sensor,
    ) -> None:
        """Test setup entry with proper entity_id generation."""

        # Mock coordinator with battery_config attribute
        mock_coordinator = MagicMock(spec=SAXBatteryCoordinator)
        mock_coordinator.hass = hass
        mock_coordinator.battery_config = mock_battery_config_sensor

        # Create test entities with entity_id generation
        entities_created = []

        def mock_add_entities(new_entities, update_before_add=False):
            # Apply entity_id generation as Home Assistant would
            for entity in new_entities:
                if hasattr(entity, "_attr_unique_id"):
                    entity.entity_id = async_generate_entity_id(
                        f"{entity.domain}.{{}}", entity._attr_unique_id, hass=hass
                    )
            entities_created.extend(new_entities)

        # Store data and run setup
        hass.data[DOMAIN] = {
            mock_config_entry_sensor.entry_id: {
                "coordinators": {"battery_a": mock_coordinator},
                "sax_data": mock_sax_data_sensor,
            }
        }

        await async_setup_entry(hass, mock_config_entry_sensor, mock_add_entities)

        # Verify setup completed without errors
        assert len(entities_created) >= 0  # Should handle empty entity list gracefully

    def test_modbus_sensor_init(
        self,
        mock_coordinator_sensor,
        temperature_modbus_item_sensor,
        simulate_unique_id_temperature,
    ) -> None:
        """Test modbus sensor entity initialization."""
        # Don't create SAXBatteryData - use mock from coordinator

        sensor = SAXBatteryModbusSensor(
            coordinator=mock_coordinator_sensor,
            battery_id="battery_a",
            modbus_item=temperature_modbus_item_sensor,
        )

        assert sensor.name == "Temperature"
        assert sensor._battery_id == "battery_a"

        assert isinstance(sensor.device_info, SAXDeviceInfo)

        assert simulate_unique_id_temperature == "sensor.sax_battery_a_temperature"

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
            "battery_a", DeviceConstants.BESS
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
        assert sensor.name == "SOC"

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
        assert sensor.name == "Power"

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

    def test_calc_sensor_init(self, simulate_unique_id_combined_soc) -> None:
        """Test calculated sensor entity initialization."""
        mock_coordinator = create_mock_coordinator({})

        # Create a minimal SAXBatteryData instance for testing
        mock_config_entry = MagicMock()
        mock_config_entry.data = {"battery_count": 1, "master_battery": "battery_a"}

        sax_data = SAXBatteryData(mock_coordinator.hass, mock_config_entry)
        mock_coordinator.sax_data = sax_data

        calc_item = SAXItem(
            name=SAX_COMBINED_SOC,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,  # System device for cluster info
            entitydescription=DESCRIPTION_SAX_COMBINED_SOC,
        )

        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coordinator)}

        sensor = SAXBatteryCalculatedSensor(
            coordinator=mock_coordinator,
            sax_item=calc_item,
            coordinators=coordinators,
        )

        assert sensor._sax_item == calc_item
        assert sensor._coordinators == coordinators
        assert sensor.name == "Combined SOC"
        # The device info should now come from actual get_device_info method
        assert sensor.device_info["name"] == "SAX BMS"  # type: ignore[index]
        assert simulate_unique_id_combined_soc == "sensor.sax_bms_combined_soc"

    def test_calc_sensor_uses_sax_item_calculate_value(self) -> None:
        """Test calculated sensor uses SAXItem calculate_value method."""
        mock_coord_a = create_mock_coordinator({"sax_soc": 80.0})
        mock_coord_b = create_mock_coordinator({"sax_soc": 90.0})

        calc_item = SAXItem(
            name=SAX_COMBINED_SOC,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.BESS,
            entitydescription=DESCRIPTION_SAX_COMBINED_SOC,
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

        # Should use SAXItem's calculate_value method which calculates combined SOC
        assert sensor.native_value == 85.0  # (80 + 90) / 2

    def test_calc_sensor_system_device_info(self) -> None:
        """Test calculated sensor uses system device info."""
        mock_coordinator = create_mock_coordinator({})

        calc_item = SAXItem(
            name=SAX_COMBINED_SOC,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.BESS,
            entitydescription=DESCRIPTION_SAX_COMBINED_SOC,
        )

        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coordinator)}

        sensor = SAXBatteryCalculatedSensor(  # noqa: F841
            coordinator=mock_coordinator,
            sax_item=calc_item,
            coordinators=coordinators,
        )

        # Verify it calls get_device_info with "cluster"
        mock_coordinator.sax_data.get_device_info.assert_called_once_with(
            "cluster", DeviceConstants.SYS
        )


class TestCumulativeEnergySensor:
    """Test cumulative energy sensors using trapezoidal integration."""

    def _create_energy_sensor(
        self,
        sensor_name: str,
        coordinators: dict[str, Any],
        master_coordinator: Any = None,
    ) -> SAXBatteryCalculatedSensor:
        """Create a cumulative energy sensor for testing."""

        descriptions = {
            SAX_CUMULATIVE_ENERGY_PRODUCED: DESCRIPTION_SAX_CUMULATIVE_ENERGY_PRODUCED,
            SAX_CUMULATIVE_ENERGY_CONSUMED: DESCRIPTION_SAX_CUMULATIVE_ENERGY_CONSUMED,
        }

        sax_item = SAXItem(
            name=sensor_name,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=descriptions[sensor_name],
        )

        coordinator = master_coordinator or next(iter(coordinators.values()))

        return SAXBatteryCalculatedSensor(
            coordinator=coordinator,
            sax_item=sax_item,
            coordinators=coordinators,
        )

    def test_energy_produced_init_creates_integrators(self) -> None:
        """Test that energy produced sensor creates per-battery integrators."""
        mock_coord_a = create_mock_coordinator({})
        mock_coord_b = create_mock_coordinator({})
        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
        }

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        assert "battery_a" in sensor._produced_integrators
        assert "battery_b" in sensor._produced_integrators
        assert "battery_a" in sensor._consumed_integrators
        assert "battery_b" in sensor._consumed_integrators

    def test_energy_produced_with_positive_power(self) -> None:
        """Test energy produced accumulates from positive power (discharging)."""
        mock_coord = create_mock_coordinator({SAX_POWER: 1000.0})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        # First call: establishes baseline (no integration yet)
        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            _ = sensor.native_value

        # Second call: 15s later → 1000W * 15s / 3600 ≈ 4.17 Wh
        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 115.0
            result = sensor.native_value

        assert result is not None
        assert result == pytest.approx(4.17, abs=0.01)

    def test_energy_consumed_with_negative_power(self) -> None:
        """Test energy consumed accumulates from negative power (charging)."""
        mock_coord = create_mock_coordinator({SAX_POWER: -2000.0})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_CONSUMED, coordinators
        )

        # First call: establishes baseline
        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            _ = sensor.native_value

        # Second call: 15s later → abs(-2000) * 15s / 3600 ≈ 8.33 Wh
        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 115.0
            result = sensor.native_value

        assert result is not None
        assert result == pytest.approx(8.33, abs=0.01)

    def test_positive_power_does_not_accumulate_consumed(self) -> None:
        """Test positive power (discharging) does not add to consumed energy."""
        mock_coord = create_mock_coordinator({SAX_POWER: 1000.0})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_CONSUMED, coordinators
        )

        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            _ = sensor.native_value

        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 115.0
            result = sensor.native_value

        # Positive power = discharging, consumed should be 0
        assert result == 0.0

    def test_negative_power_does_not_accumulate_produced(self) -> None:
        """Test negative power (charging) does not add to produced energy."""
        mock_coord = create_mock_coordinator({SAX_POWER: -1500.0})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            _ = sensor.native_value

        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 115.0
            result = sensor.native_value

        # Negative power = charging, produced should be 0
        assert result == 0.0

    def test_multi_battery_aggregation(self) -> None:
        """Test energy aggregation across multiple batteries."""
        mock_coord_a = create_mock_coordinator({SAX_POWER: 1000.0})
        mock_coord_b = create_mock_coordinator({SAX_POWER: 2000.0})
        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
        }

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        # First call: baseline
        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            _ = sensor.native_value

        # Second call: 15s later
        # battery_a: 1000W * 15s/3600 ≈ 4.17 Wh
        # battery_b: 2000W * 15s/3600 ≈ 8.33 Wh
        # Total ≈ 12.5 Wh
        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 115.0
            result = sensor.native_value

        assert result is not None
        assert result == pytest.approx(12.5, abs=0.01)

    def test_no_coordinator_data_returns_zero(self) -> None:
        """Test energy sensor returns 0 when coordinator has no data."""
        mock_coord = create_mock_coordinator({})
        mock_coord.data = None
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        result = sensor.native_value
        assert result == 0.0

    def test_missing_power_value_skipped(self) -> None:
        """Test batteries with missing power values are skipped."""
        mock_coord_a = create_mock_coordinator({SAX_POWER: 1000.0})
        mock_coord_b = create_mock_coordinator({})  # No power data
        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
        }

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            _ = sensor.native_value

        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 115.0
            result = sensor.native_value

        # Only battery_a contributed: 1000W * 15s / 3600 ≈ 4.17 Wh
        assert result == pytest.approx(4.17, abs=0.01)

    def test_zero_power_no_accumulation(self) -> None:
        """Test zero power does not accumulate energy."""
        mock_coord = create_mock_coordinator({SAX_POWER: 0.0})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            _ = sensor.native_value

        with patch("custom_components.sax_battery.sensor.time") as mock_time:
            mock_time.monotonic.return_value = 115.0
            result = sensor.native_value

        assert result == 0.0

    def test_extra_state_attributes_produced(self) -> None:
        """Test extra state attributes include per-battery breakdown for produced."""
        mock_coord_a = create_mock_coordinator({SAX_POWER: 1000.0})
        mock_coord_b = create_mock_coordinator({SAX_POWER: 2000.0})
        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
        }

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        attrs = sensor.extra_state_attributes
        assert "attribution" in attrs
        assert "per_battery" in attrs
        assert "battery_a" in attrs["per_battery"]
        assert "battery_b" in attrs["per_battery"]

    def test_extra_state_attributes_consumed(self) -> None:
        """Test extra state attributes include per-battery breakdown for consumed."""
        mock_coord = create_mock_coordinator({SAX_POWER: -500.0})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_CONSUMED, coordinators
        )

        attrs = sensor.extra_state_attributes
        assert "per_battery" in attrs
        assert "battery_a" in attrs["per_battery"]

    def test_unknown_sensor_name_returns_none(self) -> None:
        """Test unknown calculated sensor name returns None with warning."""
        mock_coord = create_mock_coordinator({})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sax_item = SAXItem(
            name="sax_unknown_calculation",
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.SYS,
            entitydescription=None,
        )

        sensor = SAXBatteryCalculatedSensor(
            coordinator=mock_coord,
            sax_item=sax_item,
            coordinators=coordinators,
        )

        assert sensor.native_value is None

    async def test_restore_cumulative_state_produced(self, hass: HomeAssistant) -> None:
        """Test restoring cumulative energy produced state after restart."""
        mock_coord_a = create_mock_coordinator({})
        mock_coord_b = create_mock_coordinator({})
        coordinators = {
            "battery_a": cast(SAXBatteryCoordinator, mock_coord_a),
            "battery_b": cast(SAXBatteryCoordinator, mock_coord_b),
        }

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        # Mock RestoreSensor's async_get_last_state
        mock_state = MagicMock()
        mock_state.state = "1000.0"

        with patch.object(sensor, "async_get_last_state", return_value=mock_state):
            await sensor._restore_cumulative_state()

        # Value should be distributed evenly across integrators
        # 1000 Wh / 2 batteries = 500 Wh each
        assert sensor._produced_integrators["battery_a"].accumulated_wh == 500.0
        assert sensor._produced_integrators["battery_b"].accumulated_wh == 500.0
        assert sensor._get_total_produced() == 1000.0

    async def test_restore_cumulative_state_consumed(self, hass: HomeAssistant) -> None:
        """Test restoring cumulative energy consumed state after restart."""
        mock_coord = create_mock_coordinator({})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_CONSUMED, coordinators
        )

        mock_state = MagicMock()
        mock_state.state = "500.0"

        with patch.object(sensor, "async_get_last_state", return_value=mock_state):
            await sensor._restore_cumulative_state()

        assert sensor._consumed_integrators["battery_a"].accumulated_wh == 500.0
        assert sensor._get_total_consumed() == 500.0

    async def test_restore_no_previous_state(self, hass: HomeAssistant) -> None:
        """Test restoration when no previous state exists."""
        mock_coord = create_mock_coordinator({})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        with patch.object(sensor, "async_get_last_state", return_value=None):
            await sensor._restore_cumulative_state()

        assert sensor._get_total_produced() == 0.0

    async def test_restore_unavailable_state(self, hass: HomeAssistant) -> None:
        """Test restoration when previous state is unavailable."""

        mock_coord = create_mock_coordinator({})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        mock_state = MagicMock()
        mock_state.state = STATE_UNAVAILABLE

        with patch.object(sensor, "async_get_last_state", return_value=mock_state):
            await sensor._restore_cumulative_state()

        assert sensor._get_total_produced() == 0.0

    async def test_restore_invalid_state_value(self, hass: HomeAssistant) -> None:
        """Test restoration with invalid (non-numeric) state value."""
        mock_coord = create_mock_coordinator({})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        mock_state = MagicMock()
        mock_state.state = "not_a_number"

        with patch.object(sensor, "async_get_last_state", return_value=mock_state):
            await sensor._restore_cumulative_state()

        # Should not crash, just log warning
        assert sensor._get_total_produced() == 0.0

    def test_entity_description_properties(self) -> None:
        """Test energy sensor has correct entity description properties."""

        mock_coord = create_mock_coordinator({})
        coordinators = {"battery_a": cast(SAXBatteryCoordinator, mock_coord)}

        sensor = self._create_energy_sensor(
            SAX_CUMULATIVE_ENERGY_PRODUCED, coordinators
        )

        assert sensor.device_class == SensorDeviceClass.ENERGY
        assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
        assert sensor.native_unit_of_measurement == UnitOfEnergy.WATT_HOUR
        assert sensor.name == "Cumulative Energy Produced"


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

        assert sensor.unique_id == "sax_battery_c_temperature"
        assert sensor.name == "Temperature"

    def test_sensor_name_handles_entity_description_prefix(
        self, mock_coordinator_sensor
    ) -> None:
        """Test sensor name handling when entity description has Sax prefix."""
        item_with_sax_prefix = ModbusItem(
            name="sax_custom_sensor",
            device=DeviceConstants.BESS,
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

        # Should remove "Sax " from entity description name
        assert sensor.name == "Custom Power Sensor"

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


class TestSensorPlatformSetup:
    """Test sensor platform setup with various configurations."""

    @pytest.fixture
    def mock_config_entry_sensor_platform(self) -> MagicMock:
        """Create mock config entry for platform tests."""
        config_entry = MagicMock()
        config_entry.entry_id = "test_sensor_platform_entry"
        config_entry.data = {"control_power": False, "limit_power": False}
        return config_entry

    @pytest.fixture
    def mock_sax_data_sensor_platform(self) -> MagicMock:
        """Create mock SAX data for platform tests."""
        return MagicMock()

    @pytest.fixture
    def mock_battery_config_sensor_platform(self) -> dict[str, Any]:
        """Create mock battery configuration for platform tests."""
        return {
            CONF_BATTERY_HOST: "192.168.1.100",
            CONF_BATTERY_PORT: 502,
            CONF_BATTERY_ENABLED: True,
            CONF_BATTERY_PHASE: "L1",
            CONF_BATTERY_IS_MASTER: True,
        }

    async def test_async_setup_entry_success(
        self,
        hass: HomeAssistant,
        mock_config_entry_sensor_platform,
        mock_sax_data_sensor_platform,
        mock_battery_config_sensor_platform,
    ) -> None:
        """Test successful setup of sensor entries."""
        # Mock coordinators with battery_config
        mock_coordinator = MagicMock(spec=SAXBatteryCoordinator)
        mock_coordinator.battery_id = "bess_a"
        mock_coordinator.battery_config = mock_battery_config_sensor_platform
        mock_coordinator.sax_data = MagicMock()
        mock_coordinator.sax_data.get_device_info.return_value = {
            "name": "Test Battery"
        }

        # Mock cycle_time_statistics for diagnostic sensors
        mock_coordinator.cycle_time_statistics = {
            "last": 0.5,
            "average": 0.45,
            "min": 0.3,
            "max": 0.6,
            "stddev": 0.1,
            "errors_per_hour": 0.0,
            "circuit_breaker_open": 0.0,
        }

        # Mock sensor items for battery with proper entity descriptions
        mock_modbus_item = ModbusItem(
            name="sax_test_sensor",
            device=DeviceConstants.BESS,
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
            device=DeviceConstants.BESS,
            entitydescription=DESCRIPTION_SAX_COMBINED_SOC,
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

        mock_sax_data_sensor_platform.get_modbus_items_for_battery.return_value = [
            mock_modbus_item
        ]
        mock_sax_data_sensor_platform.get_sax_items_for_battery.return_value = [
            mock_sax_item
        ]

        # Store mock data in hass
        hass.data[DOMAIN] = {
            mock_config_entry_sensor_platform.entry_id: {
                "coordinators": {"bess_a": mock_coordinator},
                "sax_data": mock_sax_data_sensor_platform,
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
            await async_setup_entry(
                hass, mock_config_entry_sensor_platform, mock_add_entities
            )

        # Verify entities were created
        # Expected: 1 modbus + 5 diagnostic (cycle_time, error_rate, circuit_breaker, bms_unavailability, txid_error_rate) + 1 calculated = 7 total
        assert len(entities) == 7

        # Check entity types in correct order
        # Order: [modbus_sensor, diag_cycle, diag_error, diag_circuit, diag_bms_unavail, diag_txid, calculated_sensor]
        assert isinstance(entities[0], SAXBatteryModbusSensor)
        assert isinstance(entities[1], SAXBatteryCoordinatorCycleSensor)
        assert isinstance(entities[2], SAXBatteryCoordinatorCycleSensor)
        assert isinstance(entities[3], SAXBatteryCoordinatorCycleSensor)
        assert isinstance(entities[4], SAXBatteryCoordinatorCycleSensor)
        assert isinstance(entities[5], SAXBatteryCoordinatorCycleSensor)
        assert isinstance(entities[6], SAXBatteryCalculatedSensor)

    async def test_async_setup_entry_mixed_item_types(
        self,
        hass: HomeAssistant,
        mock_config_entry_sensor_platform,
        mock_sax_data_sensor_platform,
    ) -> None:
        """Test setup with mixed item types - only sensor items should be created."""
        # Mock coordinator with battery_config attribute
        mock_coordinator = MagicMock(spec=SAXBatteryCoordinator)
        mock_coordinator.battery_id = "bess_a"
        mock_coordinator.battery_config = {
            CONF_BATTERY_HOST: "192.168.1.100",
            CONF_BATTERY_PORT: 502,
            CONF_BATTERY_ENABLED: True,
            CONF_BATTERY_PHASE: "L1",
            CONF_BATTERY_IS_MASTER: True,
        }
        mock_coordinator.sax_data = MagicMock()
        mock_coordinator.sax_data.get_device_info.return_value = {
            "name": "Test Battery"
        }

        # Mock cycle_time_statistics for diagnostic sensors
        mock_coordinator.cycle_time_statistics = {
            "last": 0.5,
            "average": 0.45,
            "min": 0.3,
            "max": 0.6,
            "stddev": 0.1,
            "errors_per_hour": 0.0,
            "circuit_breaker_open": 0.0,
        }

        # Mock mixed items - only sensors should be created
        sensor_item = ModbusItem(
            name="sax_test_sensor",
            device=DeviceConstants.BESS,
            mtype=TypeConstants.SENSOR,
            address=100,
            entitydescription=SensorEntityDescription(
                key="test_sensor",
                name="Test Sensor",
            ),
        )
        switch_item = ModbusItem(  # noqa: F841
            name="sax_test_switch",
            device=DeviceConstants.BESS,
            mtype=TypeConstants.SWITCH,
        )
        calc_item = SAXItem(  # noqa: F841
            name=SAX_COMBINED_SOC,
            mtype=TypeConstants.SENSOR_CALC,
            device=DeviceConstants.BESS,
            entitydescription=DESCRIPTION_SAX_COMBINED_SOC,
        )
        non_calc_item = SAXItem(  # noqa: F841
            name="sax_test_switch_sax",
            mtype=TypeConstants.SWITCH,
            device=DeviceConstants.BESS,
        )

        # Mock the filter functions to return appropriate items
        def mock_filter_items_by_type(items, item_type, config_entry, battery_id):
            if item_type == TypeConstants.SENSOR:
                return [sensor_item]
            return []

        def mock_filter_sax_items_by_type(items, item_type):
            if item_type == TypeConstants.SENSOR:
                calc_item = SAXItem(
                    name=SAX_COMBINED_SOC,
                    mtype=TypeConstants.SENSOR_CALC,
                    device=DeviceConstants.BESS,
                    entitydescription=DESCRIPTION_SAX_COMBINED_SOC,
                )
                return [calc_item]
            return []

        mock_sax_data_sensor_platform.get_modbus_items_for_battery.return_value = [
            sensor_item
        ]
        mock_sax_data_sensor_platform.get_sax_items_for_battery.return_value = []

        # Store mock data in hass
        hass.data[DOMAIN] = {
            mock_config_entry_sensor_platform.entry_id: {
                "coordinators": {"bess_a": mock_coordinator},
                "sax_data": mock_sax_data_sensor_platform,
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
            await async_setup_entry(
                hass, mock_config_entry_sensor_platform, mock_add_entities
            )

        # Verify sensor entities were created
        # Expected: 1 modbus + 5 diagnostic + 1 calculated = 7 total
        assert len(entities) == 7

        # Verify all entities are sensor types (no switches)
        assert all(
            isinstance(
                e,
                (
                    SAXBatteryModbusSensor,
                    SAXBatteryCalculatedSensor,
                    SAXBatteryCoordinatorCycleSensor,
                ),
            )
            for e in entities
        )


class TestSAXBatteryCoordinatorCycleSensorBMSUnavailability:
    """Test SAXBatteryCoordinatorCycleSensor dispatch for BMS_UNAVAILABILITY_RATE."""

    def _make_sensor(self, stats: dict) -> SAXBatteryCoordinatorCycleSensor:
        """Build a SAXBatteryCoordinatorCycleSensor for the BMS_UNAVAILABILITY_RATE key."""
        mock_coordinator = MagicMock()
        mock_coordinator.cycle_time_statistics = stats
        mock_coordinator.sax_data = MagicMock()
        mock_coordinator.sax_data.get_device_info.return_value = {"name": "Test BMS"}

        sax_item = SAXItem(
            name=BMS_UNAVAILABILITY_RATE,
            mtype=TypeConstants.SENSOR,
            device=DeviceConstants.SYS,
            entitydescription=DESCRIPTION_BMS_UNAVAILABILITY_RATE,
        )

        return SAXBatteryCoordinatorCycleSensor(
            coordinator=mock_coordinator,
            sax_item=sax_item,
        )

    def test_native_value_returns_float(self) -> None:
        """Test native_value returns float for BMS_UNAVAILABILITY_RATE."""
        sensor = self._make_sensor({"bms_unavailability_per_hour": 3.0})

        assert sensor.native_value == 3.0
        assert isinstance(sensor.native_value, float)

    def test_native_value_defaults_to_zero(self) -> None:
        """Test native_value returns 0.0 when key missing from stats."""
        sensor = self._make_sensor({})

        assert sensor.native_value == 0.0

    def test_native_value_handles_none(self) -> None:
        """Test native_value converts None to 0.0."""
        sensor = self._make_sensor({"bms_unavailability_per_hour": None})

        assert sensor.native_value == 0.0

    def test_extra_state_attributes_total_last_hour(self) -> None:
        """Test extra_state_attributes returns total_unavailability_last_hour."""
        sensor = self._make_sensor(
            {
                "bms_unavailability_per_hour": 5.0,
                "last_error_time": "2026-05-10T12:00:00",
            }
        )

        attrs = sensor.extra_state_attributes

        assert attrs["total_unavailability_last_hour"] == 5
        assert attrs["last_error_time"] == "2026-05-10T12:00:00"

    def test_extra_state_attributes_defaults(self) -> None:
        """Test extra_state_attributes works with empty stats dict."""
        sensor = self._make_sensor({})

        attrs = sensor.extra_state_attributes

        assert attrs["total_unavailability_last_hour"] == 0
        assert attrs["last_error_time"] is None


class TestSAXBatteryCoordinatorCycleSensorTxidErrorRate:
    """Test SAXBatteryCoordinatorCycleSensor dispatch for TXID_ERROR_RATE."""

    def _make_sensor(self, stats: dict) -> SAXBatteryCoordinatorCycleSensor:
        """Build a SAXBatteryCoordinatorCycleSensor for the TXID_ERROR_RATE key."""
        mock_coordinator = MagicMock()
        mock_coordinator.cycle_time_statistics = stats
        mock_coordinator.sax_data = MagicMock()
        mock_coordinator.sax_data.get_device_info.return_value = {"name": "Test BMS"}

        sax_item = SAXItem(
            name=TXID_ERROR_RATE,
            mtype=TypeConstants.SENSOR,
            device=DeviceConstants.SYS,
            entitydescription=DESCRIPTION_TXID_ERROR_RATE,
        )

        return SAXBatteryCoordinatorCycleSensor(
            coordinator=mock_coordinator,
            sax_item=sax_item,
        )

    def test_native_value_returns_float(self) -> None:
        """Test native_value returns float for TXID_ERROR_RATE."""
        sensor = self._make_sensor({"txid_errors_per_hour": 7.0})

        assert sensor.native_value == 7.0
        assert isinstance(sensor.native_value, float)

    def test_native_value_defaults_to_zero(self) -> None:
        """Test native_value returns 0.0 when key missing from stats."""
        sensor = self._make_sensor({})

        assert sensor.native_value == 0.0

    def test_native_value_handles_none(self) -> None:
        """Test native_value converts None to 0.0."""
        sensor = self._make_sensor({"txid_errors_per_hour": None})

        assert sensor.native_value == 0.0

    def test_extra_state_attributes_total_last_hour(self) -> None:
        """Test extra_state_attributes returns total_errors_last_hour."""
        sensor = self._make_sensor({"txid_errors_per_hour": 12.0})

        with patch(
            "custom_components.sax_battery.txid_error_tracker.get_total_errors",
            return_value=500,
        ):
            attrs = sensor.extra_state_attributes

        assert attrs["total_errors_last_hour"] == 12
        assert attrs["total_errors_since_startup"] == 500

    def test_extra_state_attributes_defaults(self) -> None:
        """Test extra_state_attributes works with empty stats dict."""
        sensor = self._make_sensor({})

        with patch(
            "custom_components.sax_battery.txid_error_tracker.get_total_errors",
            return_value=0,
        ):
            attrs = sensor.extra_state_attributes

        assert attrs["total_errors_last_hour"] == 0
        assert attrs["total_errors_since_startup"] == 0
