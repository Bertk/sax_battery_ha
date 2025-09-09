"""Number platform for SAX Battery integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SAX_MIN_SOC
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
    """Set up SAX Battery number entities."""
    integration_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators = integration_data["coordinators"]
    sax_data = integration_data["sax_data"]

    entities: list[NumberEntity] = []

    # Create numbers for each battery
    for battery_id, coordinator in coordinators.items():
        # Regular writable number items (NUMBER)
        number_items = filter_items_by_type(
            sax_data.get_modbus_items_for_battery(battery_id),
            TypeConstants.NUMBER,
            config_entry,
            battery_id,
        )

        for modbus_item in number_items:
            if isinstance(modbus_item, ModbusItem):  # Type guard
                entities.append(  # noqa: PERF401
                    SAXBatteryModbusNumber(
                        coordinator=coordinator,
                        battery_id=battery_id,
                        modbus_item=modbus_item,
                    )
                )

        _LOGGER.info(
            "Added %d modbus number entities for %s", len(number_items), battery_id
        )

    # Create system-wide configuration numbers (from SAX items)
    system_number_items = filter_sax_items_by_type(
        sax_data.get_sax_items_for_battery(
            "battery_a"
        ),  # Use first battery for system items
        TypeConstants.NUMBER,
    )

    # Get first coordinator for config numbers
    first_coordinator = next(iter(coordinators.values())) if coordinators else None
    if first_coordinator:
        for sax_item in system_number_items:
            if isinstance(sax_item, SAXItem):  # Type guard
                entities.append(  # noqa: PERF401
                    SAXBatteryConfigNumber(
                        coordinator=first_coordinator,
                        sax_item=sax_item,
                    )
                )

    _LOGGER.info(
        "Adding %d number entities: %s",
        len(entities),
        [type(entity).__name__ for entity in entities],
    )

    if entities:
        async_add_entities(entities)


class SAXBatteryModbusNumber(CoordinatorEntity[SAXBatteryCoordinator], NumberEntity):
    """Implementation of a SAX Battery number entity backed by ModbusItem."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        battery_id: str,
        modbus_item: ModbusItem,
    ) -> None:
        """Initialize the modbus number entity."""
        super().__init__(coordinator)
        self._modbus_item = modbus_item
        self._battery_id = battery_id

        # Generate unique ID using simple pattern
        if self._modbus_item.name.startswith("sax_"):
            item_name = self._modbus_item.name[4:]  # Remove "sax_" prefix
        else:
            item_name = self._modbus_item.name

        self._attr_unique_id = f"sax_{battery_id}_{item_name}"

        # Set entity description from modbus item if available
        if self._modbus_item.entitydescription is not None:
            self.entity_description = self._modbus_item.entitydescription  # type: ignore[assignment]

        # Set entity name
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "name")
            and isinstance(self.entity_description.name, str)
        ):
            entity_name = str(self.entity_description.name)
            entity_name = entity_name.removeprefix("Sax ")
            self._attr_name = entity_name
        else:
            clean_name = item_name.replace("_", " ").title()
            self._attr_name = clean_name

        # Set device info for the specific battery
        self._attr_device_info = coordinator.sax_data.get_device_info(battery_id)

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if not self.coordinator.data:
            return None
        value = self.coordinator.data.get(self._modbus_item.name)
        return float(value) if value is not None else None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            super().available
            and self.coordinator.data is not None
            and self._modbus_item.name in self.coordinator.data
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        raw_value = (
            self.coordinator.data.get(self._modbus_item.name)
            if self.coordinator.data
            else None
        )

        return {
            "battery_id": self._battery_id,
            "modbus_address": getattr(self._modbus_item, "address", None),
            "last_update": getattr(self.coordinator, "last_update_success_time", None),
            "raw_value": raw_value,
            "entity_type": "modbus",
        }

    async def async_set_native_value(self, value: float) -> None:
        """Set new value using direct ModbusItem communication."""
        try:
            # Use direct ModbusItem communication
            success = await self._modbus_item.async_write_value(value)
            if not success:
                _LOGGER.error(
                    "Failed to write value %s to %s", value, self._modbus_item.name
                )

            # Refresh coordinator data
            await self.coordinator.async_request_refresh()

        except Exception as err:
            _LOGGER.error(
                "Failed to set %s to %s: %s", self._modbus_item.name, value, err
            )
            raise


class SAXBatteryConfigNumber(CoordinatorEntity[SAXBatteryCoordinator], NumberEntity):
    """Implementation of a SAX Battery configuration number entity using SAXItem."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        sax_item: SAXItem,
    ) -> None:
        """Initialize the config number entity."""
        super().__init__(coordinator)
        self._sax_item = sax_item

        # Generate unique ID using simple pattern
        if self._sax_item.name.startswith("sax_"):
            self._attr_unique_id = self._sax_item.name
        else:
            self._attr_unique_id = f"sax_{self._sax_item.name}"

        if self._sax_item.entitydescription is not None:
            self.entity_description = self._sax_item.entitydescription  # type: ignore[assignment]

        # Set system device info - this creates the "SAX Battery Cluster" device
        self._attr_device_info = coordinator.sax_data.get_device_info("cluster")

    @property
    def native_value(self) -> float | None:
        """Return the current value using SAXItem logic."""
        # For SAX_MIN_SOC, get from config entry data
        if self._sax_item.name == SAX_MIN_SOC and self.coordinator.config_entry:
            config_value = self.coordinator.config_entry.data.get("min_soc", 15)
            return float(config_value)

        # For other SAX items, use the item's own read method
        # This will be async in real implementation but simplified here
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self.coordinator.data is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        raw_value = (
            self.coordinator.data.get(self._sax_item.name)
            if self.coordinator.data
            else None
        )

        return {
            "last_update": getattr(self.coordinator, "last_update_success_time", None),
            "raw_value": raw_value,
            "entity_type": "config",
        }

    async def async_set_native_value(self, value: float) -> None:
        """Set new value using SAXItem communication."""
        try:
            # Use SAXItem's write method for system configuration
            success = await self._sax_item.async_write_value(value)
            if not success:
                # Fallback for specific items like SAX_MIN_SOC
                if self._sax_item.name == SAX_MIN_SOC and self.coordinator.config_entry:
                    new_data = dict(self.coordinator.config_entry.data)
                    new_data["min_soc"] = int(value)
                    self.hass.config_entries.async_update_entry(
                        self.coordinator.config_entry,
                        data=new_data,
                    )
                    self.async_write_ha_state()
                    return

                _LOGGER.error(
                    "Failed to write value %s to %s", value, self._sax_item.name
                )

        except Exception as err:
            _LOGGER.error("Failed to set %s to %s: %s", self._sax_item.name, value, err)
            raise
