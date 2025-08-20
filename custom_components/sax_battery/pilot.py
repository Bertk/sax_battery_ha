"""SAX Battery pilot functionality."""

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

from .const import DOMAIN, MANUAL_CONTROL_SWITCH, PILOT_ITEMS, SOLAR_CHARGING_SWITCH
from .coordinator import SAXBatteryCoordinator
from .enums import TypeConstants
from .items import SAXItem
from .models import SAXBatteryData
from .utils import determine_entity_category

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SAX Battery pilot entities."""
    sax_data: SAXBatteryData = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[SwitchEntity] = []

    # Create pilot entities only for master battery
    master_battery_id = sax_data.master_battery_id
    if master_battery_id and master_battery_id in sax_data.coordinators:
        coordinator = sax_data.coordinators[master_battery_id]
        pilot = SAXBatteryPilot(hass, sax_data, coordinator)

        # Create pilot control entities from PILOT_ITEMS using extend
        entities.extend(
            _create_pilot_entity(pilot, coordinator, pilot_item, master_battery_id)
            for pilot_item in PILOT_ITEMS
            if pilot_item.mtype == TypeConstants.SWITCH
        )

    if entities:
        async_add_entities(entities, update_before_add=True)


def _create_pilot_entity(
    pilot: SAXBatteryPilot,
    coordinator: SAXBatteryCoordinator,
    pilot_item: SAXItem,
    battery_id: str,
) -> SwitchEntity:
    """Create appropriate pilot entity based on item name."""
    match pilot_item.name:
        case name if name == SOLAR_CHARGING_SWITCH:
            return SAXBatterySolarChargingSwitch(
                pilot, coordinator, pilot_item, battery_id
            )
        case name if name == MANUAL_CONTROL_SWITCH:
            return SAXBatteryManualControlSwitch(
                pilot, coordinator, pilot_item, battery_id
            )
        case _:
            # Default fallback for unknown switch types
            _LOGGER.warning("Unknown pilot switch type: %s", pilot_item.name)
            return SAXBatteryGenericPilotSwitch(
                pilot, coordinator, pilot_item, battery_id
            )


class SAXBatteryPilot:
    """SAX Battery pilot controller for master battery coordination."""

    def __init__(
        self,
        hass: HomeAssistant,
        sax_data: SAXBatteryData,
        coordinator: SAXBatteryCoordinator,
    ) -> None:
        """Initialize the pilot controller."""
        self.hass = hass
        self.sax_data = sax_data
        self.coordinator = coordinator

    async def set_manual_control(self, enabled: bool) -> bool:
        """Enable or disable manual control mode."""
        try:
            manual_item = self._get_pilot_item(MANUAL_CONTROL_SWITCH)
            if not manual_item:
                _LOGGER.error("Manual control pilot item not found")
                return False

            # Handle SAXItem directly - update internal state
            self.coordinator.update_sax_item_state(
                manual_item.name, 1 if enabled else 0
            )

            # Update the coordinator data for immediate UI feedback
            if self.coordinator.data is None:
                self.coordinator.data = {}
            self.coordinator.data[manual_item.name] = 1 if enabled else 0

            # Trigger coordinator update to notify entities
            self.coordinator.async_set_updated_data(self.coordinator.data)

            _LOGGER.debug("Manual control set to %s", enabled)
        except (OSError, ValueError, TypeError, AttributeError) as err:
            _LOGGER.error("Error setting manual control: %s", err)
            return False
        else:
            return True

    async def set_solar_charging(self, enabled: bool) -> bool:
        """Set solar charging mode for the battery system."""
        try:
            solar_item = self._get_pilot_item(SOLAR_CHARGING_SWITCH)
            if not solar_item:
                _LOGGER.error("Solar charging pilot item not found")
                return False

            # Handle SAXItem directly - update internal state
            value = 1 if enabled else 0
            self.coordinator.update_sax_item_state(solar_item.name, value)

            # Update the coordinator data for immediate UI feedback
            if self.coordinator.data is None:
                self.coordinator.data = {}
            self.coordinator.data[solar_item.name] = value

            # Trigger coordinator update to notify entities
            self.coordinator.async_set_updated_data(self.coordinator.data)

            _LOGGER.debug("Solar charging set to %s", enabled)
        except (OSError, ValueError, TypeError, AttributeError) as err:
            _LOGGER.error("Error setting solar charging: %s", err)
            return False
        else:
            return True

    async def set_charge_power_limit(self, power_limit: int) -> bool:
        """Set maximum charge power limit across all batteries."""
        try:
            # This would need a corresponding SAXItem for charge power limit
            # For now, use the existing modbus item lookup
            charge_limit_item = self._get_modbus_item("sax_max_charge_power")
            if not charge_limit_item:
                _LOGGER.error("Charge power limit modbus item not found")
                return False

            success = await self.coordinator.async_write_int_value(
                charge_limit_item, power_limit
            )

            if success:
                _LOGGER.debug("Charge power limit set to %s W", power_limit)
            else:
                _LOGGER.error("Failed to set charge power limit to %s W", power_limit)

        except (OSError, ValueError, TypeError, AttributeError) as err:
            _LOGGER.error("Error setting charge power limit: %s", err)
            return False
        else:
            return success

    async def set_discharge_power_limit(self, power_limit: int) -> bool:
        """Set maximum discharge power limit across all batteries."""
        try:
            # This would need a corresponding SAXItem for discharge power limit
            discharge_limit_item = self._get_modbus_item("sax_max_discharge_power")
            if not discharge_limit_item:
                _LOGGER.error("Discharge power limit modbus item not found")
                return False

            success = await self.coordinator.async_write_int_value(
                discharge_limit_item, power_limit
            )

            if success:
                _LOGGER.debug("Discharge power limit set to %s W", power_limit)
            else:
                _LOGGER.error(
                    "Failed to set discharge power limit to %s W", power_limit
                )

        except (OSError, ValueError, TypeError, AttributeError) as err:
            _LOGGER.error("Error setting discharge power limit: %s", err)
            return False
        else:
            return success

    def _get_pilot_item(self, item_name: str) -> SAXItem | None:
        """Get pilot item by name from PILOT_ITEMS."""
        for item in PILOT_ITEMS:
            if item.name == item_name:
                return item
        return None

    def _get_modbus_item(self, item_name: str) -> Any | None:
        """Get modbus item by name for backwards compatibility."""
        # Get modbus items for master battery
        api_items = self.sax_data.get_modbus_items_for_battery(
            self.coordinator.battery_id
        )

        for item in api_items:
            if hasattr(item, "name") and item.name == item_name:
                return item

        return None

    @property
    def solar_charging_enabled(self) -> bool | None:
        """Return current solar charging state."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        return self.coordinator.data.get(SOLAR_CHARGING_SWITCH) == 1

    @property
    def manual_control_enabled(self) -> bool | None:
        """Return current manual control state."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        return self.coordinator.data.get(MANUAL_CONTROL_SWITCH) == 1

    @property
    def current_charge_power_limit(self) -> int | None:
        """Return current charge power limit."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        return self.coordinator.data.get("sax_max_charge_power")

    @property
    def current_discharge_power_limit(self) -> int | None:
        """Return current discharge power limit."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        return self.coordinator.data.get("sax_max_discharge_power")


class SAXBatterySolarChargingSwitch(
    CoordinatorEntity[SAXBatteryCoordinator], SwitchEntity
):
    """Switch to control solar charging mode."""

    def __init__(
        self,
        pilot: SAXBatteryPilot,
        coordinator: SAXBatteryCoordinator,
        pilot_item: SAXItem,
        battery_id: str,
    ) -> None:
        """Initialize the solar charging switch."""
        super().__init__(coordinator)
        self._pilot = pilot
        self._pilot_item = pilot_item
        self._battery_id = battery_id

        # Generate unique ID using class name pattern
        item_name = self._pilot_item.name.removeprefix("sax_").replace("_switch", "")
        self._attr_unique_id = f"sax_{self._battery_id}_{item_name}"

        # Set entity description from pilot item if available
        if self._pilot_item.entitydescription is not None:
            self.entity_description = self._pilot_item.entitydescription  # type: ignore[assignment]

        # Set name from entity description or fallback
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "name")
            and isinstance(self.entity_description.name, str)
        ):
            base_name = self.entity_description.name
            # Remove "Sax " prefix if it exists
            base_name = base_name.removeprefix("Sax ")
        else:
            # Fallback name generation
            base_name = self._pilot_item.name.replace("_", " ").title()

        # Format battery display name
        battery_display = self._battery_id.replace("battery_", "Battery ").title()
        self._attr_name = f"Sax {battery_display} {base_name}"

        # Set icon and category
        self._attr_icon = "mdi:solar-power"
        self._attr_entity_category = determine_entity_category(pilot_item)

        # Override with entity description properties if available
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "icon")
            and self.entity_description.icon
        ):
            self._attr_icon = self.entity_description.icon

        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "entity_category")
        ):
            self._attr_entity_category = self.entity_description.entity_category

    @property
    def device_info(self) -> Any:
        """Return device info."""
        return self.coordinator.sax_data.get_device_info(self._battery_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on solar charging."""
        success = await self._pilot.set_solar_charging(True)
        if not success:
            raise HomeAssistantError("Failed to enable solar charging")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off solar charging."""
        success = await self._pilot.set_solar_charging(False)
        if not success:
            raise HomeAssistantError("Failed to disable solar charging")

    @property
    def is_on(self) -> bool | None:
        """Return true if solar charging is enabled."""
        return self._pilot.solar_charging_enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if not self.coordinator.last_update_success:
            return None

        return {
            "battery_id": self._battery_id,
            "manual_control_enabled": self._pilot.manual_control_enabled,
            "last_updated": self.coordinator.last_update_success_time,
        }


class SAXBatteryManualControlSwitch(
    CoordinatorEntity[SAXBatteryCoordinator], SwitchEntity
):
    """Switch to enable/disable manual control functionality."""

    def __init__(
        self,
        pilot: SAXBatteryPilot,
        coordinator: SAXBatteryCoordinator,
        pilot_item: SAXItem,
        battery_id: str,
    ) -> None:
        """Initialize the manual control switch."""
        super().__init__(coordinator)
        self._pilot = pilot
        self._pilot_item = pilot_item
        self._battery_id = battery_id

        # Generate unique ID using class name pattern
        item_name = self._pilot_item.name.removeprefix("sax_").replace("_switch", "")
        self._attr_unique_id = f"sax_{self._battery_id}_{item_name}"

        # Set entity description from pilot item if available
        if self._pilot_item.entitydescription is not None:
            self.entity_description = self._pilot_item.entitydescription  # type: ignore[assignment]

        # Set name from entity description or fallback
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "name")
            and isinstance(self.entity_description.name, str)
        ):
            base_name = self.entity_description.name
            # Remove "Sax " prefix if it exists
            base_name = base_name.removeprefix("Sax ")
        else:
            # Fallback name generation
            base_name = self._pilot_item.name.replace("_", " ").title()

        # Format battery display name
        battery_display = self._battery_id.replace("battery_", "Battery ").title()
        self._attr_name = f"Sax {battery_display} {base_name}"

        # Set default icon and category
        self._attr_icon = "mdi:cog"
        self._attr_entity_category = EntityCategory.CONFIG

        # Override with entity description properties if available
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "icon")
            and self.entity_description.icon
        ):
            self._attr_icon = self.entity_description.icon

        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "entity_category")
        ):
            self._attr_entity_category = self.entity_description.entity_category

    @property
    def device_info(self) -> Any:
        """Return device info."""
        return self.coordinator.sax_data.get_device_info(self._battery_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable manual control functionality."""
        success = await self._pilot.set_manual_control(True)
        if not success:
            raise HomeAssistantError("Failed to enable manual control")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable manual control functionality."""
        success = await self._pilot.set_manual_control(False)
        if not success:
            raise HomeAssistantError("Failed to disable manual control")

    @property
    def is_on(self) -> bool | None:
        """Return true if manual control is enabled."""
        return self._pilot.manual_control_enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if not self.coordinator.last_update_success:
            return None

        return {
            "battery_id": self._battery_id,
            "charge_power_limit": self._pilot.current_charge_power_limit,
            "discharge_power_limit": self._pilot.current_discharge_power_limit,
            "solar_charging_enabled": self._pilot.solar_charging_enabled,
            "last_updated": self.coordinator.last_update_success_time,
        }


class SAXBatteryGenericPilotSwitch(
    CoordinatorEntity[SAXBatteryCoordinator], SwitchEntity
):
    """Generic pilot switch for unknown switch types."""

    def __init__(
        self,
        pilot: SAXBatteryPilot,
        coordinator: SAXBatteryCoordinator,
        pilot_item: SAXItem,
        battery_id: str,
    ) -> None:
        """Initialize the generic pilot switch."""
        super().__init__(coordinator)
        self._pilot = pilot
        self._pilot_item = pilot_item
        self._battery_id = battery_id

        # Generate unique ID using class name pattern
        item_name = self._pilot_item.name.removeprefix("sax_")
        self._attr_unique_id = f"sax_{self._battery_id}_{item_name}"

        # Set entity description from pilot item if available
        if self._pilot_item.entitydescription is not None:
            self.entity_description = self._pilot_item.entitydescription  # type: ignore[assignment]

        # Set name from entity description or fallback
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "name")
            and isinstance(self.entity_description.name, str)
        ):
            base_name = self.entity_description.name
            # Remove "Sax " prefix if it exists
            base_name = base_name.removeprefix("Sax ")
        else:
            # Fallback name generation
            base_name = self._pilot_item.name.replace("_", " ").title()

        # Format battery display name
        battery_display = self._battery_id.replace("battery_", "Battery ").title()
        self._attr_name = f"Sax {battery_display} {base_name}"

        # Set default properties
        self._attr_icon = "mdi:toggle-switch"
        self._attr_entity_category = EntityCategory.CONFIG

        # Override with entity description properties if available
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "icon")
            and self.entity_description.icon
        ):
            self._attr_icon = self.entity_description.icon

        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "entity_category")
        ):
            self._attr_entity_category = self.entity_description.entity_category

    @property
    def device_info(self) -> Any:
        """Return device info."""
        return self.coordinator.sax_data.get_device_info(self._battery_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the generic switch."""
        # Generic implementation - update coordinator data directly
        if self.coordinator.data is None:
            self.coordinator.data = {}
        self.coordinator.data[self._pilot_item.name] = 1
        self.coordinator.async_set_updated_data(self.coordinator.data)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the generic switch."""
        # Generic implementation - update coordinator data directly
        if self.coordinator.data is None:
            self.coordinator.data = {}
        self.coordinator.data[self._pilot_item.name] = 0
        self.coordinator.async_set_updated_data(self.coordinator.data)

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is enabled."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        value = self.coordinator.data.get(self._pilot_item.name)
        if value is None:
            return None

        # Handle different value types
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value > 0
        if isinstance(value, str):
            return value.lower() in ("1", "true", "on", "yes")

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if not self.coordinator.last_update_success:
            return None

        return {
            "battery_id": self._battery_id,
            "pilot_item_name": self._pilot_item.name,
            "last_updated": self.coordinator.last_update_success_time,
        }
