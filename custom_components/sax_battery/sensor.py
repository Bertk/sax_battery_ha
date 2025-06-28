"""Sensor platform for SAX Battery integration."""

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final, Generic, TypeVar, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MASTER_BATTERY,
    DOMAIN,
    SAX_COMBINED_SOC,
    SAX_CURRENT_L1,
    SAX_CURRENT_L2,
    SAX_CURRENT_L3,
    SAX_ENERGY_CONSUMED,
    SAX_ENERGY_PRODUCED,
    SAX_POWER,
    SAX_SOC,
    SAX_STATUS,
    SAX_STORAGE_STATUS,
    SAX_VOLTAGE_L1,
)
from .data_manager import BatteryData, SAXBatteryDataManager

status_map = {1: "OFF", 2: "ON", 3: "Connected", 4: "Standby"}

# Define TypeVar for value types
ValueT = TypeVar("ValueT")

# Create a union type for all possible sensor value types
SensorValueType = Decimal | str | None


@dataclass(frozen=True)
class SAXBatterySensorEntityDescription(SensorEntityDescription, Generic[ValueT]):
    """Class describing SAX Battery sensor entities."""

    value_fn: Callable[[Any], ValueT] = field(
        default_factory=lambda: cast(
            Callable[[Any], ValueT],
            lambda x: (
                Decimal(str(x))
                if isinstance(x, (int, float, str)) and x is not None
                else None
            ),
        )
    )
    enabled_by_default: bool = True


@dataclass(frozen=True)
class SAXBatteryAggregatedSensorEntityDescription(SensorEntityDescription):
    """Class describing SAX Battery aggregated sensor entities."""

    aggregate_fn: Callable[[dict[str, BatteryData]], Decimal | None] = field(
        default_factory=lambda: lambda _: None
    )
    enabled_by_default: bool = True


