"""SAX Battery switch platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SAXBatteryCoordinator
from .entity_utils import filter_items_by_type
from .enums import TypeConstants
from .items import ModbusItem

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SAX Battery switch platform."""
    integration_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators = integration_data["coordinators"]
    sax_data = integration_data["sax_data"]

    entities: list[SAXBatterySwitch] = []

    # Create switch entities for each battery
    for battery_id, coordinator in coordinators.items():
        if not isinstance(coordinator, SAXBatteryCoordinator):
            continue

        # Use filter_items_by_type for consistent entity filtering
        switch_items = filter_items_by_type(
            sax_data.get_modbus_items_for_battery(battery_id),
            TypeConstants.SWITCH,
            config_entry,
            battery_id,
        )

        for modbus_item in switch_items:
            if isinstance(modbus_item, ModbusItem):  # Type guard
                entities.append(  # noqa: PERF401
                    SAXBatterySwitch(
                        coordinator=coordinator,
                        battery_id=battery_id,
                        modbus_item=modbus_item,
                    )
                )

    _LOGGER.info("Added %d switch entities", len(entities))

    if entities:
        async_add_entities(entities, update_before_add=True)


class SAXBatterySwitch(CoordinatorEntity[SAXBatteryCoordinator], SwitchEntity):
    """SAX Battery switch entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        battery_id: str,
        modbus_item: ModbusItem,
    ) -> None:
        """Initialize SAX Battery switch entity."""
        super().__init__(coordinator)

        self._battery_id = battery_id
        self._modbus_item = modbus_item

        # Generate unique ID using simple pattern - no battery prefix needed
        if self._modbus_item.name.startswith("sax_"):
            item_name = self._modbus_item.name[4:]  # Remove "sax_" prefix
        else:
            item_name = self._modbus_item.name

        self._attr_unique_id = f"sax_{battery_id}_{item_name}"

        # Set entity description from modbus item if available
        if self._modbus_item.entitydescription is not None:
            self.entity_description = self._modbus_item.entitydescription  # type: ignore[assignment]

        # Set entity name - let HA combine with device name automatically
        # Don't add battery prefix since device already provides it
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

        # Set device info for the specific battery
        self._attr_device_info = coordinator.sax_data.get_device_info(battery_id)

    @property
    def is_on(self) -> bool | None:
        """Return True if switch is on."""
        if not self.coordinator.data or not self.available:
            return None

        raw_value = self.coordinator.data.get(self._modbus_item.name)
        if raw_value is None:
            return None

        # Handle different value types
        if isinstance(raw_value, bool):
            return raw_value

        if isinstance(raw_value, str):
            return raw_value.lower() in ("on", "true", "1", "yes")

        try:
            # Numeric values: 0 = off, non-zero = on
            return bool(int(raw_value))
        except (ValueError, TypeError):
            return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self._modbus_item.name in self.coordinator.data
        )

    @property
    def entity_category(self) -> EntityCategory | None:
        """Return entity category."""
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "entity_category")
        ):
            return self.entity_description.entity_category
        return EntityCategory.CONFIG  # Default for switch entities

    @property
    def icon(self) -> str | None:
        """Return icon."""
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "icon")
        ):
            return self.entity_description.icon
        return None  # Use default Home Assistant switch icon

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        success = await self.coordinator.async_write_switch_value(
            self._modbus_item, True
        )

        if not success:
            msg = f"Failed to turn on {self.name}"
            raise HomeAssistantError(msg)

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        success = await self.coordinator.async_write_switch_value(
            self._modbus_item, False
        )

        if not success:
            msg = f"Failed to turn off {self.name}"
            raise HomeAssistantError(msg)

        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        return {
            "battery_id": self._battery_id,
            "modbus_address": self._modbus_item.address,
            "last_update": getattr(self.coordinator, "last_update_success_time", None),
            "raw_value": self.coordinator.data.get(self._modbus_item.name)
            if self.coordinator.data
            else None,
        }
