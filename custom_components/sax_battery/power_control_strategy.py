"""Power control abstraction layer for SAX Battery integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import TYPE_CHECKING

from .const_sunspec import (
    SAX_SUNSPEC_CONTROL_MODE,
    SAX_SUNSPEC_POWER_SETPOINT,
    SAX_SUNSPEC_REFERENCE_POWER,
    SAX_SUNSPEC_SETPOINT_TIMEOUT,
)
from .entity_keys import SAX_POWER_SETPOINT, SAX_POWER_SETPOINT_FACTOR
from .items import ModbusItem

if TYPE_CHECKING:
    from .coordinator import SAXBatteryCoordinator

_LOGGER = logging.getLogger(__name__)


class PowerControlStrategy(ABC):
    """Abstract interface for power setpoint and control operations."""

    @abstractmethod
    async def async_set_power(self, target_watts: float, timeout_s: int = 60) -> bool:
        """Set commanded power setpoint in Watts (negative for charge, positive for discharge)."""

    @abstractmethod
    async def async_set_mode_zero_balance(self) -> bool:
        """Set battery system to autonomous 0-grid-balancing mode."""

    @abstractmethod
    async def async_set_mode_manual(self) -> bool:
        """Set battery system to manual setpoint control mode."""

    @abstractmethod
    def get_max_power_rating(self) -> float:
        """Get the total maximum power rating in Watts."""


class LegacyPowerControlStrategy(PowerControlStrategy):
    """Legacy power control strategy using register 41 and register 42."""

    def __init__(self, coordinator: SAXBatteryCoordinator) -> None:
        """Initialize legacy strategy."""
        self.coordinator = coordinator

    def get_max_power_rating(self) -> float:
        """Return maximum power rating based on battery count."""
        battery_count = len(self.coordinator.sax_data.coordinators) or 1
        return float(battery_count * 4600)

    async def async_set_power(self, target_watts: float, timeout_s: int = 60) -> bool:
        """Write nominal power and factor atomically."""
        power_item = self.coordinator.sax_data.get_item_by_name(SAX_POWER_SETPOINT)
        if not power_item or not isinstance(power_item, ModbusItem):
            _LOGGER.error("SAX_POWER_SETPOINT item not found")
            return False

        factor_item = self.coordinator.sax_data.get_item_by_name(
            SAX_POWER_SETPOINT_FACTOR
        )
        factor = 100
        if factor_item and self.coordinator.data:
            factor_val = self.coordinator.data.get(factor_item.name)
            if factor_val is not None:
                factor = int(factor_val)

        return await self.coordinator.async_write_power_control_value(
            power_item, int(target_watts), factor
        )

    async def async_set_mode_zero_balance(self) -> bool:
        """Legacy mode achieves zero balance via software PID loop in power manager."""
        return True

    async def async_set_mode_manual(self) -> bool:
        """Legacy mode is ready for setpoint writes."""
        return True


class SunSpecPowerControlStrategy(PowerControlStrategy):
    """SunSpec power control strategy using Model 123 registers (40049-40051)."""

    def __init__(self, coordinator: SAXBatteryCoordinator) -> None:
        """Initialize SunSpec strategy."""
        self.coordinator = coordinator

    def get_max_power_rating(self) -> float:
        """Return maximum power reference from register 40053 or calculate."""
        if self.coordinator.data:
            ref_power = self.coordinator.data.get(SAX_SUNSPEC_REFERENCE_POWER)
            if ref_power and isinstance(ref_power, (int, float)) and ref_power > 0:
                return float(ref_power)
        battery_count = len(self.coordinator.sax_data.coordinators) or 1
        return float(battery_count * 4600)

    async def async_set_power(self, target_watts: float, timeout_s: int = 60) -> bool:
        """Convert target watts to percentage (-100 to +100) and write to SunSpec."""
        max_power = self.get_max_power_rating()
        if max_power <= 0:
            max_power = 4600.0

        pct = (target_watts / max_power) * 100.0
        pct = max(-100.0, min(100.0, pct))

        setpoint_item = self.coordinator.sax_data.get_item_by_name(
            SAX_SUNSPEC_POWER_SETPOINT
        )
        if setpoint_item and isinstance(setpoint_item, ModbusItem):
            await self.coordinator.async_write_number_value(setpoint_item, int(pct))

        timeout_item = self.coordinator.sax_data.get_item_by_name(
            SAX_SUNSPEC_SETPOINT_TIMEOUT
        )
        if timeout_item and isinstance(timeout_item, ModbusItem):
            await self.coordinator.async_write_number_value(
                timeout_item, min(300, max(1, timeout_s))
            )

        mode_item = self.coordinator.sax_data.get_item_by_name(SAX_SUNSPEC_CONTROL_MODE)
        if mode_item and isinstance(mode_item, ModbusItem):
            await self.coordinator.async_write_number_value(mode_item, 1)

        return True

    async def async_set_mode_zero_balance(self) -> bool:
        """Set Mode register 40051 to 0 (SmartMeter 0-balancing mode)."""
        mode_item = self.coordinator.sax_data.get_item_by_name(SAX_SUNSPEC_CONTROL_MODE)
        if not mode_item or not isinstance(mode_item, ModbusItem):
            return False
        await self.coordinator.async_write_number_value(mode_item, 0)
        return True

    async def async_set_mode_manual(self) -> bool:
        """Set Mode register 40051 to 1 (Setpoint setting mode)."""
        mode_item = self.coordinator.sax_data.get_item_by_name(SAX_SUNSPEC_CONTROL_MODE)
        if not mode_item or not isinstance(mode_item, ModbusItem):
            return False
        await self.coordinator.async_write_number_value(mode_item, 1)
        return True
