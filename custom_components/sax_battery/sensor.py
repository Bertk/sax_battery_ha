"""SAX Battery sensor platform."""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.sensor import RestoreSensor, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ATTRIBUTION,
    ATTRIBUTION,
    BATTERY_IDS,
    BMS_UNAVAILABILITY_RATE,
    CONF_BATTERY_IS_MASTER,
    CONF_BATTERY_PHASE,
    COORDINATOR_CIRCUIT_BREAKER,
    COORDINATOR_CYCLE_TIME,
    COORDINATOR_ERROR_RATE,
    DIAGNOSTIC_ITEMS,
    DOMAIN,
    SAX_COMBINED_SOC,
    SAX_CUMULATIVE_ENERGY_CONSUMED,
    SAX_CUMULATIVE_ENERGY_PRODUCED,
    SAX_SOC,
)
from .coordinator import (
    CIRCUIT_BREAKER_COOLDOWN_SECONDS,
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    SAXBatteryCoordinator,
)
from .energy_integration import EnergyIntegrator
from .entity_keys import SAX_POWER
from .entity_utils import filter_items_by_type, filter_sax_items_by_type
from .enums import DeviceConstants, TypeConstants
from .items import ModbusItem, SAXItem

_LOGGER = logging.getLogger(__name__)

# Coordinator-based sensors don't need update serialization
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SAX Battery sensor platform with multi-battery support."""
    integration_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators = integration_data["coordinators"]
    sax_data = integration_data["sax_data"]

    entities: list[SensorEntity] = []

    # Create sensors for each battery using new constants
    for battery_id, coordinator in coordinators.items():
        # Validate battery_id is in allowed list
        if battery_id not in BATTERY_IDS:
            _LOGGER.warning("Invalid battery ID %s, skipping", battery_id)
            continue

        # Get battery-specific configuration
        battery_config = coordinator.battery_config
        is_master = battery_config.get(CONF_BATTERY_IS_MASTER, False)
        phase = battery_config.get(CONF_BATTERY_PHASE, "L1")

        _LOGGER.debug(
            "Setting up sensors for %s battery %s (%s)",
            "master" if is_master else "slave",
            battery_id,
            phase,
        )

        # Filter sensor items for this battery
        sensor_items = filter_items_by_type(
            sax_data.get_modbus_items_for_battery(battery_id),
            TypeConstants.SENSOR,
            config_entry,
            battery_id,
        )

        for modbus_item in sensor_items:
            if isinstance(modbus_item, ModbusItem):
                entities.append(  # noqa: PERF401
                    SAXBatteryModbusSensor(
                        coordinator=coordinator,
                        battery_id=battery_id,
                        modbus_item=modbus_item,
                    )
                )

        # 2. Create diagnostic sensors (coordinator statistics)
        # Only create for master battery to avoid duplicates
        if is_master:
            entities.extend(
                SAXBatteryCoordinatorCycleSensor(
                    coordinator=coordinator,
                    sax_item=diag_item,
                )
                for diag_item in DIAGNOSTIC_ITEMS
                if isinstance(diag_item, SAXItem)
            )

            _LOGGER.debug(
                "Added %d diagnostic sensors for master battery %s",
                len(DIAGNOSTIC_ITEMS),
                battery_id,
            )

        _LOGGER.info(
            "Added %d modbus sensor entities for %s", len(sensor_items), battery_id
        )

    # Create system-wide calculated sensors only once (using master battery coordinator)
    # Find master coordinator - check both the coordinator's battery_config AND sax_data
    master_coordinator = None
    for battery_id, coordinator in coordinators.items():
        # Check coordinator's battery_config first
        is_master = coordinator.battery_config.get(CONF_BATTERY_IS_MASTER, False)

        # If not found in coordinator, check sax_data as fallback
        if not is_master and battery_id in sax_data.batteries:
            battery_model = sax_data.batteries[battery_id]
            is_master = battery_model.is_master

        if is_master:
            master_coordinator = coordinator
            _LOGGER.debug(
                "Found master battery coordinator: %s (is_master=%s)",
                battery_id,
                is_master,
            )
            break

    if master_coordinator:
        # Get calculated sensor items
        sax_items = filter_sax_items_by_type(
            sax_data.get_sax_items_for_battery(sax_data.master_battery_id or "bess_a"),
            TypeConstants.SENSOR,
        )

        # Create calculated sensors
        for sax_item in sax_items:
            sax_item.set_coordinators(coordinators)
            entities.append(
                SAXBatteryCalculatedSensor(
                    master_coordinator,
                    sax_item,
                    coordinators,
                )
            )

        _LOGGER.debug(
            "Created %d calculated sensors using master coordinator", len(sax_items)
        )
    else:
        _LOGGER.warning(
            "No master battery found for cumulative energy calculation. "
            "Available batteries: %s, battery configs: %s",
            list(coordinators.keys()),
            {
                bid: coord.battery_config.get(CONF_BATTERY_IS_MASTER, "not set")
                for bid, coord in coordinators.items()
            },
        )

    if entities:
        async_add_entities(entities)
        _LOGGER.info(
            "Set up %d sensor entities across %d batteries",
            len(entities),
            len(coordinators),
        )


class SAXBatteryModbusSensor(CoordinatorEntity[SAXBatteryCoordinator], SensorEntity):
    """Implementation of a SAX Battery modbus sensor entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        battery_id: str,
        modbus_item: ModbusItem,
    ) -> None:
        """Initialize the modbus sensor."""
        super().__init__(coordinator)
        self._modbus_item = modbus_item
        self._battery_id = battery_id

        # Generate unique ID using get_unique_id_for_item
        self._attr_unique_id = coordinator.sax_data.get_unique_id_for_item(
            item=modbus_item,
            battery_id=battery_id,  # For per-battery entities
        )

        # Set entity description from modbus item if available
        if self._modbus_item.entitydescription is not None:
            self.entity_description = self._modbus_item.entitydescription  # type: ignore[assignment]

        # Set entity registry enabled state from ModbusItem
        self._attr_entity_registry_enabled_default = getattr(
            self._modbus_item, "enabled_by_default", True
        )

        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "name")
            and isinstance(self.entity_description.name, str)
        ):
            # Remove "Sax " prefix from entity description name
            self.entity_description.key.removeprefix("Smartmeter ")  # beautify the key
            entity_name = str(self.entity_description.name)
            entity_name = entity_name.removeprefix("Sax ")
            self._attr_name = entity_name

        # Set device info
        self._attr_device_info: DeviceInfo = coordinator.sax_data.get_device_info(
            battery_id, self._modbus_item.device
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._modbus_item.name)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        return {
            "battery_id": self._battery_id,
            "modbus_address": getattr(self._modbus_item, "address", None),
            "last_update": getattr(self.coordinator, "last_update_success_time", None),
            "raw_value": self.coordinator.data.get(self._modbus_item.name)
            if self.coordinator.data
            else None,
        }


