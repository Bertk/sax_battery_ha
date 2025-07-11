"""SAX Battery integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import SAXBatteryCoordinator
from .models import SAXBatterySystem

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SAX Battery from a config entry."""
    # Initialize SAX Battery system
    sax_system = SAXBatterySystem(entry=entry)
    await sax_system.async_setup()

    # Create battery-specific coordinators
    coordinators = {}
    for battery_id, battery in sax_system.batteries.items():
        # Get appropriate update interval for this battery
        update_interval = sax_system.get_polling_interval_for_battery(
            battery_id, "battery_realtime"
        )

        if sax_system.modbus_api is None:
            raise RuntimeError(
                f"Modbus API is not initialized for battery {battery_id}"
            )

        coordinator = SAXBatteryCoordinator(
            hass=hass,
            battery_id=battery_id,
            sax_data=sax_system,
            modbus_api=sax_system.modbus_api,
            update_interval=timedelta(seconds=update_interval),
        )

        # Perform initial data fetch
        await coordinator.async_config_entry_first_refresh()
        coordinators[battery_id] = coordinator

    # Store coordinators in sax_system for entity access
    sax_system.coordinators = coordinators

    # Store data
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = sax_system

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
