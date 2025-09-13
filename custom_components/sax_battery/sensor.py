"""SAX Battery sensor platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SAXBatteryCoordinator
from .entity_utils import filter_items_by_type, filter_sax_items_by_type
from .enums import TypeConstants
from .items import ModbusItem, SAXItem

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SAX Battery sensor platform."""
    integration_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators = integration_data["coordinators"]
    sax_data = integration_data["sax_data"]

    entities: list[SensorEntity] = []

    # Create sensors for each battery (modbus items)
    for battery_id, coordinator in coordinators.items():
        sensor_items = filter_items_by_type(
            sax_data.get_modbus_items_for_battery(battery_id),
            TypeConstants.SENSOR,
            config_entry,
            battery_id,
        )

        for modbus_item in sensor_items:
            if isinstance(modbus_item, ModbusItem):  # Type guard
                entities.append(  # noqa: PERF401
                    SAXBatteryModbusSensor(
                        coordinator=coordinator,
                        battery_id=battery_id,
                        modbus_item=modbus_item,
                    )
                )

        _LOGGER.info(
            "Added %d modbus sensor entities for %s", len(sensor_items), battery_id
        )

    # Create system-wide calculated sensors (SAX items with SENSOR_CALC)
    system_sensor_items = filter_sax_items_by_type(
        sax_data.get_sax_items_for_battery(
            "battery_a"
        ),  # Use first battery for system items
        TypeConstants.SENSOR,
    )

    # Get first coordinator for calculated sensors - fix StopIteration error
    if coordinators:
        first_coordinator = next(iter(coordinators.values()))
        for sax_item in system_sensor_items:
            if isinstance(sax_item, SAXItem):  # Type guard
                entities.append(  # noqa: PERF401
                    SAXBatteryCalculatedSensor(
                        coordinator=first_coordinator,
                        sax_item=sax_item,
                        coordinators=coordinators,
                    )
                )

    _LOGGER.info("Added %d calculated sensor entities", len(system_sensor_items))

    if entities:
        async_add_entities(entities)


class SAXBatteryModbusSensor(CoordinatorEntity[SAXBatteryCoordinator], SensorEntity):
    """Implementation of a SAX Battery modbus sensor entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        battery_id: str,
        modbus_item: ModbusItem,
    ) -> None:
        """Initialize the modbus sensor."""
        super().__init__(coordinator)
        self._modbus_item = modbus_item
        self._battery_id = battery_id

        # Generate unique ID using class name pattern
        item_name = self._modbus_item.name.removeprefix("sax_")
        self._attr_unique_id = f"sax_{self._battery_id}_{item_name}"

        # Set entity description from modbus item if available
        if self._modbus_item.entitydescription is not None:
            self.entity_description = self._modbus_item.entitydescription  # type: ignore[assignment]

        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "name")
            and isinstance(self.entity_description.name, str)
        ):
            # Remove "Sax " prefix from entity description name
            entity_name = str(self.entity_description.name)
            entity_name = entity_name.removeprefix("Sax ")  # Remove "Sax " prefix
            self._attr_name = entity_name
        else:
            # Fallback: use clean item name without prefixes
            clean_name = item_name.replace("_", " ").title()
            self._attr_name = clean_name

        # Set device info
        self._attr_device_info = coordinator.sax_data.get_device_info(battery_id)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._modbus_item.name)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        return {
            "battery_id": self._battery_id,
            "modbus_address": getattr(self._modbus_item, "address", None),
            "last_update": getattr(self.coordinator, "last_update_success_time", None),
            "raw_value": self.coordinator.data.get(self._modbus_item.name)
            if self.coordinator.data
            else None,
        }


class SAXBatteryCalculatedSensor(
    CoordinatorEntity[SAXBatteryCoordinator], SensorEntity
):
    """Implementation of a SAX Battery calculated sensor entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        sax_item: SAXItem,
        coordinators: dict[str, SAXBatteryCoordinator],
    ) -> None:
        """Initialize the calculated sensor."""
        super().__init__(coordinator)
        self._sax_item = sax_item
        self._coordinators = coordinators

        # Set coordinators on the SAX item for calculations
        self._sax_item.set_coordinators(coordinators)

        # Generate unique ID using class name pattern (without "(Calculated)" suffix)
        if self._sax_item.name.startswith("sax_"):
            self._attr_unique_id = self._sax_item.name
        else:
            self._attr_unique_id = f"sax_{self._sax_item.name}"

        # Set entity description from sax item if available
        if self._sax_item.entitydescription is not None:
            self.entity_description = self._sax_item.entitydescription  # type: ignore[assignment]

        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "name")
            and isinstance(self.entity_description.name, str)
        ):
            item_name = self.entity_description.name[4:]  # eliminate 'Sax '

        self._attr_name = f"Sax {item_name}"  # type: ignore

        # Set system device info
        self._attr_device_info = coordinator.sax_data.get_device_info("cluster")

    @property
    def native_value(self) -> Any:
        """Return the calculated sensor value."""
        # Use SAXItem's calculate_value method
        return self._sax_item.calculate_value(self._coordinators)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        return {
            "battery_id": self.coordinator.battery_id,
            "calculation_type": "function_based",
            "calculation_function": self._sax_item.name,
            "battery_count": len(self._coordinators),
            "last_update": getattr(self.coordinator, "last_update_success_time", None),
        }