class SAXBatteryCalculatedSensor(
    CoordinatorEntity[SAXBatteryCoordinator], RestoreSensor
):
    """SAX Battery calculated sensor entity with system-wide aggregation."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({ATTR_ATTRIBUTION})

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        sax_item: SAXItem,
        coordinators: dict[str, SAXBatteryCoordinator],
    ) -> None:
        """Initialize the calculated sensor entity.

        Args:
            coordinators: Dictionary of battery_id -> coordinator for aggregation
            sax_item: SAXItem containing entity configuration
            coordinator: Coordinator for the master battery

        Security:
            OWASP A05: Validates coordinators and item configuration
        """
        super().__init__(coordinator)
        self._sax_item = sax_item
        self._coordinators = coordinators

        # Set coordinators on the SAX item for calculations
        self._sax_item.set_coordinators(coordinators)

        # Generate unique ID using class name pattern
        self._attr_unique_id = coordinator.sax_data.get_unique_id_for_item(
            item=sax_item,
            battery_id=None,  # For per-battery entities
        )

        # Set entity description from sax item if available
        if self._sax_item.entitydescription is not None:
            self.entity_description = self._sax_item.entitydescription  # type: ignore[assignment]

        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "name")
            and isinstance(self.entity_description.name, str)
        ):
            self._attr_name = self.entity_description.name.removeprefix("Sax ")

        # Per-battery energy integrators for trapezoidal integration
        # Positive power (discharging) -> energy produced
        # Negative power (charging) -> energy consumed (absolute value)
        self._produced_integrators: dict[str, EnergyIntegrator] = {
            battery_id: EnergyIntegrator() for battery_id in coordinators
        }
        self._consumed_integrators: dict[str, EnergyIntegrator] = {
            battery_id: EnergyIntegrator() for battery_id in coordinators
        }

        # Set system device info
        self._attr_device_info: DeviceInfo = coordinator.sax_data.get_device_info(
            "cluster", DeviceConstants.SYS
        )

    @property
    def native_value(self) -> float | None:
        """Return the calculated sensor value.

        Performance:
            O(n) iteration over coordinators - efficient for small battery counts

        Security:
            OWASP A05: Validates coordinator data availability
        """
        if self._sax_item.name == SAX_COMBINED_SOC:
            return self._calculate_combined_soc()
        if self._sax_item.name in (
            SAX_CUMULATIVE_ENERGY_PRODUCED,
            SAX_CUMULATIVE_ENERGY_CONSUMED,
        ):
            self._integrate_all_batteries()
            if self._sax_item.name == SAX_CUMULATIVE_ENERGY_PRODUCED:
                return self._get_total_produced()
            return self._get_total_consumed()

        _LOGGER.warning("Unknown calculation type for sensor: %s", self._sax_item.name)
        return None

    def _calculate_combined_soc(self) -> float | None:
        """Calculate combined SOC from all batteries."""
        total_soc = 0.0
        battery_count = 0

        for coordinator in self._coordinators.values():
            if not coordinator.data:
                continue

            soc_value = coordinator.data.get(SAX_SOC)
            if soc_value is not None:
                try:
                    total_soc += float(soc_value)
                    battery_count += 1
                except ValueError, TypeError:
                    _LOGGER.debug(
                        "Invalid SOC value for battery %s: %s",
                        coordinator.battery_id,
                        soc_value,
                    )

        if battery_count == 0:
            return None

        return round(total_soc / battery_count, 1)

    def _integrate_all_batteries(self) -> None:
        """Feed current power readings from all batteries into integrators.

        For each battery, reads SAX_POWER (signed watts):
        - Positive power = discharging → energy produced
        - Negative power = charging → energy consumed (absolute value)

        Uses trapezoidal integration for high-resolution energy tracking,
        matching the accuracy of HA's built-in Riemann sum integration.

        Performance:
            O(n) where n = number of batteries (typically 1-3)
        """
        now = time.monotonic()

        for battery_id, coordinator in self._coordinators.items():
            if not coordinator.data:
                continue

            power_value = coordinator.data.get(SAX_POWER)
            if power_value is None:
                continue

            try:
                power_w = float(power_value)
            except ValueError, TypeError:
                _LOGGER.debug(
                    "Invalid power value for battery %s: %s",
                    battery_id,
                    power_value,
                )
                continue

            # Positive power = discharging = energy produced
            produced_power = max(power_w, 0.0)
            self._produced_integrators[battery_id].add_sample(produced_power, now)

            # Negative power = charging = energy consumed (take abs)
            consumed_power = abs(min(power_w, 0.0))
            self._consumed_integrators[battery_id].add_sample(consumed_power, now)

    def _get_total_produced(self) -> float:
        """Return total energy produced across all batteries in Wh."""
        return round(
            sum(
                integrator.accumulated_wh
                for integrator in self._produced_integrators.values()
            ),
            2,
        )

    def _get_total_consumed(self) -> float:
        """Return total energy consumed across all batteries in Wh."""
        return round(
            sum(
                integrator.accumulated_wh
                for integrator in self._consumed_integrators.values()
            ),
            2,
        )

    async def async_added_to_hass(self) -> None:
        """Restore state when entity is added to hass.

        Security:
            OWASP A05: Validates restored state before use
        """
        await super().async_added_to_hass()

        # Restore previous state for TOTAL_INCREASING sensors
        if self._sax_item.name in (
            SAX_CUMULATIVE_ENERGY_PRODUCED,
            SAX_CUMULATIVE_ENERGY_CONSUMED,
        ):
            await self._restore_cumulative_state()

    async def _restore_cumulative_state(self) -> None:
        """Restore cumulative energy state from last known value.

        Distributes the restored value evenly across all battery integrators
        so the total matches the previous state.

        Security:
            OWASP A05: Validates restored state
        """
        last_state = await self.async_get_last_state()

        if not last_state or last_state.state in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            _LOGGER.debug("No previous state to restore for %s", self._sax_item.name)
            return

        try:
            restored_value = float(last_state.state)

            if self._sax_item.name == SAX_CUMULATIVE_ENERGY_PRODUCED:
                integrators = self._produced_integrators
            elif self._sax_item.name == SAX_CUMULATIVE_ENERGY_CONSUMED:
                integrators = self._consumed_integrators
            else:
                return

            # Distribute restored value evenly across battery integrators
            if integrators:
                per_battery = restored_value / len(integrators)
                for integrator in integrators.values():
                    integrator.restore(per_battery)

            _LOGGER.info(
                "Restored %s: %s Wh across %d batteries",
                self._sax_item.name,
                restored_value,
                len(integrators),
            )

        except (ValueError, TypeError) as exc:
            _LOGGER.warning(
                "Failed to restore state for %s: %s",
                self._sax_item.name,
                exc,
            )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes.

        Returns:
            Dictionary of extra attributes for diagnostics
        """
        attrs: dict[str, Any] = {ATTR_ATTRIBUTION: ATTRIBUTION}

        # Add per-battery breakdown for energy sensors
        if self._sax_item.name == SAX_CUMULATIVE_ENERGY_PRODUCED:
            attrs["per_battery"] = {
                bid: integrator.accumulated_wh
                for bid, integrator in self._produced_integrators.items()
            }
        elif self._sax_item.name == SAX_CUMULATIVE_ENERGY_CONSUMED:
            attrs["per_battery"] = {
                bid: integrator.accumulated_wh
                for bid, integrator in self._consumed_integrators.items()
            }

        return attrs


