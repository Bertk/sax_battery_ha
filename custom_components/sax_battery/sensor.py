"""SAX Battery sensor platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SAXBatteryCoordinator
from .enums import TypeConstants
from .items import ModbusItem, SAXItem
from .models import SAXBatteryData
from .utils import format_battery_display_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SAX Battery sensor platform."""
    sax_data: SAXBatteryData = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[SensorEntity] = []

    # Create sensor entities for each battery
    for battery_id, coordinator in sax_data.coordinators.items():
        if not isinstance(coordinator, SAXBatteryCoordinator):
            continue

        # Add modbus sensor items using extend
        modbus_items = sax_data.get_modbus_items_for_battery(battery_id)
        entities.extend(
            SAXBatteryModbusSensor(
                coordinator=coordinator,
                battery_id=battery_id,
                modbus_item=item,
            )
            for item in modbus_items
            if item.mtype == TypeConstants.SENSOR
        )

        # Add SAX sensor items (calculated sensors) using extend
        sax_items = sax_data.get_sax_items_for_battery(battery_id)
        entities.extend(
            SAXBatteryCalcSensor(
                coordinator=coordinator,
                battery_id=battery_id,
                sax_item=sax_item,
            )
            for sax_item in sax_items
            if sax_item.mtype == TypeConstants.SENSOR_CALC
        )

    if entities:
        async_add_entities(entities, update_before_add=True)


class SAXBatteryModbusSensor(CoordinatorEntity[SAXBatteryCoordinator], SensorEntity):
    """SAX Battery modbus sensor entity."""

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        battery_id: str,
        modbus_item: ModbusItem,
    ) -> None:
        """Initialize SAX Battery modbus sensor entity."""
        super().__init__(coordinator)

        self._battery_id = battery_id
        self._modbus_item = modbus_item

        # Generate unique ID using class name pattern
        item_name = self._modbus_item.name.removeprefix("sax_")
        self._attr_unique_id = f"sax_{self._battery_id}_{item_name}"

        # Set entity description from modbus item if available
        if self._modbus_item.entitydescription is not None:
            self.entity_description = self._modbus_item.entitydescription  # type: ignore[assignment] # fmt: skip

        if isinstance(self.entity_description.name, str):
            item_name = self.entity_description.name[4:]  # eliminate 'Sax ' # type: ignore[index] # fmt: skip

        self.name = f"Sax {format_battery_display_name(self._battery_id)} {item_name}"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device info."""
        return self.coordinator.sax_data.get_device_info(self._battery_id)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        return self.coordinator.data.get(self._modbus_item.name)

    @property
    def state_class(self) -> str | None:
        """Return state class."""
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "state_class")
        ):
            return self.entity_description.state_class
        return None

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return device class."""
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "device_class")
        ):
            return self.entity_description.device_class
        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit of measurement."""
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "native_unit_of_measurement")
        ):
            return self.entity_description.native_unit_of_measurement
        return None

    @property
    def entity_category(self) -> EntityCategory | None:
        """Return entity category."""
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "entity_category")
        ):
            return self.entity_description.entity_category
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        return {
            "battery_id": self._battery_id,
            "modbus_address": self._modbus_item.address,
            "last_update": getattr(self.coordinator, "last_update_success_time", None),
        }


class SAXBatteryCalcSensor(CoordinatorEntity[SAXBatteryCoordinator], SensorEntity):
    """SAX Battery calculated sensor entity."""

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        battery_id: str,
        sax_item: SAXItem,
    ) -> None:
        """Initialize SAX Battery calculated sensor entity."""
        super().__init__(coordinator)

        self._battery_id = battery_id
        self._sax_item = sax_item

        # Generate unique ID using class name pattern (without "(Calculated)" suffix)
        item_name = self._sax_item.name.removeprefix("sax_")
        self._attr_unique_id = f"sax_{self._battery_id}_{item_name}"

        # Set entity description from sax item if available
        if self._sax_item.entitydescription is not None:
            self.entity_description = self._sax_item.entitydescription  # type: ignore[assignment] # fmt: skip
        if isinstance(self.entity_description.name, str):
            item_name = self.entity_description.name[4:]  # eliminate 'Sax ' # type: ignore[index] # fmt: skip

        self.name = f"Sax {format_battery_display_name(self._battery_id)} {item_name}"

        # Call post-init to add "(Calculated)" suffix to display name
        self.__post_init__()

    def __post_init__(self) -> None:
        """Initialize compiled calculation after object creation."""
        if self._sax_item.mtype == TypeConstants.SENSOR_CALC and isinstance(self.name, str):  # fmt: skip
            if not self.name.endswith("(Calculated)"):
                self.name = f"{self.name} (Calculated)"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device info."""
        return self.coordinator.sax_data.get_device_info(self._battery_id)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        return self.coordinator.data.get(self._sax_item.name)

    @property
    def state_class(self) -> str | None:
        """Return state class."""
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "state_class")
        ):
            return self.entity_description.state_class
        return None

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return device class."""
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "device_class")
        ):
            return self.entity_description.device_class
        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit of measurement."""
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "native_unit_of_measurement")
        ):
            return self.entity_description.native_unit_of_measurement
        return None

    @property
    def entity_category(self) -> EntityCategory | None:
        """Return entity category."""
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "entity_category")
        ):
            return self.entity_description.entity_category
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        return {
            "battery_id": self._battery_id,
            "calculation_type": "sax_item",
            "last_update": getattr(self.coordinator, "last_update_success_time", None),
        }
