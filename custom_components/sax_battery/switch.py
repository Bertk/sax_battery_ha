"""Switch platform for SAX Battery integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENABLE_SOLAR_CHARGING,
    CONF_MANUAL_CONTROL,
    CONF_PILOT_FROM_HA,
    DOMAIN,
    SAX_STATUS,
)
from .data_manager import BatteryData, SAXBatteryDataManager

_LOGGER = logging.getLogger(__name__)


async def _noop_async(_: Any) -> None:
    """No-op async function for default callbacks."""


@dataclass(frozen=True)
class SAXBatterySwitchEntityDescription(SwitchEntityDescription):
    """Class describing SAX Battery switch entities."""

    turn_on_fn: Callable[[Any], Awaitable[None]] = _noop_async
    turn_off_fn: Callable[[Any], Awaitable[None]] = _noop_async
    is_on_fn: Callable[[Any], bool] = lambda x: False
    available_fn: Callable[[Any], bool] = lambda x: True


def _get_battery_status(battery: BatteryData) -> bool:
    """Get battery switch status."""
    if not hasattr(battery, "data") or not hasattr(battery, "data_manager"):
        return False

    status_value = battery.data.get(SAX_STATUS)
    if status_value is None:
        return False

    modbus_regs = battery.data_manager.modbus_registers.get(battery.battery_id, {})
    status_config = modbus_regs.get(SAX_STATUS, {})

    return bool(status_value == status_config.get("state_on", 1))


def _is_battery_available(battery: BatteryData) -> bool:
    """Check if battery status is available."""
    return hasattr(battery, "data") and SAX_STATUS in battery.data


async def _turn_battery_on(battery: BatteryData) -> None:
    """Turn battery on via Modbus."""
    if hasattr(battery, "data_manager"):
        await battery.data_manager.set_battery_switch(battery.battery_id, True)


async def _turn_battery_off(battery: BatteryData) -> None:
    """Turn battery off via Modbus."""
    if hasattr(battery, "data_manager"):
        await battery.data_manager.set_battery_switch(battery.battery_id, False)


def _get_solar_charging_status(data_manager: SAXBatteryDataManager) -> bool:
    """Get solar charging status from pilot or config."""
    # First check if pilot exists and has solar charging setting
    if hasattr(data_manager, "pilot") and data_manager.pilot:
        return bool(data_manager.pilot.solar_charging_enabled)

    # Fallback to config entry data
    if hasattr(data_manager, "entry"):
        return bool(data_manager.entry.data.get(CONF_ENABLE_SOLAR_CHARGING, True))

    return True


def _get_manual_control_status(data_manager: SAXBatteryDataManager) -> bool:
    """Get manual control status from config."""
    if hasattr(data_manager, "entry"):
        return bool(data_manager.entry.data.get(CONF_MANUAL_CONTROL, False))
    return False


async def _turn_solar_charging_on(data_manager: SAXBatteryDataManager) -> None:
    """Turn on solar charging."""
    if hasattr(data_manager, "pilot") and data_manager.pilot:
        await data_manager.pilot.set_solar_charging(True)
    else:
        await data_manager.set_solar_charging_enabled(True)


async def _turn_solar_charging_off(data_manager: SAXBatteryDataManager) -> None:
    """Turn off solar charging."""
    if hasattr(data_manager, "pilot") and data_manager.pilot:
        await data_manager.pilot.set_solar_charging(False)
    else:
        await data_manager.set_solar_charging_enabled(False)


async def _turn_manual_control_on(data_manager: SAXBatteryDataManager) -> None:
    """Turn on manual control."""
    await data_manager.set_manual_control_enabled(True)


async def _turn_manual_control_off(data_manager: SAXBatteryDataManager) -> None:
    """Turn off manual control."""
    await data_manager.set_manual_control_enabled(False)


BATTERY_SWITCH_TYPES: tuple[SAXBatterySwitchEntityDescription, ...] = (
    SAXBatterySwitchEntityDescription(
        key="battery_switch",
        name="Battery Switch",
        icon="mdi:battery",
        is_on_fn=_get_battery_status,
        available_fn=_is_battery_available,
        turn_on_fn=_turn_battery_on,
        turn_off_fn=_turn_battery_off,
    ),
)

PILOT_SWITCH_TYPES: tuple[SAXBatterySwitchEntityDescription, ...] = (
    SAXBatterySwitchEntityDescription(
        key="solar_charging",
        name="Solar Charging",
        icon="mdi:solar-power",
        is_on_fn=_get_solar_charging_status,
        turn_on_fn=_turn_solar_charging_on,
        turn_off_fn=_turn_solar_charging_off,
    ),
    SAXBatterySwitchEntityDescription(
        key="manual_control",
        name="Manual Control",
        icon="mdi:hand",
        is_on_fn=_get_manual_control_status,
        turn_on_fn=_turn_manual_control_on,
        turn_off_fn=_turn_manual_control_off,
    ),
)


class SAXBatterySwitch(SwitchEntity):
    """Base switch for SAX Battery."""

    _sax_entity_description: SAXBatterySwitchEntityDescription

    def __init__(
        self,
        device_info: DeviceInfo,
        description: SAXBatterySwitchEntityDescription,
        unique_id_prefix: str,
        device: BatteryData | SAXBatteryDataManager,
    ) -> None:
        """Initialize the switch."""
        self._sax_entity_description = description
        self.entity_description = description
        self._device = device

        self._attr_unique_id = f"{unique_id_prefix}_{description.key}"
        self._attr_name = f"SAX Battery {description.name}"
        self._attr_device_info = device_info

        # Set initial state using _attr pattern
        if description.is_on_fn is not None:
            self._attr_is_on = description.is_on_fn(device)

    async def async_update(self) -> None:
        """Update the switch state."""
        if self._sax_entity_description.is_on_fn is not None:
            self._attr_is_on = self._sax_entity_description.is_on_fn(self._device)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if self._sax_entity_description.available_fn is None:
            return True
        return self._sax_entity_description.available_fn(self._device)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._sax_entity_description.turn_on_fn(self._device)
        # Update state after successful operation
        if self._sax_entity_description.is_on_fn is not None:
            self._attr_is_on = self._sax_entity_description.is_on_fn(self._device)
        else:
            self._attr_is_on = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._sax_entity_description.turn_off_fn(self._device)
        # Update state after successful operation
        if self._sax_entity_description.is_on_fn is not None:
            self._attr_is_on = self._sax_entity_description.is_on_fn(self._device)
        else:
            self._attr_is_on = False


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the SAX Battery switches."""
    data_manager: SAXBatteryDataManager = hass.data[DOMAIN][entry.entry_id]
    entities: list[SAXBatterySwitch] = []

    # Device info that will be shared between all entities
    device_info: DeviceInfo = {
        "identifiers": {(DOMAIN, data_manager.device_id)},
        "name": "SAX Battery System",
        "manufacturer": "SAX",
        "model": "SAX Battery",
        "sw_version": "1.0",
    }

    # Add battery switches using list.extend with list comprehension
    entities.extend(
        [
            SAXBatterySwitch(
                device_info=device_info,
                description=description,
                unique_id_prefix=f"{entry.entry_id}_{battery.battery_id}",
                device=battery,
            )
            for battery in data_manager.batteries.values()
            for description in BATTERY_SWITCH_TYPES
        ]
    )

    # Add pilot switches if enabled
    if entry.data.get(CONF_PILOT_FROM_HA, False):
        entities.extend(
            [
                SAXBatterySwitch(
                    device_info=device_info,
                    description=description,
                    unique_id_prefix=entry.entry_id,
                    device=data_manager,
                )
                for description in PILOT_SWITCH_TYPES
            ]
        )

    async_add_entities(entities)
