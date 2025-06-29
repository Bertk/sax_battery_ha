"""Data manager for SAX Battery integration."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from decimal import Decimal
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_ID,
    CONF_ENABLE_SOLAR_CHARGING,
    CONF_MANUAL_CONTROL,
    SAX_STATUS,
)
from .pilot import SAXBatteryPilot

_LOGGER = logging.getLogger(__name__)


@dataclass
class SmartMeterData:
    """Data class for smart meter information."""

    power: Decimal = Decimal(0)
    voltage: Decimal = Decimal(0)
    current: Decimal = Decimal(0)


@dataclass
class CombinedData:
    """Data class for accumulated values across batteries."""

    combined_power: Decimal = Decimal(0)
    combined_soc: Decimal = Decimal(0)
    total_energy_produced: Decimal | None = None
    total_energy_consumed: Decimal | None = None
    smartmeter: SmartMeterData = field(default_factory=SmartMeterData)


@dataclass
class BatteryData:
    """Data class representing individual battery data."""

    battery_id: str
    data_manager: SAXBatteryDataManager
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def device_id(self) -> str:
        """Get the device ID from the data manager."""
        return self.data_manager.device_id


class SAXBatteryDataManager:
    """Data manager for SAX Battery integration."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the data manager."""
        self.hass = hass
        self.entry = entry

        # Ensure device_id is a string, with fallback
        device_id = entry.data.get(CONF_DEVICE_ID)
        if not device_id or not isinstance(device_id, str):
            msg = "Device ID is required and must be a string"
            raise ConfigEntryError(msg)

        self.device_id: str = device_id
        self.batteries: dict[str, BatteryData] = {}
        self.combined_data: dict[str, float | None] = {}  # For compatibility
        self.modbus_clients: dict[str, Any] = {}
        self.modbus_registers: dict[str, dict[str, Any]] = {}

        # Keep structured data separate for internal use
        self._structured_combined_data: CombinedData = CombinedData()

        # Initialize pilot functionality
        self.pilot: SAXBatteryPilot = SAXBatteryPilot(hass, self)

    async def async_setup(self) -> None:
        """Set up the data manager and initialize pilot."""
        # Initialize pilot with configuration from config entry
        await self.pilot.async_setup(self.entry)

    async def async_update_data(self) -> None:
        """Update data from all batteries."""
        if not self.batteries:
            return

        # Update all batteries concurrently following async patterns
        update_tasks = [
            self._update_battery_data(battery_id, battery)
            for battery_id, battery in self.batteries.items()
        ]

        results = await asyncio.gather(*update_tasks, return_exceptions=True)

        # Log any exceptions that occurred during updates
        for battery_id, result in zip(self.batteries.keys(), results, strict=True):
            if isinstance(result, Exception):
                _LOGGER.debug("Failed to update battery %s: %s", battery_id, result)

        # Update combined data after all individual updates
        self._update_combined_data()

        # Update pilot calculations if enabled
        if hasattr(self.pilot, "is_enabled") and self.pilot.is_enabled:
            await self.pilot.async_update()

    async def _update_battery_data(self, battery_id: str, battery: BatteryData) -> None:
        """Update data for a single battery."""
        try:
            # Implement your actual Modbus reading logic here
            await self._read_battery_modbus_data(battery_id, battery)
        except Exception as err:
            _LOGGER.warning("Failed to update battery %s: %s", battery_id, err)
            raise

    async def _read_battery_modbus_data(
        self, battery_id: str, battery: BatteryData
    ) -> None:
        """Read Modbus data for a single battery."""
        # Placeholder for actual Modbus reading implementation
        # This should contain your existing Modbus reading logic

    def _update_combined_data(self) -> None:
        """Update combined data from all batteries."""
        if not self.batteries:
            return

        total_power = Decimal(0)
        total_soc = Decimal(0)
        valid_soc_count = 0
        total_energy_produced = Decimal(0)
        total_energy_consumed = Decimal(0)

        for battery in self.batteries.values():
            # Aggregate power (sum)
            if power_value := battery.data.get("power"):
                with contextlib.suppress(ValueError, TypeError):
                    total_power += Decimal(str(power_value))

            # Aggregate SOC (average)
            if soc_value := battery.data.get("soc"):
                with contextlib.suppress(ValueError, TypeError):
                    total_soc += Decimal(str(soc_value))
                    valid_soc_count += 1

            # Aggregate energy produced (sum)
            if energy_produced := battery.data.get("energy_produced"):
                with contextlib.suppress(ValueError, TypeError):
                    total_energy_produced += Decimal(str(energy_produced))

            # Aggregate energy consumed (sum)
            if energy_consumed := battery.data.get("energy_consumed"):
                with contextlib.suppress(ValueError, TypeError):
                    total_energy_consumed += Decimal(str(energy_consumed))

        # Update structured combined data
        self._structured_combined_data.combined_power = total_power
        self._structured_combined_data.combined_soc = (
            total_soc / valid_soc_count if valid_soc_count > 0 else Decimal(0)
        )
        self._structured_combined_data.total_energy_produced = (
            total_energy_produced if total_energy_produced > 0 else None
        )
        self._structured_combined_data.total_energy_consumed = (
            total_energy_consumed if total_energy_consumed > 0 else None
        )

        # Update compatibility dict for external access
        self.combined_data.update(
            {
                "combined_power": float(self._structured_combined_data.combined_power),
                "combined_soc": float(self._structured_combined_data.combined_soc),
                "total_energy_produced": (
                    float(self._structured_combined_data.total_energy_produced)
                    if self._structured_combined_data.total_energy_produced is not None
                    else None
                ),
                "total_energy_consumed": (
                    float(self._structured_combined_data.total_energy_consumed)
                    if self._structured_combined_data.total_energy_consumed is not None
                    else None
                ),
            }
        )

    def add_battery(self, battery_id: str) -> BatteryData:
        """Add a new battery to the data manager."""
        battery = BatteryData(
            battery_id=battery_id,
            data_manager=self,
        )
        self.batteries[battery_id] = battery
        return battery

    def remove_battery(self, battery_id: str) -> None:
        """Remove a battery from the data manager."""
        self.batteries.pop(battery_id, None)
        # Clean up any associated Modbus clients
        if modbus_client := self.modbus_clients.pop(battery_id, None):
            if hasattr(modbus_client, "close"):
                modbus_client.close()

    async def async_shutdown(self) -> None:
        """Shutdown the data manager and clean up resources."""
        # Shutdown pilot
        if hasattr(self.pilot, "async_shutdown"):
            await self.pilot.async_shutdown()

        # Close all Modbus clients
        for client in self.modbus_clients.values():
            if hasattr(client, "close"):
                with contextlib.suppress(Exception):
                    client.close()

        self.modbus_clients.clear()
        self.batteries.clear()

    async def set_battery_switch(self, battery_id: str, enabled: bool) -> None:
        """Set battery switch state via Modbus."""
        try:
            battery = self.batteries.get(battery_id)
            if not battery:
                _LOGGER.error("Battery %s not found", battery_id)
                return

            client = self.modbus_clients.get(battery_id)
            if not client:
                _LOGGER.error("No Modbus client found for battery %s", battery_id)
                return

            # Get the register configuration for battery switch
            register_config = self.modbus_registers.get(battery_id, {}).get(
                SAX_STATUS, {}
            )
            register_address = register_config.get("address", 1)
            state_value = register_config.get(
                "state_on" if enabled else "state_off", 1 if enabled else 0
            )

            # Write to Modbus register
            result = await self.hass.async_add_executor_job(
                lambda: client.write_register(register_address, state_value, slave=64)
            )

            if hasattr(result, "isError") and result.isError():
                _LOGGER.error(
                    "Error setting battery %s switch to %s: %s",
                    battery_id,
                    enabled,
                    result,
                )
            else:
                _LOGGER.debug(
                    "Successfully set battery %s switch to %s", battery_id, enabled
                )
                # Update local data
                battery.data[SAX_STATUS] = state_value

        except Exception as err:
            _LOGGER.error("Failed to set battery %s switch: %s", battery_id, err)

    async def set_solar_charging_enabled(self, enabled: bool) -> None:
        """Enable or disable solar charging system-wide."""
        try:
            # Update config entry data
            new_data = dict(self.entry.data)
            new_data[CONF_ENABLE_SOLAR_CHARGING] = enabled

            self.hass.config_entries.async_update_entry(self.entry, data=new_data)

            # If pilot exists, update it directly
            if hasattr(self, "pilot") and self.pilot:
                await self.pilot.set_solar_charging(enabled)

            _LOGGER.info("Solar charging %s", "enabled" if enabled else "disabled")

        except Exception as err:
            _LOGGER.error("Failed to set solar charging to %s: %s", enabled, err)

    async def set_manual_control_enabled(self, enabled: bool) -> None:
        """Enable or disable manual control mode."""
        try:
            # Update config entry data
            new_data = dict(self.entry.data)
            new_data[CONF_MANUAL_CONTROL] = enabled

            self.hass.config_entries.async_update_entry(self.entry, data=new_data)

            _LOGGER.info("Manual control %s", "enabled" if enabled else "disabled")

        except Exception as err:
            _LOGGER.error("Failed to set manual control to %s: %s", enabled, err)
