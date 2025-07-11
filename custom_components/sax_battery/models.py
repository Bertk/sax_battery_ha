"""Data models for SAX Battery integration."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, PILOT_ITEMS
from .enums import DeviceConstants
from .items import ModbusItem, SAXItem


class BatteryRole(Enum):
    """Battery roles in the system."""

    MASTER = "master"
    SLAVE = "slave"


class CommunicationInterface(Enum):
    """Communication interface types."""

    ETHERNET = "ethernet"
    RS485 = "rs485"


@dataclass
class BatteryConfig:
    """Configuration for a single battery."""

    battery_id: str
    host: str
    port: int = 502
    slave_id: int = 64
    role: BatteryRole = BatteryRole.SLAVE
    phase: str = "L1"
    communication: CommunicationInterface = CommunicationInterface.ETHERNET


@dataclass
class SmartMeterData:
    """Smart meter data container."""

    total_power: float | None = None
    grid_frequency: float | None = None
    voltage_l1: float | None = None
    voltage_l2: float | None = None
    voltage_l3: float | None = None
    current_l1: float | None = None
    current_l2: float | None = None
    current_l3: float | None = None
    import_power: float | None = None
    export_power: float | None = None
    active_power_l1: float | None = None
    active_power_l2: float | None = None
    active_power_l3: float | None = None
    last_update: float = field(default_factory=time.time)

    def is_data_fresh(self, max_age_seconds: int = 60) -> bool:
        """Check if smart meter data is fresh."""
        return (time.time() - self.last_update) < max_age_seconds


@dataclass
class BatteryDevice:
    """Represents a single battery device."""

    battery_id: str
    host: str
    port: int = 502
    slave_id: int = 64
    role: str = "slave"
    phase: str = "L1"
    data: dict[str, Any] = field(default_factory=dict)
    last_update: float = field(default_factory=time.time)

    async def async_update(self) -> None:
        """Update battery data via Modbus."""
        self.last_update = time.time()

    @property
    def is_master(self) -> bool:
        """Check if this battery is the master."""
        return self.role == "master"


class SAXBatteryData:
    """Container for all SAX battery system data."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize SAX battery data."""
        self.config_entry = config_entry
        self.entry = config_entry  # For backward compatibility
        self.batteries: dict[str, BatteryDevice] = {}
        self.coordinators: dict[str, Any] = {}
        self.coordinator: Any = None  # For backward compatibility
        self.smart_meter_data = SmartMeterData()
        self._master_battery_id: str | None = None
        self.device_id: str = config_entry.entry_id
        self.battery_configs: dict[str, BatteryConfig] = {}
        self.modbus_api: Any = None
        self.pilot: Any = None
        self.system_power_limits: dict[str, float] = {}
        self.phase_balancing_enabled: bool = True

    @property
    def config(self) -> dict[str, Any]:
        """Get configuration data from config entry."""
        return dict(self.config_entry.data)

    @property
    def options(self) -> dict[str, Any]:
        """Get options data from config entry."""
        return dict(self.config_entry.options)

    @property
    def master_battery_id(self) -> str | None:
        """Get the master battery ID."""
        if self._master_battery_id:
            return self._master_battery_id

        for battery_id, battery in self.batteries.items():
            if battery.is_master:
                self._master_battery_id = battery_id
                return battery_id

        if self.batteries:
            first_battery_id = next(iter(self.batteries))
            self._master_battery_id = first_battery_id
            return first_battery_id

        return None

    @master_battery_id.setter
    def master_battery_id(self, value: str | None) -> None:
        """Set the master battery ID."""
        self._master_battery_id = value

    async def async_setup(self) -> bool:
        """Set up the battery data."""
        return True

    def should_poll_smart_meter(self, battery_id: str) -> bool:
        """Check if this battery should poll smart meter data."""
        return battery_id == self.master_battery_id

    def get_modbus_items_for_battery(self, battery_id: str) -> list[ModbusItem]:
        """Get Modbus items for a specific battery."""
        return []

    def get_sax_items_for_battery(self, battery_id: str) -> list[SAXItem]:
        """Get SAX items for a specific battery."""
        if not self.should_poll_smart_meter(battery_id):
            return []

        battery = self.batteries.get(battery_id)
        if not battery:
            return []

        available_items = []
        for item in PILOT_ITEMS:
            if self._should_include_sax_item(item, battery):
                available_items.append(item)

        return available_items

    def _should_include_sax_item(self, item: SAXItem, battery: BatteryDevice) -> bool:
        """Check if SAX item should be included for this battery."""
        if getattr(item, "master_only", False) and not battery.is_master:
            return False

        item_device = getattr(item, "device", None)
        if item_device and item_device != DeviceConstants.SYS:
            config_device = self.config.get("device_type")
            if config_device and item_device.value != config_device:
                return False

        required_features = getattr(item, "required_features", None)
        if required_features:
            available_features = self.config.get("features", [])
            if not all(feature in available_features for feature in required_features):
                return False

        return True

    def get_device_info(self, battery_id: str) -> DeviceInfo:
        """Get device info for a battery."""
        battery = self.batteries.get(battery_id)
        if not battery:
            raise ValueError(f"Battery {battery_id} not found")

        return DeviceInfo(
            identifiers={(DOMAIN, battery_id)},
            name=f"SAX Battery {battery_id.upper()}",
            manufacturer="SAX-power",
            model="Energy Storage System",
            sw_version="1.0.0",
            configuration_url=f"http://{battery.host}:{battery.port}",
        )

    def add_battery(
        self,
        battery_id: str,
        host: str,
        port: int = 502,
        slave_id: int = 64,
        role: str = "slave",
        phase: str = "L1",
    ) -> BatteryDevice:
        """Add a battery to the system."""
        battery = BatteryDevice(
            battery_id=battery_id,
            host=host,
            port=port,
            slave_id=slave_id,
            role=role,
            phase=phase,
        )
        self.batteries[battery_id] = battery

        if role == "master":
            self._master_battery_id = battery_id

        return battery

    def remove_battery(self, battery_id: str) -> None:
        """Remove a battery from the system."""
        if battery_id in self.batteries:
            del self.batteries[battery_id]

        if battery_id in self.coordinators:
            del self.coordinators[battery_id]

        if self._master_battery_id == battery_id:
            self._master_battery_id = None

    def get_battery_by_role(self, role: str) -> BatteryDevice | None:
        """Get battery by role (master/slave)."""
        for battery in self.batteries.values():
            if battery.role == role:
                return battery
        return None

    def get_master_battery(self) -> BatteryDevice | None:
        """Get the master battery."""
        return self.get_battery_by_role("master")

    def get_slave_batteries(self) -> list[BatteryDevice]:
        """Get all slave batteries."""
        return [
            battery for battery in self.batteries.values() if battery.role == "slave"
        ]

    def get_batteries_by_phase(self, phase: str) -> list[BatteryDevice]:
        """Get all batteries connected to a specific phase."""
        return [
            battery for battery in self.batteries.values() if battery.phase == phase
        ]

    def get_polling_interval_for_battery(self, battery_id: str) -> int:
        """Get polling interval for a specific battery."""
        battery = self.batteries.get(battery_id)
        if not battery:
            return 10

        # Master battery polls more frequently
        if battery.is_master:
            return 5
        return 10

    def get_total_system_power(self) -> float:
        """Get total system power from all batteries."""
        total_power = 0.0
        for battery in self.batteries.values():
            power = battery.data.get("power", 0.0)
            if isinstance(power, (int, float)):
                total_power += power
        return total_power

    def get_average_soc(self) -> float | None:
        """Get average state of charge across all batteries."""
        soc_values = []
        for battery in self.batteries.values():
            soc = battery.data.get("soc")
            if isinstance(soc, (int, float)):
                soc_values.append(soc)

        if not soc_values:
            return None

        return sum(soc_values) / len(soc_values)

    def get_system_status(self) -> dict[str, Any]:
        """Get overall system status."""
        return {
            "total_batteries": len(self.batteries),
            "master_battery": self.master_battery_id,
            "smart_meter_fresh": self.smart_meter_data.is_data_fresh(),
            "last_smart_meter_update": self.smart_meter_data.last_update,
            "batteries": {
                battery_id: {
                    "role": battery.role,
                    "phase": battery.phase,
                    "host": battery.host,
                    "last_update": battery.last_update,
                }
                for battery_id, battery in self.batteries.items()
            },
        }


# Type alias for backward compatibility
SAXBatterySystem = SAXBatteryData
