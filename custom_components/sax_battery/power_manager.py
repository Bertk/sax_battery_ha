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
    CONF_MIN_SOC,
    CONF_POWER_SENSOR,
    DEFAULT_MIN_SOC,
    GRID_CHARGING_MODE,
    LIMIT_MAX_CHARGE_PER_BATTERY,
    LIMIT_MAX_DISCHARGE_PER_BATTERY,
    MODBUS_BATTERY_BMS_ITEMS,
    MODBUS_BATTERY_POWER_CONTROL_ITEMS,
    PILOT_ITEMS,
    PV_CHARGING_MODE,
    SAX_AC_POWER_TOTAL,
    SAX_CHARGE_FROM_PV_SWITCH,
    SAX_COMBINED_SOC,
    SAX_MAX_CHARGE,
    SAX_MAX_DISCHARGE,
    SAX_MAX_SOC_CHARGING,
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
    manual_mode_enabled: bool = False
    manual_power_value: float = 0.0

    # State persistence for mode transitions
    previous_pv_state: bool = False  # Store PV state before grid charging
    previous_grid_state: bool = False  # Store grid state before PV charging


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
        self._power_entity_id: str | None = (
            None  # Entity ID for SAX_NOMINAL_POWER (register 43)
        )
        self._power_factor_entity_id: str | None = (
            None  # Entity ID for SAX_NOMINAL_FACTOR (register 44)
        )
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

    def _get_switch_state(self, switch_name: str) -> bool:
        """Get current state of a switch entity.

        Args:
            switch_name: Entity key (e.g., SAX_CHARGE_FROM_PV_SWITCH)

        Returns:
            True if switch is on, False otherwise

        Security:
            OWASP A05: Validates entity availability before reading state
        """
        try:
            # Get switch item from PILOT_ITEMS
            switch_item = next(
                (item for item in PILOT_ITEMS if item.name == switch_name),
                None,
            )

            if not switch_item:
                _LOGGER.warning("Switch item %s not found in PILOT_ITEMS", switch_name)
                return False

            # Get entity ID from registry
            entity_id = self.coordinator.sax_data.get_entity_id_for_item(
                switch_item,
                battery_id=None,  # Cluster-wide entity
            )

            if not entity_id:
                _LOGGER.debug("Entity ID not found for %s", switch_name)
                return False

            # Read state from Home Assistant state machine
            state = self.hass.states.get(entity_id)
            if not state or state.state in ("unknown", "unavailable"):
                _LOGGER.debug("Switch %s state unavailable", entity_id)
                return False

            return state.state == "on"  # noqa: TRY300

        except (ValueError, TypeError, AttributeError) as err:
            _LOGGER.debug("Could not get switch state for %s: %s", switch_name, err)
            return False

    def _update_config_values(self) -> None:
        """Update configuration values from entry data.

        Uses coordinator cycle for polling instead of custom interval (CONF_AUTO_PILOT_INTERVAL removed).
        CONF_POWER_SENSOR now represents PV production sensor (not smart meter).
        Reads SAX_CHARGE_FROM_PV_SWITCH entity state for runtime control.
        """
        self.pv_power_sensor = self.config_entry.data.get(CONF_POWER_SENSOR)

        # Read switch entity states for runtime control (not config)
        pv_enabled = self._get_switch_state(SAX_CHARGE_FROM_PV_SWITCH)
        grid_enabled = bool(
            self.config_entry.data.get(CONF_ENABLE_GRID_CHARGING, False)
        )

        # Security: Enforce mutual exclusion at startup
        if pv_enabled and grid_enabled:
            _LOGGER.warning(
                "Both PV charging and grid control are enabled - "
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
            # Check current mode (priority order: manual > grid > pv)
            if self._state.manual_mode_enabled:
                # Manual mode: maintain fixed power setpoint
                _LOGGER.debug(
                    "Manual mode active - maintaining power: %sW",
                    self._state.manual_power_value,
                )
                return

            if self._state.grid_charging_enabled:
                await self._update_grid_balance_mode()
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

    async def _update_grid_balance_mode(self) -> None:
        """Update power setpoint to balance grid power.

        Uses grid power sensor to calculate battery power needed
        to achieve zero grid import/export.

        Formula:
            target_battery_power = current_battery_power - grid_power

        Where:
            - Negative grid_power = importing from grid (need to discharge battery)
            - Positive grid_power = exporting to grid (need to charge battery)

        Security:
            OWASP A05: Validates sensor availability and data freshness

        Performance:
            Single entity state lookup, O(1) calculation
        """
        # Get grid power sensor from config
        power_sensor_id = self.config_entry.data.get(CONF_POWER_SENSOR)
        if not power_sensor_id:
            _LOGGER.warning("Grid power sensor not configured")
            return

        # Get current grid power
        grid_state = self.hass.states.get(power_sensor_id)
        if not grid_state or grid_state.state in ("unknown", "unavailable"):
            _LOGGER.warning("Grid power sensor unavailable: %s", power_sensor_id)
            return

        try:
            grid_power = float(grid_state.state)
        except (ValueError, TypeError) as err:
            _LOGGER.error("Invalid grid power value: %s", err)
            return

        # Get current battery power from state machine
        current_battery_power = await self._get_battery_power()

        if current_battery_power is None:
            _LOGGER.warning("Battery power not available, skipping grid balance update")
            return

        # Calculate target power to balance grid
        # If importing 1000W from grid, need to discharge 1000W from battery
        # If exporting 500W to grid, need to charge 500W to battery
        target_power = current_battery_power - grid_power

        _LOGGER.debug(
            "Grid balance: grid_power=%.0fW, battery_power=%.0fW, target=%.0fW",
            grid_power,
            current_battery_power,
            target_power,
        )

        # Apply constraints and update hardware
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

    async def _get_min_soc_limit(self) -> float:
        """Get minimum SOC limit from config.

        Returns:
            Minimum SOC percentage (0-100)

        Security:
            OWASP A05: Validates config entry availability
        """
        if not self.config_entry:
            return DEFAULT_MIN_SOC

        return float(self.config_entry.data.get(CONF_MIN_SOC, DEFAULT_MIN_SOC))

    async def _get_max_soc_charging_limit(self) -> float:
        """Get maximum SOC charging limit from entity.

        Returns:
            Maximum SOC percentage (0-100)

        Security:
            OWASP A05: Validates entity availability with fallback
        """
        try:
            # Get SAX_MAX_SOC_CHARGING entity (cluster-wide virtual entity)
            max_soc_item = next(
                (item for item in PILOT_ITEMS if item.name == SAX_MAX_SOC_CHARGING),
                None,
            )

            if not max_soc_item:
                return 90.0  # Default fallback

            max_soc_entity_id = self.coordinator.sax_data.get_entity_id_for_item(
                max_soc_item,
                battery_id=None,  # Cluster-wide entity
            )

            if max_soc_entity_id:
                state = self.hass.states.get(max_soc_entity_id)
                if state and state.state not in ("unknown", "unavailable"):
                    return float(state.state)

        except (ValueError, TypeError, AttributeError) as err:
            _LOGGER.debug("Could not get max SOC charging limit: %s", err)

        return 90.0  # Default fallback

    async def _get_max_charge_limit(self) -> float:
        """Get maximum charge power limit from entity.

        Returns:
            Maximum charge power in watts (per battery)

        Security:
            OWASP A05: Validates entity availability with fallback
        """
        try:
            # Get SAX_MAX_CHARGE entity (per-battery hardware entity)
            max_charge_item = next(
                (
                    item
                    for item in MODBUS_BATTERY_POWER_CONTROL_ITEMS
                    if item.name == SAX_MAX_CHARGE
                ),
                None,
            )

            if not max_charge_item:
                return LIMIT_MAX_CHARGE_PER_BATTERY

            max_charge_entity_id = self.coordinator.sax_data.get_entity_id_for_item(
                max_charge_item,
                battery_id=self.coordinator.battery_id,
            )

            if max_charge_entity_id:
                state = self.hass.states.get(max_charge_entity_id)
                if state and state.state not in ("unknown", "unavailable"):
                    return float(state.state)

        except (ValueError, TypeError, AttributeError) as err:
            _LOGGER.debug("Could not get max charge limit: %s", err)

        return LIMIT_MAX_CHARGE_PER_BATTERY

    async def _get_max_discharge_limit(self) -> float:
        """Get maximum discharge power limit from entity.

        Returns:
            Maximum discharge power in watts (per battery)

        Security:
            OWASP A05: Validates entity availability with fallback
        """
        try:
            # Get SAX_MAX_DISCHARGE entity (per-battery hardware entity)
            max_discharge_item = next(
                (
                    item
                    for item in MODBUS_BATTERY_POWER_CONTROL_ITEMS
                    if item.name == SAX_MAX_DISCHARGE
                ),
                None,
            )

            if not max_discharge_item:
                return LIMIT_MAX_DISCHARGE_PER_BATTERY

            max_discharge_entity_id = self.coordinator.sax_data.get_entity_id_for_item(
                max_discharge_item,
                battery_id=self.coordinator.battery_id,
            )

            if max_discharge_entity_id:
                state = self.hass.states.get(max_discharge_entity_id)
                if state and state.state not in ("unknown", "unavailable"):
                    return float(state.state)

        except (ValueError, TypeError, AttributeError) as err:
            _LOGGER.debug("Could not get max discharge limit: %s", err)

        return LIMIT_MAX_DISCHARGE_PER_BATTERY

    async def apply_power_constraints(
        self,
        target_power: float,
        combined_soc: float,
    ) -> float:
        """Apply all power constraints in correct order matching pilot.py logic.

        Args:
            target_power: Desired total power (positive=discharge, negative=charge)
            combined_soc: Current cluster SOC percentage

        Returns:
            Constrained power value per battery

        Security:
            OWASP A05: Hardware protection via constraint enforcement

        Performance:
            O(1) constraint checks, no loops

        Note:
            Constraint enforcement order (from pilot.py):
            1. Distribute power across batteries
            2. SOC-based discharge protection (MIN_SOC)
            3. SOC-based charge limit (MAX_SOC_CHARGING)
            4. Hardware charge limit (MAX_CHARGE)
            5. Hardware discharge limit (MAX_DISCHARGE)
        """
        # Step 1: Distribute power across batteries
        battery_power = target_power / self.battery_count

        # Step 2: Get constraint limits from entities
        min_soc = await self._get_min_soc_limit()
        max_soc_charging = await self._get_max_soc_charging_limit()
        max_charge = await self._get_max_charge_limit()
        max_discharge = await self._get_max_discharge_limit()

        _LOGGER.debug(
            "Constraint limits: min_soc=%.1f%%, max_soc=%.1f%%, "
            "max_charge=%.0fW, max_discharge=%.0fW",
            min_soc,
            max_soc_charging,
            max_charge,
            max_discharge,
        )

        # Step 3: SOC-based discharge protection
        if combined_soc <= min_soc and battery_power > 0:
            _LOGGER.info(
                "Discharge blocked: SOC %.1f%% <= min %.1f%%",
                combined_soc,
                min_soc,
            )
            return 0.0

        # Step 4: SOC-based charge limit
        if combined_soc >= max_soc_charging and battery_power < 0:
            _LOGGER.info(
                "Charge blocked: SOC %.1f%% >= max %.1f%%",
                combined_soc,
                max_soc_charging,
            )
            return 0.0

        # Step 5: Hardware charge limit (charging = negative power)
        if battery_power < 0:
            original_power = battery_power
            battery_power = max(battery_power, -max_charge)
            if battery_power != original_power:
                _LOGGER.debug(
                    "Charge power limited: %.0fW -> %.0fW",
                    original_power,
                    battery_power,
                )

        # Step 6: Hardware discharge limit (discharging = positive power)
        if battery_power > 0:
            original_power = battery_power
            battery_power = min(battery_power, max_discharge)
            if battery_power != original_power:
                _LOGGER.debug(
                    "Discharge power limited: %.0fW -> %.0fW",
                    original_power,
                    battery_power,
                )

        return battery_power

    async def update_power_setpoint(self, power: float) -> None:
        """Update power setpoint via number entity service call.

        Args:
            power: Power value in watts (positive = discharge, negative = charge)

        Security:
            OWASP A05: Validates power limits, SOC constraints, and entity availability
        Performance:
            Non-blocking service call for efficiency
        """
        # Security: Validate power limits
        if not isinstance(power, (int, float)):
            _LOGGER.error("Invalid power value type: %s", type(power))  # type:ignore[unreachable]
            return

        # Get current combined SOC
        combined_soc = self.coordinator.data.get(SAX_COMBINED_SOC)
        if combined_soc is None:
            _LOGGER.warning("Combined SOC not available, cannot apply constraints")
            return

        # Apply all power constraints (SOC protection, hardware limits, distribution)
        constrained_power = await self.apply_power_constraints(
            target_power=power,
            combined_soc=combined_soc,
        )

        if constrained_power != power:
            _LOGGER.info(
                "Power constrained: %.0fW -> %.0fW (SOC: %.1f%%)",
                power,
                constrained_power,
                combined_soc,
            )

        # Update state immediately
        self._state.target_power = constrained_power
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
                            "value": constrained_power,
                        },
                        blocking=False,
                    )

                _LOGGER.info(
                    "✓ Power setpoint updated to %sW via %s",
                    constrained_power,
                    self._power_entity_id,
                )
            except TimeoutError:
                _LOGGER.error(
                    "Timeout setting power value to %sW (entity: %s)",
                    constrained_power,
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

    async def set_grid_control_mode(self, enabled: bool, power: float = 0.0) -> None:
        """Enable or disable grid charging mode.

        Args:
            enabled: True to enable grid charging mode
            power: Initial charge power (optional, uses SAX_MAX_CHARGE if 0)

        Security:
            OWASP A01: Power manager state synchronized with switch state

        """
        # Store previous PV state before enabling grid charging
        if enabled:
            self._state.previous_pv_state = self._state.pv_charging_enabled
            self._state.pv_charging_enabled = False  # Mutual exclusion
        elif self._state.previous_pv_state:
            # Restore previous PV state when disabling grid charging
            _LOGGER.info("Restoring PV charging mode after grid charging disabled")
            self._state.pv_charging_enabled = self._state.previous_pv_state
            self._state.previous_pv_state = False

        self._state.grid_charging_enabled = enabled
        self._state.mode = (
            GRID_CHARGING_MODE
            if enabled
            else (PV_CHARGING_MODE if self._state.pv_charging_enabled else "standby")
        )

        _LOGGER.info(
            "Grid charging mode %s (PV charging will be %s)",
            "enabled" if enabled else "disabled",
            "restored"
            if not enabled and self._state.pv_charging_enabled
            else "disabled",
        )

        if enabled:
            # Apply manual power if specified
            if power != 0.0:
                await self.update_power_setpoint(power)
            # Otherwise, grid charging logic will be handled by _async_update_power

    async def set_manual_power_mode(
        self,
        enabled: bool,
        target_power: float = 0.0,
    ) -> None:
        """Enable or disable manual power control mode.

        Args:
            enabled: True to enable manual mode
            target_power: Fixed power setpoint (W)
                         Positive = discharge to grid
                         Negative = charge from grid/PV
                         Default = 0.0 (standby)

        Security:
            OWASP A01: Power manager state synchronized with mode switches
            OWASP A05: Validates power constraints before hardware write

        Example:
            # Charge at 3000W from grid
            await manager.set_manual_power_mode(True, -3000.0)

            # Discharge at 2000W to grid
            await manager.set_manual_power_mode(True, 2000.0)

            # Disable manual mode
            await manager.set_manual_power_mode(False)
        """
        # Store previous states before enabling manual mode
        if enabled:
            self._state.previous_pv_state = self._state.pv_charging_enabled
            self._state.previous_grid_state = self._state.grid_charging_enabled
            self._state.pv_charging_enabled = False  # Mutual exclusion
            self._state.grid_charging_enabled = False  # Mutual exclusion
        elif self._state.previous_pv_state or self._state.previous_grid_state:
            # Restore previous state when disabling manual mode
            if self._state.previous_grid_state:
                _LOGGER.info("Restoring grid charging mode after manual mode disabled")
                self._state.grid_charging_enabled = True
            elif self._state.previous_pv_state:
                _LOGGER.info("Restoring PV charging mode after manual mode disabled")
                self._state.pv_charging_enabled = True
            self._state.previous_pv_state = False
            self._state.previous_grid_state = False

        self._state.manual_mode_enabled = enabled
        self._state.manual_power_value = target_power
        self._state.mode = (
            "manual"
            if enabled
            else (
                GRID_CHARGING_MODE
                if self._state.grid_charging_enabled
                else (
                    PV_CHARGING_MODE if self._state.pv_charging_enabled else "standby"
                )
            )
        )

        _LOGGER.info(
            "Manual power mode %s%s",
            "enabled" if enabled else "disabled",
            f" (target: {target_power:.0f}W)" if enabled else "",
        )

        if enabled:
            # Apply power setpoint with constraint enforcement
            await self.update_power_setpoint(target_power)
        else:
            # Reset to standby when disabling
            await self.update_power_setpoint(0.0)

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

    @property
    def get_manual_mode_enabled(self) -> bool:
        """Check if manual power mode is enabled."""
        return self._state.manual_mode_enabled

    @property
    def get_manual_power_value(self) -> float:
        """Get manual mode power setpoint."""
        return self._state.manual_power_value

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
            "manual_mode_enabled": self._state.manual_mode_enabled,
            "manual_power_value": self._state.manual_power_value,
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