class SAXBatteryCoordinatorCycleSensor(
    CoordinatorEntity[SAXBatteryCoordinator], SensorEntity
):
    """Sensor for coordinator cycle time monitoring."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        sax_item: SAXItem,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sax_item = sax_item
        self._coordinators = coordinator

        if sax_item.entitydescription is not None:
            self.entity_description = sax_item.entitydescription  # type: ignore[assignment]

        # Generate unique ID using get_unique_id_for_item
        self._attr_unique_id = coordinator.sax_data.get_unique_id_for_item(
            item=sax_item,
            battery_id=coordinator.battery_id,  # Per-battery diagnostic
        )

        # Set device info for proper grouping
        self._attr_device_info: DeviceInfo = coordinator.sax_data.get_device_info(
            coordinator.battery_id, sax_item.device
        )

    @property
    def native_value(self) -> float | str | None:
        """Return the sensor value."""
        stats = self.coordinator.cycle_time_statistics

        # Proper key matching
        if self.entity_description.key == COORDINATOR_CYCLE_TIME:
            last_cycle = stats.get("last")
            return float(last_cycle) if last_cycle is not None else None

        if self.entity_description.key == COORDINATOR_ERROR_RATE:
            errors_per_hour = stats.get("errors_per_hour", 0.0)
            return float(errors_per_hour) if errors_per_hour is not None else 0.0

        if self.entity_description.key == COORDINATOR_CIRCUIT_BREAKER:
            circuit_breaker_open = stats.get("circuit_breaker_open", 0.0)
            return "OPEN" if circuit_breaker_open else "CLOSED"

        if self.entity_description.key == BMS_UNAVAILABILITY_RATE:
            unavailability_per_hour = stats.get("bms_unavailability_per_hour", 0.0)
            return (
                float(unavailability_per_hour)
                if unavailability_per_hour is not None
                else 0.0
            )

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        stats = self.coordinator.cycle_time_statistics

        if self.entity_description.key == COORDINATOR_CYCLE_TIME:
            return {
                "average": round(stats.get("average", 0.0), 3),
                "min": round(stats.get("min", 0.0), 3),
                "max": round(stats.get("max", 0.0), 3),
                "stddev": round(stats.get("stddev", 0.0), 3),
                "total_updates": self.coordinator._total_updates,  # noqa: SLF001
                "failed_updates": self.coordinator._failed_updates,  # noqa: SLF001
                "consecutive_failures": self.coordinator._circuit_breaker.consecutive_failures,  # noqa: SLF001
            }

        if self.entity_description.key == COORDINATOR_ERROR_RATE:
            # Reuse cached stats from cycle_time_statistics (Issue #43)
            # Avoids redundant error_history iteration
            return {
                "modbus_errors": stats.get("modbus_errors", 0),
                "network_errors": stats.get("network_errors", 0),
                "timeout_errors": stats.get("timeout_errors", 0),
                "total_errors_last_hour": int(stats.get("errors_per_hour", 0)),
                "failed_registers": stats.get("failed_registers", {}),
                "last_error_time": stats.get("last_error_time"),
            }

        if self.entity_description.key == COORDINATOR_CIRCUIT_BREAKER:
            return {
                "consecutive_failures": self.coordinator._circuit_breaker.consecutive_failures,  # noqa: SLF001
                "failure_threshold": CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                "cooldown_seconds": CIRCUIT_BREAKER_COOLDOWN_SECONDS,
            }

        if self.entity_description.key == BMS_UNAVAILABILITY_RATE:
            return {
                "total_unavailability_last_hour": int(
                    stats.get("bms_unavailability_per_hour", 0)
                ),
                "last_error_time": stats.get("last_error_time"),
            }

        return {}
