"""Number platform for SAX Battery integration."""

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_AUTO_PILOT_INTERVAL,
    CONF_LIMIT_POWER,
    CONF_MANUAL_CONTROL,
    CONF_MIN_SOC,
    CONF_PILOT_FROM_HA,
    DEFAULT_AUTO_PILOT_INTERVAL,
    DEFAULT_MIN_SOC,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SAXBatteryNumberEntityDescription(NumberEntityDescription):
    """Class describing SAX Battery number entities."""

    write_value_fn: Callable[[Any, float], None] = lambda x, y: None
    availability_fn: Callable[[Any], bool] = lambda x: True
    icon_fn: Callable[[Any], str | None] | None = None


BATTERY_POWER_NUMBERS = (
    SAXBatteryNumberEntityDescription(
        key="max_charge",
        name="Maximum Charge Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_step=50,
        mode=NumberMode.BOX,
    ),
    SAXBatteryNumberEntityDescription(
        key="max_discharge",
        name="Maximum Discharge Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_step=50,
        mode=NumberMode.BOX,
    ),
)

PILOT_NUMBERS = (
    SAXBatteryNumberEntityDescription(
        key="pilot_interval",
        name="Auto Pilot Interval",
        native_unit_of_measurement="s",
        native_min_value=5,
        native_max_value=300,
        native_step=5,
        mode=NumberMode.BOX,
    ),
    SAXBatteryNumberEntityDescription(
        key="min_soc",
        name="Minimum State of Charge",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.BOX,
    ),
    SAXBatteryNumberEntityDescription(
        key="manual_power",
        name="Battery Manual Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        native_step=100,
        mode=NumberMode.SLIDER,
        icon_fn=lambda entity: (
            "mdi:battery-charging"
            if entity.native_value and entity.native_value > 0
            else "mdi:battery-minus"
            if entity.native_value and entity.native_value < 0
            else "mdi:battery"
        ),
        availability_fn=lambda entity: entity._data_manager.entry.data.get(
            CONF_MANUAL_CONTROL, False
        ),
    ),
)


class SAXBatteryNumber(NumberEntity):
    """Base class for SAX Battery number entities."""

    entity_description: SAXBatteryNumberEntityDescription

    def __init__(
        self,
        data_manager: Any,
        description: SAXBatteryNumberEntityDescription,
        native_max_value: float,
        native_value: float | None = None,
    ) -> None:
        """Initialize the number entity."""
        self._data_manager = data_manager
        self.entity_description = description
        self._attr_unique_id = f"{data_manager.device_id}_{description.key}"
        self._attr_native_max_value = native_max_value
        self._attr_native_value = native_value or native_max_value

        self._attr_device_info = {
            "identifiers": {(DOMAIN, data_manager.device_id)},
            "name": "SAX Battery System",
            "manufacturer": "SAX",
            "model": "SAX Battery",
            "sw_version": "1.0",
        }

    @property
    def icon(self) -> str | None:
        """Return the icon."""
        if self.entity_description.icon_fn is not None:
            return self.entity_description.icon_fn(self)
        return super().icon

    @property
    def available(self) -> bool:
        """Return availability."""
        return self.entity_description.availability_fn(self)

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        self.entity_description.write_value_fn(self._data_manager, value)
        self._attr_native_value = value
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SAX Battery number entities."""
    sax_battery_data = hass.data[DOMAIN][entry.entry_id]
    battery_count = len(sax_battery_data.batteries)
    entities: list[NumberEntity] = []

    # Add power limiting entities
    if entry.data.get(CONF_LIMIT_POWER, False):
        max_charge = battery_count * 3500
        max_discharge = battery_count * 4600

        for description in BATTERY_POWER_NUMBERS:
            max_value = max_charge if description.key == "max_charge" else max_discharge
            entities.append(SAXBatteryNumber(sax_battery_data, description, max_value))

    # Add pilot-related number entities
    if entry.data.get(CONF_PILOT_FROM_HA, False):
        for description in PILOT_NUMBERS:
            match description.key:
                case "manual_power":
                    entities.append(
                        SAXBatteryNumber(
                            sax_battery_data,
                            description,
                            battery_count * 4500,  # max charge power
                            native_value=0,
                        )
                    )
                case "pilot_interval":
                    entities.append(
                        SAXBatteryNumber(
                            sax_battery_data,
                            description,
                            description.native_max_value or 300,
                            entry.data.get(
                                CONF_AUTO_PILOT_INTERVAL, DEFAULT_AUTO_PILOT_INTERVAL
                            ),
                        )
                    )
                case "min_soc":
                    entities.append(
                        SAXBatteryNumber(
                            sax_battery_data,
                            description,
                            description.native_max_value or 100,
                            entry.data.get(CONF_MIN_SOC, DEFAULT_MIN_SOC),
                        )
                    )

    async_add_entities(entities)
