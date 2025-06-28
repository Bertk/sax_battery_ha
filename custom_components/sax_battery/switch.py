"""Switch platform for SAX Battery integration."""

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_ENABLE_SOLAR_CHARGING,
    CONF_MANUAL_CONTROL,
    CONF_PILOT_FROM_HA,
    DOMAIN,
    SAX_STATUS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SAXBatterySwitchEntityDescription(SwitchEntityDescription):
    """Class describing SAX Battery switch entities."""

    turn_on_fn: Callable[[Any], None] = lambda x: None
    turn_off_fn: Callable[[Any], None] = lambda x: None
    is_on_fn: Callable[[Any], bool] = lambda x: False
    available_fn: Callable[[Any], bool] = lambda x: True


BATTERY_SWITCH_TYPES = (
    SAXBatterySwitchEntityDescription(
        key="battery_switch",
        name="Battery Switch",
        is_on_fn=lambda battery: (
            battery.data.get(SAX_STATUS)
            == battery._data_manager.modbus_registers[battery.battery_id][SAX_STATUS][
                "state_on"
            ]
        ),
        available_fn=lambda battery: SAX_STATUS in battery.data,
    ),
)

PILOT_SWITCH_TYPES = (
    SAXBatterySwitchEntityDescription(
        key="solar_charging",
        name="Solar Charging",
        icon="mdi:solar-power",
        is_on_fn=lambda data: data.get(CONF_ENABLE_SOLAR_CHARGING, True),
    ),
    SAXBatterySwitchEntityDescription(
        key="manual_control",
        name="Manual Control",
        icon="mdi:hand",
        is_on_fn=lambda data: data.get(CONF_MANUAL_CONTROL, False),
    ),
)


class SAXBatterySwitch(SwitchEntity):
    """Base class for SAX Battery switches."""

    entity_description: SAXBatterySwitchEntityDescription

    def __init__(
        self,
        device_info: DeviceInfo,
        description: SAXBatterySwitchEntityDescription,
        unique_id_prefix: str,
    ) -> None:
        """Initialize the switch."""
        self.entity_description = description  # type: ignore[override]
        self._attr_device_info = device_info
        self._attr_unique_id = f"{unique_id_prefix}_{description.key}"
        self._attr_name = f"Sax Battery {description.name}"
        self._device: Any = None

    @property
    def is_on(self) -> bool:  # type: ignore[override]
        """Return true if switch is on."""
        return self.entity_description.is_on_fn(self._device)

    @property
    def available(self) -> bool:  # type: ignore[override]
        """Return True if entity is available."""
        return self.entity_description.available_fn(self._device)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self.entity_description.turn_on_fn(self._device)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self.entity_description.turn_off_fn(self._device)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the SAX Battery switches."""
    sax_battery_data = hass.data[DOMAIN][entry.entry_id]
    entities: list[SAXBatterySwitch] = []

    # Device info that will be shared between all entities
    device_info: DeviceInfo = {
        "identifiers": {(DOMAIN, sax_battery_data.device_id)},
        "name": "SAX Battery System",
        "manufacturer": "SAX",
        "model": "SAX Battery",
        "sw_version": "1.0",
    }

    # Add battery switches
    for battery in sax_battery_data.batteries.values():
        for description in BATTERY_SWITCH_TYPES:
            switch = SAXBatterySwitch(
                device_info=device_info,
                description=description,
                unique_id_prefix=f"{entry.entry_id}_{battery.battery_id}",
            )
            switch._device = battery
            entities.append(switch)

    # Add pilot switches if enabled
    if entry.data.get(CONF_PILOT_FROM_HA, False):
        for description in PILOT_SWITCH_TYPES:
            switch = SAXBatterySwitch(
                device_info=device_info,
                description=description,
                unique_id_prefix=entry.entry_id,
            )
            switch._device = sax_battery_data
            entities.append(switch)

    async_add_entities(entities)
