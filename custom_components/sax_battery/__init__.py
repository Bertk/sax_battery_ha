"""Integration for SAX Battery."""

import logging
from typing import Any

from pymodbus.client import ModbusTcpClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from .const import (
    CONF_DEVICE_ID,
    # CONF_MANUAL_CONTROL,
    CONF_PILOT_FROM_HA,
    DOMAIN,
    SAX_SOC,
    SAX_STATUS,
)
from .pilot import async_setup_pilot

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the SAX Battery integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SAX Battery from a config entry."""
    try:
        # Create SAX Battery data instance
        sax_battery_data = SAXBatteryData(hass, entry)
        await sax_battery_data.async_init()
    except (ConnectionError, TimeoutError, ValueError) as err:
        _LOGGER.error("Failed to initialize SAX Battery: %s", err)
        raise ConfigEntryNotReady from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = sax_battery_data

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up pilot service if enabled
    if entry.data.get(CONF_PILOT_FROM_HA, False):
        await async_setup_pilot(hass, entry.entry_id)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Stop pilot service if running
        sax_battery_data = hass.data[DOMAIN][entry.entry_id]
        if hasattr(sax_battery_data, "pilot"):
            await sax_battery_data.pilot.async_stop()

        # Close all Modbus connections
        for client in sax_battery_data.modbus_clients.values():
            client.close()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class SAXBatteryData:
    """Manages SAX Battery Modbus communication and data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the SAX Battery data manager."""
        self.hass = hass
        self.entry = entry
        self.device_id = entry.data.get(CONF_DEVICE_ID)
        self.master_battery: SAXBattery | None = None
        # Fix: Use SAXBattery instead of BatteryData
        self.batteries: dict[str, SAXBattery] = {}
        self.modbus_clients: dict[str, ModbusTcpClient] = {}
        self.power_sensor_entity_id = entry.data.get("power_sensor_entity_id")
        self.pf_sensor_entity_id = entry.data.get("pf_sensor_entity_id")
        self.modbus_registers: dict[str, dict[str, Any]] = {}
        # Use float timestamps for better performance
        self.last_updates: dict[str, float] = {}

    async def async_init(self) -> None:
        """Initialize Modbus connections and battery data."""
        battery_count = self.entry.data.get("battery_count")
        master_battery_id = self.entry.data.get("master_battery")

        _LOGGER.debug(
            "Initializing %s batteries. Master: %s", battery_count, master_battery_id
        )

        for i in range(1, battery_count + 1):  # type: ignore[operator]
            battery_id = f"battery_{chr(96 + i)}"
            host = self.entry.data.get(f"{battery_id}_host")
            port = self.entry.data.get(f"{battery_id}_port")

            _LOGGER.debug("Setting up battery %s at %s:%s", battery_id, host, port)

            try:
                # Validate host and port before creating client
                if not host or not port:
                    msg = f"Missing host or port for {battery_id}"
                    raise ConfigEntryError(msg)

                # Initialize Modbus TCP client with proper parameters
                client = ModbusTcpClient(
                    host=str(host),
                    port=int(port),
                    timeout=10,
                )

                if not client.connect():
                    raise ConnectionError(f"Could not connect to {host}:{port}")

                self.modbus_clients[battery_id] = client
                _LOGGER.info("Successfully connected to battery at %s:%s", host, port)

                # Create SAXBattery instance
                battery = SAXBattery(self.hass, self, battery_id)
                self.batteries[battery_id] = battery

                # Set master battery if this is the one
                if battery_id == master_battery_id:
                    self.master_battery = battery

                # Initialize the registers configuration
                self.modbus_registers[battery_id] = {
                    SAX_STATUS: {
                        "address": 45,
                        "count": 1,
                        "data_type": "int",
                        "slave": 64,
                        "scan_interval": 60,
                        "state_on": 3,
                        "state_off": 1,
                        "command_on": 2,
                        "command_off": 1,
                    },
                    SAX_SOC: {
                        "address": 46,
                        "count": 1,
                        "data_type": "int",
                        "slave": 64,
                        "scan_interval": 60,
                    },
                    # ... rest of your register definitions
                }

            except Exception as err:
                _LOGGER.error("Failed to initialize battery %s: %s", battery_id, err)
                raise


###
class SAXBattery:
    """Represents a single SAX Battery."""

    def __init__(
        self, hass: HomeAssistant, data_manager: SAXBatteryData, battery_id: str
    ) -> None:
        """Initialize the battery."""
        self.hass = hass
        self._data_manager = data_manager
        self.battery_id = battery_id
        self.data: dict[str, Any] = {}
        # Use float timestamps for monotonic time
        self._last_updates: dict[str, float] = {}

    async def async_update(self) -> bool:
        """Update the battery data."""
        try:
            client = self._data_manager.modbus_clients[self.battery_id]
            registers = self._data_manager.modbus_registers[self.battery_id]
            current_time = self.hass.loop.time()  # Monotonic time

            # Initialize missing timestamps
            for register_name in registers:
                if register_name not in self._last_updates:
                    self._last_updates[register_name] = 0

            # Handle standard requests for non-slave 40
            for register_name, register_info in registers.items():
                if register_info["slave"] != 40:
                    # Check if enough time has passed since last update
                    time_since_update = current_time - self._last_updates.get(
                        register_name, 0
                    )
                    if time_since_update < register_info["scan_interval"]:
                        continue

                    try:
                        result = await self.read_modbus_register(client, register_info)
                        if result is not None:
                            self.data[register_name] = result
                            self._last_updates[register_name] = current_time
                    except (ConnectionError, TimeoutError) as err:
                        _LOGGER.error(
                            "Error updating register %s: %s", register_name, err
                        )

            return True

        except Exception as err:
            _LOGGER.error("Failed to update battery %s: %s", self.battery_id, err)
            return False

    async def read_modbus_register(
        self, client: ModbusTcpClient, register_info: dict[str, Any]
    ) -> int | float | None:
        """Read a single Modbus register."""
        try:

            def _read_holding_registers() -> Any:
                """Execute the blocking Modbus read operation."""
                return client.read_holding_registers(
                    address=register_info["address"],
                    slave=register_info["slave"],
                    count=register_info.get("count", 1),
                )

            result = await self.hass.async_add_executor_job(_read_holding_registers)

            if result.isError():
                return None

            # Safe extraction with proper defaults and type checking
            raw_value = result.registers[0]
            offset = register_info.get("offset", 0)
            scale = register_info.get("scale", 1)

            # Ensure we have numeric values
            if not isinstance(offset, (int, float)):
                offset = 0
            if not isinstance(scale, (int, float)) or scale == 0:
                scale = 1

            return float((raw_value + offset) * scale)

        except Exception as err:
            _LOGGER.error(
                "Error reading register %s: %s", register_info["address"], err
            )
            return None
