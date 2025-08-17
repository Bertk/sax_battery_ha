"""Utility functions for SAX Battery integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory

from .const import (
    CONF_BATTERY_COUNT,
    CONF_LIMIT_POWER,
    CONF_PILOT_FROM_HA,
    LIMIT_MAX_CHARGE_PER_BATTERY,
    LIMIT_MAX_DISCHARGE_PER_BATTERY,
    MAX_SUPPORTED_BATTERIES,
    MODBUS_BATTERY_PILOT_ITEMS,
    MODBUS_BATTERY_REALTIME_ITEMS,
    REGISTER_ACCESS_CONTROL,
    WRITE_ONLY_REGISTERS,
)
from .items import ModbusItem, SAXItem


def create_entity_unique_id(
    battery_id: str, modbus_item: ModbusItem | SAXItem, index: int
) -> str:
    """Create unique ID for an entity.

    Args:
        battery_id: Battery identifier (e.g., "battery_a")
        modbus_item: Modbus item
        index: Item index

    Returns:
        Unique entity ID without duplicate battery references

    """
    # Remove semantic suffixes like "(Calculated)" from SAXItem names
    clean_name = modbus_item.name.replace(" (Calculated)", "")

    # Normalize the clean name to lowercase for comparison
    clean_name_lower = clean_name.lower()
    battery_id_lower = battery_id.lower()

    # Extract battery letter for more specific checking
    battery_letter = battery_id.split("_")[-1] if "_" in battery_id else battery_id

    # More comprehensive battery reference patterns to check
    battery_patterns = [
        battery_id_lower,  # "battery_a"
        f"sax_{battery_id_lower}",  # "sax_battery_a"
        f"{battery_letter}_",  # "a_" at start
        f"_{battery_letter}_",  # "_a_" in middle
        f"_{battery_letter}",  # "_a" at end
    ]

    # Check if any battery pattern is already in the name
    contains_battery_ref = any(
        pattern in clean_name_lower for pattern in battery_patterns
    )

    if contains_battery_ref:
        # If battery reference is already in the name, use it as-is
        return f"{clean_name}_{index}"
    else:  # noqa: RET505
        # If no battery reference, add battery_id prefix
        return f"{battery_id}_{clean_name}_{index}"


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
    modbus_item: ModbusItem,
    config_entry: ConfigEntry,
    battery_id: str,
) -> bool:
    """Determine if entity should be included based on configuration.

    Args:
        modbus_item: Modbus item
        config_entry: Config entry
        battery_id: Battery identifier

    Returns:
        True if entity should be included

    """
    # Filter out write-only registers that cannot be read
    if hasattr(modbus_item, "address") and modbus_item.address in WRITE_ONLY_REGISTERS:
        return False

    device_type = getattr(modbus_item, "device", None)
    if device_type:
        config_device = config_entry.data.get("device_type")
        if config_device and device_type != config_device:
            return False

    master_only = getattr(modbus_item, "master_only", False)
    if master_only:
        battery_configs = config_entry.data.get("batteries", {})
        battery_config = battery_configs.get(battery_id, {})
        return bool(battery_config.get("role") == "master")

    required_features = getattr(modbus_item, "required_features", None)
    if required_features:
        available_features = config_entry.data.get("features", [])
        return bool(all(feature in available_features for feature in required_features))

    return True


def calculate_system_max_charge(battery_count: int) -> int:
    """Calculate maximum charge power for the entire system.

    Args:
        battery_count: Number of batteries in the system (1-3)

    Returns:
        Maximum charge power in watts for the system

    """
    if battery_count < 1 or battery_count > MAX_SUPPORTED_BATTERIES:
        msg = f"Battery count must be between 1 and {MAX_SUPPORTED_BATTERIES}, got {battery_count}"
        raise ValueError(msg)

    return battery_count * LIMIT_MAX_CHARGE_PER_BATTERY


def calculate_system_max_discharge(battery_count: int) -> int:
    """Calculate maximum discharge power for the entire system.

    Args:
        battery_count: Number of batteries in the system (1-3)

    Returns:
        Maximum discharge power in watts for the system

    """
    if battery_count < 1 or battery_count > MAX_SUPPORTED_BATTERIES:
        msg = f"Battery count must be between 1 and {MAX_SUPPORTED_BATTERIES}, got {battery_count}"
        raise ValueError(msg)

    return battery_count * LIMIT_MAX_DISCHARGE_PER_BATTERY


def get_battery_limits_for_count(battery_count: int) -> tuple[int, int]:
    """Get both charge and discharge limits for a given battery count.

    Args:
        battery_count: Number of batteries in the system (1-3)

    Returns:
        Tuple of (max_charge, max_discharge) in watts

    """
    return (
        calculate_system_max_charge(battery_count),
        calculate_system_max_discharge(battery_count),
    )


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


# def should_load_pilot_module(
# config_data: dict[str, Any], is_master: bool = False
# ) -> bool:
# """Determine if pilot.py module should be loaded based on configuration."""
# access_config = create_register_access_config(config_data, is_master)
# return access_config.should_load_pilot_module()


def get_writable_registers(
    config_data: dict[str, Any], is_master: bool = False
) -> set[int]:
    """Get set of registers that are writable based on current configuration."""
    access_config = create_register_access_config(config_data, is_master)
    return access_config.get_writable_registers()


# def validate_write_access(
#     address: int, config_data: dict[str, Any], is_master: bool = False
# ) -> bool:
#     """Validate if a write operation to a register is allowed."""
#     access_config = create_register_access_config(config_data, is_master)
#     return access_config.can_write_register(address)


# def get_modbus_battery_items(
#     config_data: dict[str, Any], is_master: bool = False
# ) -> list[ModbusItem]:
#     """Get all battery modbus items with proper configuration."""
#     access_config = create_register_access_config(config_data, is_master)

#     return (
#         get_battery_realtime_items(access_config)
#         + MODBUS_BATTERY_STATIC_ITEMS
#         + MODBUS_BATTERY_SMARTMETER_ITEMS
#     )


# Configuration validation helpers
# def validate_configuration(config_data: dict[str, Any]) -> list[str]:
#     """Validate configuration and return list of warnings/errors."""
#     warnings = []

#     pilot_from_ha = config_data.get(CONF_PILOT_FROM_HA, False)
#     limit_power = config_data.get(CONF_LIMIT_POWER, False)

#     if not pilot_from_ha:
#         warnings.append(
#             "Pilot control disabled: Registers 41 (Nominal Power) and 42 (Nominal Factor) not writeable"
#         )

#     if not limit_power:
#         warnings.append(
#             "Power limiting disabled: Registers 43 (Max Discharge) and 44 (Max Charge) not writeable"
#         )

#     if not pilot_from_ha and not limit_power:
#         warnings.append(
#             "All write operations disabled: System is in monitoring-only mode"
#         )

#     return warnings


@dataclass(frozen=True)
class RegisterAccessConfig:
    """Configuration for register access control."""

    pilot_from_ha: bool = False
    limit_power: bool = False
    is_master_battery: bool = False
    battery_count: int = 1

    def can_write_register(self, address: int) -> bool:
        """Check if a register can be written to based on configuration."""
        if address in WRITE_ONLY_REGISTERS:
            required_config = REGISTER_ACCESS_CONTROL.get(address)
            if required_config == CONF_PILOT_FROM_HA:
                return self.pilot_from_ha and self.is_master_battery
            elif required_config == CONF_LIMIT_POWER:  # noqa: RET505
                return self.limit_power and self.is_master_battery
        return True

    # def should_load_pilot_module(self) -> bool:
    #     """Determine if pilot.py module should be loaded."""
    #     return self.pilot_from_ha and self.is_master_battery

    def get_system_max_charge(self) -> int:
        """Get system maximum charge based on battery count."""
        return calculate_system_max_charge(self.battery_count)

    def get_system_max_discharge(self) -> int:
        """Get system maximum discharge based on battery count."""
        return calculate_system_max_discharge(self.battery_count)

    def get_writable_registers(self) -> set[int]:
        """Get set of registers that are writable based on configuration."""
        writable = set()

        # Add pilot registers if enabled
        if self.pilot_from_ha and self.is_master_battery:
            writable.update({41, 42})  # Nominal Power, Nominal Factor

        # Add power limiting registers if enabled
        if self.limit_power and self.is_master_battery:
            writable.update({43, 44})  # Max Discharge, Max Charge

        return writable


# Entity descriptions for read-only versions
def get_battery_realtime_items(access_config: RegisterAccessConfig) -> list[ModbusItem]:
    """Get battery realtime items based on access configuration."""
    items = MODBUS_BATTERY_REALTIME_ITEMS

    # Add writable items based on configuration
    if access_config.pilot_from_ha:
        items.extend(MODBUS_BATTERY_PILOT_ITEMS)

    return items
