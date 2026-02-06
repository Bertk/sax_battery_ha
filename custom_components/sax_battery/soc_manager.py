"""SOC constraint management for SAX Battery integration.

Security:
    OWASP A05: Implements resource protection to prevent battery damage

Performance:
    Efficient SOC checking with caching to minimize coordinator queries
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    MODBUS_BATTERY_POWER_LIMIT_ITEMS,
    SAX_COMBINED_SOC,
    SAX_MAX_DISCHARGE,
)

if TYPE_CHECKING:
    from .coordinator import SAXBatteryCoordinator

_LOGGER = logging.getLogger(__name__)


class SOCManager:
    """Manager for SOC-based battery protection constraints."""

    def __init__(
        self,
        coordinator: SAXBatteryCoordinator,
        min_soc: int,
        enabled: bool = True,
    ) -> None:
        """Initialize SOC manager."""
        self.coordinator = coordinator
        self.hass = coordinator.hass
        self.config_entry = coordinator.config_entry
        # used for min_soc enforcement - max_soc not implemented yet
        self._min_soc: int = max(0, min(100, min_soc))
        self._enabled = enabled

    @property
    def min_soc(self) -> int:
        """Get minimum SOC threshold."""
        return self._min_soc

    @min_soc.setter
    def min_soc(self, value: int) -> None:
        """Set minimum SOC threshold with validation."""
        old_value = self._min_soc
        self._min_soc = max(0, min(100, value))
        _LOGGER.debug("Min SOC updated to %s%%", self._min_soc)

        # If min_soc increased, check if we need to enforce new limit
        if self._min_soc > old_value:
            # Trigger asynchronous constraint check
            # This will be handled by the coordinator's next update cycle
            _LOGGER.debug(
                "Min SOC increased, enforcement check will occur on next update"
            )

    @property
    def enabled(self) -> bool:
        """Get constraint enabled state."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Set constraint enabled state."""
        self._enabled = bool(value)
        _LOGGER.debug("SOC constraints %s", "enabled" if self._enabled else "disabled")

    async def check_and_enforce_discharge_limit(self) -> bool:
        """Check and enforce discharge limit based on combined SOC.

        Returns:
            bool: True if enforcement was applied, False otherwise

        Security:
            OWASP A05: Validates coordinator state before hardware writes
            OWASP A01: Uses is_master property to ensure proper access control
        """
        # Add early logging for debugging
        _LOGGER.debug(
            "SOC enforcement check: enabled=%s, coordinator_data=%s, is_master=%s",
            self.enabled,
            bool(self.coordinator.data),
            self.coordinator.is_master
            if hasattr(self.coordinator, "is_master")
            else "N/A",
        )

        if not self.enabled:
            _LOGGER.debug("Cannot enforce discharge limit - SOC protection disabled")
            return False

        # Validate coordinator has required data
        if not self.coordinator.data:
            _LOGGER.warning("Coordinator data not available for SOC enforcement")
            return False

        # CRITICAL: Only master coordinator can enforce discharge limits
        if not self.coordinator.is_master:
            _LOGGER.debug(
                "SOC enforcement skipped - coordinator %s is not master",
                self.coordinator.battery_id,
            )
            return False

        # Get combined SOC from master coordinator's data
        combined_soc = self.coordinator.data.get(SAX_COMBINED_SOC)

        # Log SOC value for debugging
        _LOGGER.debug(
            "SOC enforcement check: combined_soc=%s, min_soc=%s",
            combined_soc,
            self.min_soc,
        )

        if combined_soc is None:
            _LOGGER.debug(
                "Combined SOC not yet available in master coordinator data: %s",
                self.coordinator.data.keys(),
            )
            return False

        # Check if below minimum
        if combined_soc >= self.min_soc:
            _LOGGER.debug(
                "SOC %.1f%% >= min %.1f%% - no enforcement needed",
                combined_soc,
                self.min_soc,
            )
            return False

        # Find SAX_MAX_DISCHARGE ModbusItem from MODBUS_BATTERY_POWER_LIMIT_ITEMS list
        max_discharge_item = next(
            (
                item
                for item in MODBUS_BATTERY_POWER_LIMIT_ITEMS
                if item.name == SAX_MAX_DISCHARGE
            ),
            None,
        )

        if not max_discharge_item:
            _LOGGER.error(
                "Could not find SAX_MAX_DISCHARGE in MODBUS_BATTERY_POWER_LIMIT_ITEMS"
            )
            return False

        # Generate unique_id for SAX_MAX_DISCHARGE entity
        unique_id = self.coordinator.sax_data.get_unique_id_for_item(
            max_discharge_item,
            battery_id=self.coordinator.battery_id,  # Master's battery_id
        )

        # Type guard: Validate unique_id before entity lookup
        if not unique_id:
            _LOGGER.error(
                "Could not generate unique_id for SAX_MAX_DISCHARGE on master %s (entry_id=%s)",
                self.coordinator.battery_id,
                self.coordinator.config_entry.entry_id
                if self.coordinator.config_entry
                else None,
            )
            return False

        ent_reg = er.async_get(self.hass)

        # Use "number" domain, not "input_number"
        entity_id = ent_reg.async_get_entity_id("number", DOMAIN, unique_id)

        if not entity_id:
            _LOGGER.error(
                "Could not find entity_id for SAX_MAX_DISCHARGE unique_id=%s (available entities: %s)",
                unique_id,
                [
                    e.unique_id
                    for e in ent_reg.entities.get_entries_for_config_entry_id(
                        self.coordinator.config_entry.entry_id
                    )
                    if e.domain == "number"
                ]
                if self.coordinator.config_entry
                else "N/A",
            )
            return False

        # Only write 0W if the current value is non-zero
        current_state = self.hass.states.get(entity_id)
        if current_state and current_state.state not in ("unknown", "unavailable"):
            try:
                current_value = float(current_state.state)
                if current_value == 0.0:
                    _LOGGER.debug(
                        "Discharge limit already enforced (0W) on master %s, skipping redundant write",
                        self.coordinator.battery_id,
                    )

                    return False  # No write needed, enforcement already active
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Could not parse current SAX_MAX_DISCHARGE value: %s",
                    current_state.state,
                )

        _LOGGER.warning(
            "Combined SOC %.1f%% below minimum %.1f%% - enforcing discharge limit via master %s",
            combined_soc,
            self.min_soc,
            self.coordinator.battery_id,
        )

        # Use number.set_value service (not input_number)
        try:
            _LOGGER.info(
                "Calling number.set_value service: entity_id=%s, value=0.0",
                entity_id,
            )

            await self.hass.services.async_call(
                "number",  # Correct domain for NumberEntity
                "set_value",
                {
                    "entity_id": entity_id,
                    "value": 0,
                },
                blocking=True,
            )

            _LOGGER.info(
                "Discharge blocked on master %s: SOC %.1f%% < min %.1f%% (entity: %s)",
                self.coordinator.battery_id,
                combined_soc,
                self.min_soc,
                entity_id,
            )

            return True  # noqa: TRY300

        except Exception as exc:
            _LOGGER.error(  # noqa: G201
                "Failed to enforce discharge limit on master %s via entity %s: %s",
                self.coordinator.battery_id,
                entity_id,
                exc,
                exc_info=True,  # Add full traceback for debugging
            )
            return False
