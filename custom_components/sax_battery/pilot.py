"""Integration for SAX Battery pilot functionality."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

if TYPE_CHECKING:
    from .data_manager import SAXBatteryDataManager

from .const import SAX_COMBINED_SOC, SAX_SOC

_LOGGER = logging.getLogger(__name__)


class SAXBatteryPilot:
    """SAX Battery pilot for power management."""

    def __init__(
        self, hass: HomeAssistant, data_manager: SAXBatteryDataManager
    ) -> None:
        """Initialize the pilot."""
        self.hass = hass
        self.data_manager = data_manager
        self.solar_charging_enabled = True
        self.calculated_power: float | None = None
        self._requested_manual_power: float | None = None

        # Entity IDs for power calculations
        self.total_power_entity_id: str | None = None
        self.priority_power_entity_id: str | None = None
        self.battery_power_entity_id: str | None = None

    async def _get_master_battery_soc(self) -> float:
        """Get SOC from master battery or combined data."""
        # First try to get from combined data
        if combined_soc := self.data_manager.combined_data.get(SAX_COMBINED_SOC):
            return float(combined_soc)

        # Fallback to first available battery SOC
        for battery in self.data_manager.batteries.values():
            if soc_value := battery.data.get(SAX_SOC):
                try:
                    return float(soc_value)
                except (ValueError, TypeError) as err:
                    _LOGGER.debug(
                        "Could not convert SOC '%s' to number: %s", soc_value, err
                    )

        _LOGGER.debug("No SOC data available")
        return 0.0

    async def _get_entity_float_value(self, entity_id: str | None) -> float:
        """Get float value from Home Assistant entity."""
        if not entity_id:
            return 0.0

        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.debug("Entity %s not found", entity_id)
            return 0.0

        if state.state in ("unknown", "unavailable"):
            _LOGGER.debug("Entity %s state is %s", entity_id, state.state)
            return 0.0

        try:
            return float(state.state)
        except (ValueError, TypeError) as err:
            _LOGGER.debug(
                "Could not convert entity %s value '%s' to number: %s",
                entity_id,
                state.state,
                err,
            )
            return 0.0

    async def _calculate_power(self) -> float:
        """Calculate the power setpoint based on current conditions."""
        # Get power values from Home Assistant entities
        total_power = await self._get_entity_float_value(self.total_power_entity_id)
        priority_power = await self._get_entity_float_value(
            self.priority_power_entity_id
        )
        battery_power = await self._get_entity_float_value(self.battery_power_entity_id)

        # Get SOC from master battery or combined data
        master_soc = await self._get_master_battery_soc()

        _LOGGER.debug(
            "Starting calculation with total_power=%s, priority_power=%s, battery_power=%s SOC=%s%%",
            total_power,
            priority_power,
            battery_power,
            master_soc,
        )

        # Calculate net power based on priority logic
        if priority_power > 50:
            _LOGGER.debug(
                "Condition met: priority_power > 50 (%s > 50)", priority_power
            )
            net_power = 0.0
        else:
            _LOGGER.debug(
                "Condition met: priority_power <= 50 (%s <= 50)", priority_power
            )
            net_power = total_power - battery_power

        _LOGGER.debug("Final net_power value: %s", net_power)
        return net_power

    async def set_manual_power(self, power_value: float) -> None:
        """Set manual power override."""
        await self.send_power_command(power_value, 1.0)
        self.calculated_power = power_value
        _LOGGER.debug("Manual power set to %sW", power_value)

    async def send_power_command(self, power: float, power_factor: float) -> None:
        """Send power command to battery via Modbus."""
        self._requested_manual_power = power
        # Implementation for sending Modbus commands
        _LOGGER.debug("Sending power command: %sW with PF: %s", power, power_factor)

    async def set_solar_charging(self, enabled: bool) -> None:
        """Enable or disable solar charging."""
        self.solar_charging_enabled = enabled
        _LOGGER.debug("Solar charging %s", "enabled" if enabled else "disabled")

    @property
    def requested_manual_power(self) -> float | None:
        """Get the last manually requested power value."""
        return self._requested_manual_power


class SAXBatteryManualPowerNumber(Entity):
    """Number entity for manual power control."""

    def __init__(self, pilot: SAXBatteryPilot) -> None:
        """Initialize the number entity."""
        self._pilot = pilot
        self._attr_unique_id = (
            f"sax_battery_manual_power_{pilot.data_manager.device_id}"
        )
        self._attr_name = "Manual Power"
        self._attr_native_min_value = -10000
        self._attr_native_max_value = 10000
        self._attr_native_step = 100
        self._attr_native_unit_of_measurement = "W"

        self._attr_device_info = {
            "identifiers": {("sax_battery", pilot.data_manager.device_id)},
            "name": "SAX Battery System",
            "manufacturer": "SAX",
            "model": "SAX Battery",
            "sw_version": "1.0",
        }

    @property
    def native_value(self) -> float | None:
        """Return the current manual power value."""
        return self._pilot.calculated_power

    async def async_set_native_value(self, value: float) -> None:
        """Handle manual override of calculated power."""
        await self._pilot.send_power_command(value, 1.0)
        self._pilot.calculated_power = value


class SAXBatterySolarChargingSwitch(Entity):
    """Switch to enable/disable solar charging."""

    def __init__(self, pilot: SAXBatteryPilot) -> None:
        """Initialize the switch."""
        self._pilot = pilot
        self._attr_unique_id = (
            f"sax_battery_solar_charging_{pilot.data_manager.device_id}"
        )
        self._attr_name = "Solar Charging"

        self._attr_device_info = {
            "identifiers": {("sax_battery", pilot.data_manager.device_id)},
            "name": "SAX Battery System",
            "manufacturer": "SAX",
            "model": "SAX Battery",
            "sw_version": "1.0",
        }

    @property
    def is_on(self) -> bool:
        """Return true if solar charging is enabled."""
        return self._pilot.solar_charging_enabled

    @property
    def icon(self) -> str:  # type: ignore[override]
        """Return the icon to use for the switch."""
        return "mdi:solar-power" if self.is_on else "mdi:solar-power-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on solar charging."""
        await self._pilot.set_solar_charging(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off solar charging."""
        await self._pilot.set_solar_charging(False)