SENSOR_TYPES: Final[tuple[SAXBatterySensorEntityDescription[SensorValueType], ...]] = (
    # Basic sensors
    SAXBatterySensorEntityDescription(
        key=SAX_STATUS,
        name="Status",
        translation_key="status",
        value_fn=lambda x: str(x) if x is not None else None,
    ),
    SAXBatterySensorEntityDescription(
        key=SAX_SOC,
        name="SOC",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SAXBatterySensorEntityDescription(
        key=SAX_POWER,
        name="Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # Energy sensors
    SAXBatterySensorEntityDescription(
        key=SAX_ENERGY_PRODUCED,
        name="Energy Produced",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
    ),
    SAXBatterySensorEntityDescription(
        key=SAX_ENERGY_CONSUMED,
        name="Energy Consumed",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
    ),
    # Phase Current sensors
    SAXBatterySensorEntityDescription(
        key=SAX_CURRENT_L1,
        name="Current L1",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        enabled_by_default=False,
    ),
    SAXBatterySensorEntityDescription(
        key=SAX_CURRENT_L2,
        name="Current L2",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        enabled_by_default=False,
    ),
    SAXBatterySensorEntityDescription(
        key=SAX_CURRENT_L3,
        name="Current L3",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        enabled_by_default=False,
    ),
    # Phase Voltage sensors
    SAXBatterySensorEntityDescription(
        key=SAX_VOLTAGE_L1,
        name="Voltage L1",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        enabled_by_default=False,
    ),
    SAXBatterySensorEntityDescription(
        key=SAX_STORAGE_STATUS,
        name="Storage Status",
        translation_key="storage_status",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda x: str(
            status_map.get(x, f"Unknown ({x})") if x is not None else "Unknown"
        ),
    ),
)


def _sum_battery_values(data: dict[str, BatteryData], key: str) -> Decimal | None:
    """Sum values from all batteries for a given key."""
    if not data:
        return None

    total = Decimal("0")
    valid_values = 0

    for battery in data.values():
        if (value := battery.data.get(key)) is not None:
            total += Decimal(str(value))
            valid_values += 1

    return total if valid_values > 0 else None


def _average_battery_values(data: dict[str, BatteryData], key: str) -> Decimal | None:
    """Calculate average value from all batteries for a given key."""
    if not data:
        return None

    total = Decimal("0")
    valid_values = 0

    for battery in data.values():
        if (value := battery.data.get(key)) is not None:
            total += Decimal(str(value))
            valid_values += 1

    return total / valid_values if valid_values > 0 else None


AGGREGATED_SENSOR_TYPES: Final[
    tuple[SAXBatteryAggregatedSensorEntityDescription, ...]
] = (
    SAXBatteryAggregatedSensorEntityDescription(
        key="combined_power",
        name="Combined Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        aggregate_fn=lambda data: _sum_battery_values(data, SAX_POWER),
    ),
    SAXBatteryAggregatedSensorEntityDescription(
        key="combined_soc",
        name="Combined SOC",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        aggregate_fn=lambda data: _average_battery_values(data, SAX_SOC),
    ),
)


class SAXBatterySensor(SensorEntity):
    """Base class for SAX Battery sensors."""

    entity_description: SAXBatterySensorEntityDescription[SensorValueType]

    def __init__(
        self,
        battery: BatteryData,
        battery_id: str,
        description: SAXBatterySensorEntityDescription[SensorValueType],
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description  # type: ignore[override]
        self.battery = battery
        self._battery_id = battery_id

        self._attr_unique_id = (
            f"{battery.data_manager.device_id}_{battery_id}_{description.key}"
        )
        self._attr_name = (
            f"Sax {battery_id.replace('_', ' ').title()} {description.name}"
        )

        self._attr_device_info = {
            "identifiers": {(DOMAIN, battery.data_manager.device_id)},
            "name": "SAX Battery System",
            "manufacturer": "SAX",
            "model": "SAX Battery",
            "sw_version": "1.0",
        }

    @property
    def native_value(self) -> SensorValueType:  # type: ignore[override]
        """Return the native value of the sensor."""
        value = self.battery.data.get(self.entity_description.key)
        return self.entity_description.value_fn(value)


class SAXBatteryAggregatedSensor(SensorEntity):
    """Base class for SAX Battery aggregated sensors."""

    entity_description: SAXBatteryAggregatedSensorEntityDescription

    def __init__(
        self,
        data_manager: SAXBatteryDataManager,
        description: SAXBatteryAggregatedSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self.data_manager = data_manager

        self._attr_unique_id = f"{data_manager.device_id}_{description.key}"
        self._attr_name = f"Sax Battery {description.name}"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, data_manager.device_id)},
            "name": "SAX Battery System",
            "manufacturer": "SAX",
            "model": "SAX Battery",
            "sw_version": "1.0",
        }

        # Note: combined_data is now properly initialized in data_manager

    @property
    def native_value(self) -> Decimal | None:
        """Return the aggregated value across all batteries."""
        # Calculate the aggregated value
        aggregated_value = self.entity_description.aggregate_fn(
            self.data_manager.batteries
        )

        # Store in combined_data for access by other components (like pilot)
        if self.entity_description.key == "combined_soc":
            # Store as SAX_COMBINED_SOC for pilot compatibility
            self.data_manager.combined_data[SAX_COMBINED_SOC] = (
                float(aggregated_value) if aggregated_value is not None else None
            )

        # Store with the sensor key as well
        self.data_manager.combined_data[self.entity_description.key] = (
            float(aggregated_value) if aggregated_value is not None else None
        )

        return aggregated_value

    @property
    def should_poll(self) -> bool:
        """Return True if entity should be polled."""
        return True

    async def async_update(self) -> None:
        """Update the sensor state and combined data."""
        # Update all battery data through the data manager
        await self.data_manager.async_update_data()

        # Calculate and store the new aggregated value
        _ = self.native_value  # This triggers the calculation and storage


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the SAX Battery sensors."""
    sax_battery_data: SAXBatteryDataManager = hass.data[DOMAIN][entry.entry_id]
    master_battery_id: str | None = entry.data.get(CONF_MASTER_BATTERY)

    entities: list[SensorEntity] = []

    # Add aggregated sensors
    for agg_description in AGGREGATED_SENSOR_TYPES:
        if agg_description.key.startswith("cumulative") and master_battery_id:
            # Only add cumulative sensors for master battery
            entities.append(
                SAXBatteryAggregatedSensor(sax_battery_data, agg_description)
            )
        elif not agg_description.key.startswith("cumulative"):
            # Add combined sensors for all batteries
            entities.append(
                SAXBatteryAggregatedSensor(sax_battery_data, agg_description)
            )

    # Add individual battery sensors
    for battery_id, battery in sax_battery_data.batteries.items():
        for sensor_description in SENSOR_TYPES:
            entities.append(SAXBatterySensor(battery, battery_id, sensor_description))

    async_add_entities(entities)
    return True
