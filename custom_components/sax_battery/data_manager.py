"""Data manager for SAX Battery integration."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from const import SAX_POWER, SAX_SOC


@dataclass
class SmartMeterData:
    """Data class for smart meter readings."""

    current_l1: Optional[Decimal] = None
    current_l2: Optional[Decimal] = None
    current_l3: Optional[Decimal] = None
    voltage_l1: Optional[Decimal] = None
    voltage_l2: Optional[Decimal] = None
    voltage_l3: Optional[Decimal] = None
    total_power: Optional[Decimal] = None


@dataclass
class AccumulatedData:
    """Data class for accumulated values across batteries."""

    combined_power: Decimal = Decimal(0)
    combined_soc: Decimal = Decimal(0)
    total_energy_produced: Optional[Decimal] = None
    total_energy_consumed: Optional[Decimal] = None
    smartmeter: SmartMeterData = field(default_factory=SmartMeterData)


@dataclass
class BatteryData:
    """Data class representing individual battery data."""

    data_manager: "SAXBatteryDataManager"
    data: dict[str, Any]

    @property
    def device_id(self) -> str:
        """Get the device ID from the data manager."""
        return self.data_manager.device_id


@dataclass
class SAXBatteryDataManager:
    """Class to manage data for SAX Battery integration."""

    _device_id: str
    max_batteries: int = 3
    batteries: dict[str, "BatteryData"] = field(default_factory=dict)
    combined_data: dict[str, float | int | str | None] = field(default_factory=dict)
    accumulated: AccumulatedData = field(default_factory=AccumulatedData)

    def add_battery(self, battery_id: str, battery_data: BatteryData) -> bool:
        """Add a battery if under max limit."""
        if len(self.batteries) < self.max_batteries:
            self.batteries[battery_id] = battery_data
            return True
        return False

    def get_battery(self, battery_id: str) -> Optional[BatteryData]:
        """Get battery data by ID."""
        return self.batteries.get(battery_id)

    def update_accumulated_data(self) -> None:
        """Update accumulated values from all batteries."""
        total_power = Decimal(0)
        total_soc = Decimal(0)
        valid_batteries = 0

        for battery in self.batteries.values():
            if power := battery.data.get(SAX_POWER):
                total_power += Decimal(str(power))
            if soc := battery.data.get(SAX_SOC):
                total_soc += Decimal(str(soc))
                valid_batteries += 1

        self.accumulated.combined_power = total_power
        if valid_batteries > 0:
            self.accumulated.combined_soc = total_soc / valid_batteries

    @property
    def device_id(self) -> str:
        """Get the device ID.

        Returns:
            str: The device identifier

        """
        return self._device_id
