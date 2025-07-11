"""Switch platform for SAX Battery integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SAXBatteryCoordinator
from .entity_helpers import (
    build_entity_list,
    create_entity_unique_id,
    determine_entity_category,
)
from .enums import TypeConstants
from .items import ModbusItem
from .models import SAXBatteryData


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SAX Battery switch entities."""
    sax_data: SAXBatteryData = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[SwitchEntity] = []

    # Create switch entities for each battery
    for battery_id, coordinator in sax_data.coordinators.items():
        api_items = sax_data.get_modbus_items_for_battery(battery_id)

        await build_entity_list(
            entries=entities,
            config_entry=config_entry,
            api_items=api_items,
            item_type=TypeConstants.SWITCH,
            coordinator=coordinator,
            battery_id=battery_id,
        )

    async_add_entities(entities)


class SAXBatterySwitch(CoordinatorEntity[SAXBatteryCoordinator], SwitchEntity):
    """SAX Battery switch entity using coordinator for Modbus operations."""

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        battery_id: str,
        modbus_item: ModbusItem,
        index: int,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self._battery_id = battery_id
        self._modbus_item = modbus_item
        self._index = index

        # Entity configuration
        self._attr_unique_id = create_entity_unique_id(battery_id, modbus_item, index)
        self._attr_name = (
            f"{battery_id.title()} {modbus_item.name.replace('_', ' ').title()}"
        )
        self._attr_entity_category = determine_entity_category(modbus_item)

        # Use icon from description if available
        if hasattr(modbus_item, "description") and modbus_item.description:
            self._attr_icon = getattr(modbus_item.description, "icon", None)
        elif hasattr(modbus_item, "icon"):
            self._attr_icon = modbus_item.icon

        # Device info
        self._attr_device_info = coordinator.sax_data.get_device_info(battery_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        success = await self.coordinator.async_write_modbus_register(
            self._modbus_item, self._get_on_value()
        )

        if not success:
            raise HomeAssistantError(f"Failed to turn on {self._modbus_item.name}")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        success = await self.coordinator.async_write_modbus_register(
            self._modbus_item, self._get_off_value()
        )

        if not success:
            raise HomeAssistantError(f"Failed to turn off {self._modbus_item.name}")

    def _get_on_value(self) -> int:
        """Get the value to write for turning on the switch."""
        # Use on_value from ModbusItem if defined
        on_value = getattr(self._modbus_item, "on_value", None)
        if on_value is not None:
            return int(on_value)

        # Check if resultlist provides on/off mapping
        resultlist = getattr(self._modbus_item, "resultlist", None)
        if resultlist:
            # Look for "Connected" or similar "on" state
            for status_item in resultlist:
                if status_item.text.lower() in ["connected", "on", "enabled"]:
                    return int(status_item.number)

        # Default fallback
        return 1

    def _get_off_value(self) -> int:
        """Get the value to write for turning off the switch."""
        # Use off_value from ModbusItem if defined
        off_value = getattr(self._modbus_item, "off_value", None)
        if off_value is not None:
            return int(off_value)

        # Check if resultlist provides on/off mapping
        resultlist = getattr(self._modbus_item, "resultlist", None)
        if resultlist:
            # Look for "OFF" or similar "off" state
            for status_item in resultlist:
                if status_item.text.lower() in ["off", "disconnected", "disabled"]:
                    return int(status_item.number)

        # Default fallback
        return 0

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        if not self.coordinator.last_update_success:
            return None

        value = self.coordinator.data.get(self._modbus_item.name)
        if value is None:
            return None

        # Check against on value
        on_value = self._get_on_value()
        return bool(value == on_value)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if not self.coordinator.last_update_success:
            return None

        return {
            "battery_id": self._battery_id,
            "modbus_address": getattr(self._modbus_item, "address", None),
            "last_updated": self.coordinator.last_update_success_time,
            "on_value": self._get_on_value(),
            "off_value": self._get_off_value(),
        }
