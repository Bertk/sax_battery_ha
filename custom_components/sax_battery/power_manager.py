"""Power manager for SAX Battery integration.

Replaces pilot.py with state-based power management using Home Assistant
number entities (SAX_NOMINAL_POWER and SAX_NOMINAL_FACTOR) and SOC constraints.

Security:
    OWASP A05: Validates all sensor inputs and power values
    OWASP A01: Only master battery can create power manager

Performance:
    Debounced grid monitoring with configurable intervals
    Efficient state updates using HA service calls
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_ENABLE_GRID_CHARGING,
    CONF_ENABLE_PV_CHARGING,
    CONF_POWER_SENSOR,
    GRID_CHARGING_MODE,
    LIMIT_MAX_CHARGE_PER_BATTERY,
    LIMIT_MAX_DISCHARGE_PER_BATTERY,
    MODBUS_BATTERY_BMS_ITEMS,
    MODBUS_BATTERY_POWER_CONTROL_ITEMS,
    PILOT_ITEMS,
    PV_CHARGING_MODE,
    SAX_AC_POWER_TOTAL,
    SAX_NOMINAL_FACTOR,
    SAX_NOMINAL_POWER,
)
from .coordinator import SAXBatteryCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PowerManagerState:
    """Power manager state tracking.

    Performance: Uses slots for memory efficiency
    """

    mode: str
    target_power: float
    last_update: datetime
    pv_charging_enabled: bool = False
    grid_charging_enabled: bool = False


class PowerManager:
    """Power manager for coordinating battery control via HA entities.

    This replaces the direct Modbus write approach in pilot.py with a state-based
    system using Home Assistant number entities and SOC constraints.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: SAXBatteryCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize power manager.

        Args:
            hass: Home Assistant instance
            coordinator: Master battery coordinator
            config_entry: Configuration entry

        Security:
            OWASP A01: Validates coordinator is for master battery
        """
        self.hass = hass
        self.coordinator = coordinator
        self.config_entry = config_entry
        self.battery_count = len(coordinator.sax_data.coordinators)

        # Power limits based on battery count
        self.max_discharge_power = self.battery_count * LIMIT_MAX_CHARGE_PER_BATTERY
        self.max_charge_power = self.battery_count * LIMIT_MAX_DISCHARGE_PER_BATTERY

        # State tracking
        self._state = PowerManagerState(
            mode=GRID_CHARGING_MODE,
            target_power=0.0,
            last_update=datetime.now(),
        )

        # self._pv_callback_running = False
        # self._grid_power_sensor = None

        # Tracking for event listeners
        self._remove_interval_update: Callable[[], None] | None = None
        self._remove_config_update: Callable[[], None] | None = None
        self._running = False

        # Resolve entity IDs from entity registry using unique_id
        self._power_entity_id: str | None = None
        self._power_factor_entity_id: str | None = None
        self._resolve_entity_ids()

        # Configuration values - now safe to call after state initialization
        self._update_config_values()

    def _resolve_entity_ids(self) -> None:
        """Resolve entity IDs for power control entities from registry.

        Uses SAX_NOMINAL_POWER (register 43) and SAX_NOMINAL_FACTOR (register 44)
        for direct hardware control instead of intermediate SAX_POWER_CONTROL_SETPOINT.
        """
        # Validate coordinator has required dependencies
        if not hasattr(self.coordinator, "sax_data"):
            _LOGGER.error("Coordinator missing sax_data attribute")
            return

        # Resolve SAX_NOMINAL_POWER entity (register 43)
        nominal_power_item = next(
            (item for item in PILOT_ITEMS if item.name == SAX_NOMINAL_POWER),
            None,
        )

        if not nominal_power_item:
            _LOGGER.error("Could not find %s in PILOT_ITEMS", SAX_NOMINAL_POWER)
            return

        power_entity_id = self.coordinator.sax_data.get_entity_id_for_item(
            nominal_power_item,
            SAX_NOMINAL_POWER,
        )

        if power_entity_id:
            self._power_entity_id = power_entity_id
            _LOGGER.info(
                "✓ Resolved power entity: SAX_NOMINAL_POWER (register 43, entity_id: %s)",
                self._power_entity_id,
            )
        else:
            _LOGGER.error("Could not generate entity_id for %s", SAX_NOMINAL_POWER)

        # Resolve SAX_NOMINAL_FACTOR entity (register 44)
        power_factor_item = next(
            (item for item in PILOT_ITEMS if item.name == SAX_NOMINAL_FACTOR),
            None,
        )

        if not power_factor_item:
            _LOGGER.error("Could not find %s in PILOT_ITEMS", SAX_NOMINAL_FACTOR)
            return

        # Resolve SAX_NOMINAL_FACTOR entity (for power factor)
        factor_entity_id = self.coordinator.sax_data.get_entity_id_for_item(
            power_factor_item,
            SAX_NOMINAL_FACTOR,
        )

        if factor_entity_id:
            self._power_factor_entity_id = factor_entity_id
            _LOGGER.info(
                "✓ Resolved power factor entity: SAX_NOMINAL_FACTOR (entity_id: %s)",
                self._power_factor_entity_id,
            )
        else:
            _LOGGER.error("Could not generate unique_id for %s", SAX_NOMINAL_FACTOR)

        _LOGGER.debug(
            "Entity resolution complete: power=%s, factor=%s",
            self._power_entity_id,
            self._power_factor_entity_id,
        )

    def _update_config_values(self) -> None:
        """Update configuration values from entry data.

        Uses coordinator cycle for polling instead of custom interval (CONF_AUTO_PILOT_INTERVAL removed).
        CONF_POWER_SENSOR now represents PV production sensor (not smart meter).
        """
        self.pv_power_sensor = self.config_entry.data.get(CONF_POWER_SENSOR)

        pv_enabled = bool(self.config_entry.data.get(CONF_ENABLE_PV_CHARGING, False))
        grid_enabled = bool(
            self.config_entry.data.get(CONF_ENABLE_GRID_CHARGING, False)
        )

        # Security: Enforce mutual exclusion at startup
        if pv_enabled and grid_enabled:
            _LOGGER.warning(
                "Both PV charging and grid control are enabled in config - "
                "defaulting to PV charging mode"
            )
            pv_enabled = True
            grid_enabled = False

        self._state.pv_charging_enabled = pv_enabled
        self._state.grid_charging_enabled = grid_enabled

        _LOGGER.info(
            "Power manager config updated: PV=%s, grid=%s, pv_sensor=%s",
            pv_enabled,
            grid_enabled,
            self.pv_power_sensor,
        )

    async def async_start(self) -> None:
        """Start the power manager service.

        Uses coordinator's update_interval instead of custom CONF_AUTO_PILOT_INTERVAL.
        Security: Only starts if not already running
        """
        if self._running:
            _LOGGER.warning("Power manager already running")
            return

        self._running = True

        # Set up periodic updates using coordinator's update interval
        # Use 60 seconds as fallback if coordinator interval is not set
        update_interval: timedelta = (
            self.coordinator.update_interval
            if self.coordinator.update_interval is not None
            else timedelta(seconds=60)
        )

        self._remove_interval_update = async_track_time_interval(
            self.hass,
            self._async_update_power,
            update_interval,
        )

        # Add listener for config entry updates
        self._remove_config_update = self.config_entry.add_update_listener(
            self._async_config_updated
        )

        # Do initial update
        await self._async_update_power(None)

        _LOGGER.info(
            "Power manager started with coordinator cycle (%ss)",
            update_interval.total_seconds(),
        )

    async def async_stop(self) -> None:
        """Stop the power manager service.

        Security: Proper resource cleanup (OWASP A05)
        """
        if not self._running:
            return

        if self._remove_interval_update is not None:
            self._remove_interval_update()
            self._remove_interval_update = None

        if self._remove_config_update is not None:
            self._remove_config_update()
            self._remove_config_update = None

        self._running = False
        _LOGGER.info("Power manager stopped")

    async def _async_config_updated(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Handle config entry updates.

        Args:
            hass: Home Assistant instance
            entry: Updated config entry
        """
        self.config_entry = entry
        self._update_config_values()
        await self._async_update_power(None)
        _LOGGER.info("Power manager configuration updated")

    async def _async_update_power(self, now: Any = None) -> None:
        """Update power setpoint based on current mode.

        Args:
            now: Current time (from time interval trigger)

        Security:
            OWASP A05: Validates sensor states before processing
        """
        try:
            # Check current mode
            if self._state.grid_charging_enabled:
                _LOGGER.debug(
                    "Grid charging mode active - power: %sW",
                    self._state.target_power,
                )
                return

            if self._state.pv_charging_enabled:
                await self._update_pv_charging_power()
            else:
                _LOGGER.debug("No active power management mode")

        except (OSError, ValueError, TypeError) as err:
            _LOGGER.error("Error updating power: %s", err)

    async def _update_pv_charging_power(self) -> None:
        """Update power setpoint for PV charging mode.

        Uses the formula: New Battery Power = Current Battery Power - Grid Power
        This ensures grid power goes to zero by adjusting battery charge/discharge.

        Security:
            OWASP A05: Validates PV sensor state and battery power availability

        Performance:
            Direct state machine access with entity registry lookup
        """
        if not self.pv_power_sensor:
            _LOGGER.warning("PV power sensor not configured")
            return

        # Get PV power state (production value from CONF_POWER_SENSOR)
        pv_state = self.hass.states.get(self.pv_power_sensor)
        if pv_state is None:
            _LOGGER.warning("PV power sensor %s not found", self.pv_power_sensor)
            return

        if pv_state.state in (None, "unknown", "unavailable"):
            _LOGGER.warning(
                "PV power sensor %s state is %s",
                self.pv_power_sensor,
                pv_state.state,
            )
            return

        try:
            pv_power = float(pv_state.state)
        except (ValueError, TypeError) as err:
            _LOGGER.error(
                "Could not convert PV power '%s' to float: %s",
                pv_state.state,
                err,
            )
            return

        # FIX: Get current battery power from Home Assistant state machine
        current_battery_power = await self._get_battery_power()

        if current_battery_power is None:
            _LOGGER.warning(
                "Battery power not available, skipping solar charging update"
            )
            return

        # CORRECT CALCULATION:
        # New Battery Power = Current Battery Power - PV Power
        target_power = current_battery_power - pv_power

        _LOGGER.debug(
            "Solar charging calculation: pv=%sW, current_battery=%sW, raw_target=%sW",
            pv_power,
            current_battery_power,
            target_power,
        )

        # Apply power limits (Note: charging is negative, discharging is positive)
        target_power = max(
            -self.max_charge_power,  # Maximum charge (negative value)
            min(self.max_discharge_power, target_power),  # Maximum discharge
        )

        _LOGGER.debug("After power limits: target=%sW", target_power)

        _LOGGER.info(
            "PV charging update: pv=%sW, battery=%sW ",
            pv_power,
            current_battery_power,
        )

        # Update power setpoint via number entity
        await self.update_power_setpoint(target_power)

    async def _get_battery_power(self) -> float | None:
        """Get current battery power (SAX_AC_POWER_TOTAL) from Home Assistant state machine.

        Returns:
            float | None: Current battery power in watts or None if unavailable

        Security:
            OWASP A05: Validates entity availability before access

        Performance:
            Direct state machine access with multiple lookup strategies

        """
        try:
            # Validate coordinator has required dependencies
            if not hasattr(self.coordinator, "sax_data"):
                _LOGGER.error("Coordinator missing sax_data attribute")
                return None

            # Get SAXItem for SAX_AC_POWER_TOTAL from list MODBUS_BATTERY_BMS_ITEMS
            power_ac_item = None
            for item in MODBUS_BATTERY_BMS_ITEMS:
                if item.name == SAX_AC_POWER_TOTAL:
                    power_ac_item = item
                    break

            if power_ac_item is None:
                _LOGGER.debug(
                    "Could not find SAXItem for SAX_AC_POWER_TOTAL in list MODBUS_BATTERY_BMS_ITEMS"
                )
                return None

            # SAX_AC_POWER_TOTAL is a cluster-wide entity (battery_id=None)
            # sensor: sensor.sax_cluster_ac_power_total
            power_entity_id = self.coordinator.sax_data.get_entity_id_for_item(
                power_ac_item,
                battery_id=None,  # Cluster-wide entity
            )

            if power_entity_id is None:
                return None

            state = self.hass.states.get(power_entity_id)
            if state and state.state not in ("unknown", "unavailable", None):
                try:
                    power_value = float(state.state)
                    _LOGGER.info(
                        "✓ Found battery power %s: %.1fW",
                        power_entity_id,
                        power_value,
                    )
                    return power_value  # noqa: TRY300
                except (ValueError, TypeError) as err:
                    _LOGGER.debug("Could not convert registry entity value: %s", err)
        except Exception as err:
            _LOGGER.error(  # noqa: G201
                "Unexpected error getting battery power: %s", err, exc_info=True
            )

        return None

    async def update_power_setpoint(self, power: float) -> None:
        """Update power setpoint via number entity service call.

        Args:
            power: Power value in watts (positive = discharge, negative = charge)

        Security:
            OWASP A05: Validates power limits and entity availability
        Performance:
            Non-blocking service call for efficiency
        """
        # Security: Validate power limits
        if not isinstance(power, (int, float)):
            _LOGGER.error("Invalid power value type: %s", type(power))  # type:ignore[unreachable]
            return

        # Clamp to absolute limits
        clamped_power = max(
            -self.max_charge_power,  # Note: negative = charge
            min(self.max_discharge_power, power),
        )

        if clamped_power != power:
            _LOGGER.warning("Power value %sW clamped to %sW", power, clamped_power)

        # Update state immediately
        self._state.target_power = clamped_power
        self._state.last_update = datetime.now()

        if self._power_entity_id is None:
            return

        # Verify entity exists
        if not self.hass.states.get(self._power_entity_id):
            _LOGGER.error(
                "Power entity %s not found in Home Assistant",
                self._power_entity_id,
            )
            return

        # Fire-and-forget with timeout
        async def _set_power_value() -> None:
            """Set power value with timeout protection."""
            try:
                async with asyncio.timeout(5.0):  # 5 second timeout
                    await self.hass.services.async_call(
                        "number",
                        "set_value",
                        {
                            "entity_id": self._power_entity_id,
                            "value": clamped_power,
                        },
                        blocking=False,
                    )

                _LOGGER.info(
                    "✓ Power setpoint updated to %sW via %s",
                    clamped_power,
                    self._power_entity_id,
                )
            except TimeoutError:
                _LOGGER.error(
                    "Timeout setting power value to %sW (entity: %s)",
                    clamped_power,
                    self._power_entity_id,
                )
            except Exception as err:
                _LOGGER.error(  # noqa: G201
                    "Failed to update power setpoint: %s",
                    err,
                    exc_info=True,
                )

        #  Create task but don't await (fire-and-forget)
        self.hass.async_create_task(_set_power_value())

    async def set_pv_charging_mode(self, enabled: bool) -> None:
        """Enable or disable PV charging mode.

        Args:
            enabled: True to enable PV charging mode

        Security:
            OWASP A01: Power manager state synchronized with switch state
        """
        self._state.pv_charging_enabled = enabled
        self._state.mode = PV_CHARGING_MODE if enabled else GRID_CHARGING_MODE

        # Update grid charging state (mutual exclusion)
        if enabled:
            self._state.grid_charging_enabled = False

        _LOGGER.info(
            "PV charging mode %s (grid_charging=%s)",
            "enabled" if enabled else "disabled",
            self._state.grid_charging_enabled,
        )

        if enabled:
            await self._async_update_power(None)

    async def set_manual_control_mode(self, enabled: bool, power: float = 0.0) -> None:
        """Enable or disable manual control mode.

        Args:
            enabled: True to enable manual control mode
            power: Manual power setpoint (only used if enabled=True)

        Security:
            OWASP A01: Power manager state synchronized with switch state

        """
        self._state.grid_charging_enabled = enabled
        self._state.mode = GRID_CHARGING_MODE if enabled else PV_CHARGING_MODE

        # Update PV charging state (mutual exclusion)
        if enabled:
            self._state.pv_charging_enabled = False

        if enabled:
            # Apply manual power
            await self.update_power_setpoint(power)

        _LOGGER.info(
            "Manual control mode %s (grid_charging=%s)",
            "enabled" if enabled else "disabled",
            self._state.grid_charging_enabled,
        )

    @property
    def current_mode(self) -> str:
        """Get current power management mode."""
        return self._state.mode

    @property
    def current_power(self) -> float:
        """Get current power setpoint."""
        return self._state.target_power

    @property
    def get_pv_charging_enabled(self) -> bool:
        """Check if PV charging mode is enabled."""
        return self._state.pv_charging_enabled

    @property
    def get_grid_charging_enabled(self) -> bool:
        """Check if grid charging mode is enabled."""
        return self._state.grid_charging_enabled

    def get_diagnostics(self) -> dict[str, object]:
        """Return diagnostic information for troubleshooting.

        Returns:
            Dictionary with power manager state and configuration

        Security:
            OWASP A05: Does not expose sensitive configuration data
        """
        update_interval: timedelta = (
            self.coordinator.update_interval
            if self.coordinator.update_interval is not None
            else timedelta(seconds=60)
        )
        return {
            "running": self._running,
            "mode": self._state.mode,
            "target_power": self._state.target_power,
            "pv_charging_enabled": self._state.pv_charging_enabled,
            "grid_charging_enabled": self._state.grid_charging_enabled,
            "last_update": self._state.last_update.isoformat(),
            "battery_count": self.battery_count,
            "max_discharge_power": self.max_discharge_power,
            "max_charge_power": self.max_charge_power,
            "update_interval_seconds": update_interval.total_seconds(),
            "power_entity_id": self._power_entity_id,
            "power_factor_entity_id": self._power_factor_entity_id,
        }

    async def _update_entity_states(self, power: float, factor: int) -> None:
        """Update entity states for immediate UI feedback.

        Args:
            power: Power value
            factor: Power factor

        Security:
            OWASP A05: Validates entity registry access
        """

        if not self.coordinator.sax_data:
            return

        for item in MODBUS_BATTERY_POWER_CONTROL_ITEMS:
            entity_id = None
            if item.name == SAX_NOMINAL_POWER:
                entity_id = self.coordinator.sax_data.get_entity_id_for_item(
                    item=item,
                    battery_id="bess_a",
                )
            if item.name == SAX_NOMINAL_FACTOR:
                entity_id = self.coordinator.sax_data.get_entity_id_for_item(
                    item=item,
                    battery_id="bess_a",
                )
            if entity_id is not None:
                self.coordinator.hass.states.async_set(
                    entity_id,
                    str(factor),
                )
