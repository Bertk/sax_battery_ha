"""Utility functions for SAX Battery integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory

from .const import (
    CONF_BATTERY_COUNT,
    CONF_LIMIT_POWER,
    CONF_MASTER_BATTERY,
    CONF_PILOT_FROM_HA,
    MODBUS_BATTERY_PILOT_CONTROL_ITEMS,
    MODBUS_BATTERY_POWER_LIMIT_ITEMS,
    MODBUS_BATTERY_REALTIME_ITEMS,
    WRITE_ONLY_REGISTERS,
)
from .items import ModbusItem, SAXItem

_LOGGER = logging.getLogger(__name__)


def format_battery_display_name(battery_id: str) -> str:
    """Format battery ID for display purposes.

    This function is primarily used for device names, not entity names.
    Entity names should not include battery prefix when _attr_has_entity_name = True.

    Args:
        battery_id: Battery identifier (e.g., "battery_a", "battery_b", "cluster")

    Returns:
        Formatted display name (e.g., "Battery A", "Battery B", "Cluster")

    """
    if battery_id.lower().startswith("battery_"):
        # Remove "battery_" prefix and capitalize the letter
        battery_letter = battery_id[8:].upper()
        return f"Battery {battery_letter}"
    if battery_id == "cluster":
        return "Cluster"
    return battery_id.replace("_", " ").title()


def determine_entity_category(
    modbus_item: ModbusItem | SAXItem,
) -> EntityCategory | None:
    """Determine entity category based on modbus item.

    Args:
        modbus_item: Modbus item

    Returns:
        Entity category or None

    """
    # Check entitydescription for entity_category first
    if hasattr(modbus_item, "entitydescription") and modbus_item.entitydescription:
        if (
            hasattr(modbus_item.entitydescription, "entity_category")
            and modbus_item.entitydescription.entity_category
        ):
            return modbus_item.entitydescription.entity_category

    diagnostic_keywords = ["debug", "diagnostic", "status", "error", "version"]
    config_keywords = ["config", "setting", "limit", "max_", "pilot_", "enable_"]

    item_name_lower = modbus_item.name.lower()

    if any(keyword in item_name_lower for keyword in diagnostic_keywords):
        return EntityCategory.DIAGNOSTIC

    if any(keyword in item_name_lower for keyword in config_keywords):
        return EntityCategory.CONFIG

    return None


def should_include_entity(
    item: ModbusItem | SAXItem,
    config_entry: ConfigEntry,
    battery_id: str,
) -> bool:
    """Determine if entity should be included based on configuration."""
    # Handle write-only registers first (specific case)
    if hasattr(item, "address") and item.address in WRITE_ONLY_REGISTERS:
        # Get master battery ID from configuration
        master_battery_id = config_entry.data.get(CONF_MASTER_BATTERY, "battery_a")
        is_master = battery_id == master_battery_id

        # Pilot registers (41, 42) require pilot_from_ha AND master battery
        if item.address in {41, 42}:
            return config_entry.data.get(CONF_PILOT_FROM_HA, False) and is_master
        # Power limit registers (43, 44) require limit_power AND master battery
        elif item.address in {43, 44}:  # noqa: RET505
            return config_entry.data.get(CONF_LIMIT_POWER, False) and is_master
        else:
            # Unknown write-only register
            return False

    # For ModbusItem, check additional constraints (general case)
    if isinstance(item, ModbusItem):
        device_type = getattr(item, "device", None)
        if device_type:
            config_device = config_entry.data.get("device_type")
            if config_device and device_type != config_device:
                return False

        master_only = getattr(item, "master_only", False)
        if master_only:
            battery_configs = config_entry.data.get("batteries", {})
            battery_config = battery_configs.get(battery_id, {})
            return bool(battery_config.get("role") == "master")

        required_features = getattr(item, "required_features", None)
        if required_features:
            available_features = config_entry.data.get("features", [])
            return bool(
                all(feature in available_features for feature in required_features)
            )

    # Default: include the entity
    return True


def create_register_access_config(
    config_data: dict[str, Any], is_master: bool = False
) -> RegisterAccessConfig:
    """Create register access configuration.

    Args:
        config_data: Configuration data from config entry
        is_master: Whether this is the master battery

    Returns:
        RegisterAccessConfig with dynamic limits based on battery count

    """
    battery_count = config_data.get(CONF_BATTERY_COUNT, 1)

    return RegisterAccessConfig(
        pilot_from_ha=config_data.get(CONF_PILOT_FROM_HA, False),
        limit_power=config_data.get(CONF_LIMIT_POWER, False),
        is_master_battery=is_master,
        battery_count=battery_count,
    )


def get_writable_registers(
    config_data: dict[str, Any], is_master: bool = False
) -> set[int]:
    """Get set of registers that are writable based on current configuration."""
    access_config = create_register_access_config(config_data, is_master)
    return access_config.get_writable_registers()


@dataclass(frozen=True)
class RegisterAccessConfig:
    """Configuration for register access control."""

    pilot_from_ha: bool = False
    limit_power: bool = False
    is_master_battery: bool = False
    battery_count: int = 1

    def get_writable_registers(self) -> set[int]:
        """Get set of writable register addresses."""
        writable = set()

        # Pilot control registers require both pilot_from_ha AND master battery
        if self.pilot_from_ha and self.is_master_battery:
            writable.update({41, 42})

        # Power limit registers require both limit_power AND master battery
        if self.limit_power and self.is_master_battery:
            writable.update({43, 44})

        return writable


def get_battery_realtime_items(access_config: RegisterAccessConfig) -> list[ModbusItem]:
    """Get battery realtime items based on access configuration.

    Only master batteries get write-only control items (registers 41-44).
    """
    items = list(MODBUS_BATTERY_REALTIME_ITEMS)  # Make a copy

    # Add pilot control items (registers 41, 42) ONLY for master battery when pilot is enabled
    if access_config.pilot_from_ha and access_config.is_master_battery:
        items.extend(MODBUS_BATTERY_PILOT_CONTROL_ITEMS)

    # Add power limit items (registers 43, 44) ONLY for master battery when power limits are enabled
    if access_config.limit_power and access_config.is_master_battery:
        items.extend(MODBUS_BATTERY_POWER_LIMIT_ITEMS)

    return items
