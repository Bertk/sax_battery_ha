"""Number platform for SAX Battery integration."""
import logging
from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfPower
from .const import DOMAIN, CONF_LIMIT_POWER
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the SAX Battery number entities."""
    if not entry.data.get(CONF_LIMIT_POWER, False):
        return

    sax_battery_data = hass.data[DOMAIN][entry.entry_id]
    battery_count = len(sax_battery_data.batteries)
    
    
    entities = [
        SAXBatteryMaxChargeNumber(sax_battery_data, battery_count * 3500),
        SAXBatteryMaxDischargeNumber(sax_battery_data, battery_count * 4600)
    ]
    
    async_add_entities(entities)

class SAXBatteryMaxChargeNumber(NumberEntity):
    """SAX Battery Maximum Charge Power number."""
    
    def __init__(self, sax_battery_data, max_value):
        self._data_manager = sax_battery_data
        self._attr_unique_id = f"{DOMAIN}_max_charge"
        self._attr_name = "Maximum Charge Power"
        self._attr_native_min_value = 0
        self._attr_native_max_value = max_value
        self._attr_native_step = 50
        self._attr_native_unit_of_measurement = UnitOfPower.WATT
        self._attr_native_value = max_value
        self._last_written_value = None  # Track the last written value
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._data_manager.device_id)},
            "name": "SAX Battery System",
            "manufacturer": "SAX",
            "model": "SAX Battery",
            "sw_version": "1.0",
        }

    async def async_added_to_hass(self):
        """Set up periodic updates."""
        self._remove_interval = async_track_time_interval(
            self.hass, self._periodic_write, timedelta(minutes=2)
        )

    async def async_will_remove_from_hass(self):
        """Clean up on removal."""
        if hasattr(self, '_remove_interval'):
            self._remove_interval()

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        if value == self._attr_native_max_value and self._last_written_value == value:
            # Skip if value is at max and already set
            return
        
        await self._write_value(value)

    async def _periodic_write(self, _):
        """Write the value periodically."""
        if self._attr_native_value is not None:
            if self._attr_native_value == self._attr_native_max_value and self._last_written_value == self._attr_native_max_value:
                # Skip periodic writes for max value
                return
            await self._write_value(self._attr_native_value)

    async def _write_value(self, value: float):
        """Write the value to the hardware."""
        try:
            client = self._data_manager.master_battery._data_manager.modbus_clients[
                self._data_manager.master_battery.battery_id
            ]
            
            # Get the battery count
            battery_count = len(self._data_manager.batteries)
            # Calculate the per-battery value
            per_battery_value = int(value / battery_count)
            
            import asyncio
            # Add a small delay before writing
            await asyncio.sleep(0.1)
            
            _LOGGER.debug(f"Setting maximum charge power to {int(value)}W")
            
            # Use write_registers with the slave parameter as a keyword argument
            result = await self._data_manager.hass.async_add_executor_job(
                lambda: client.write_registers(
                    44,  # Register for max charge
                    [per_battery_value],  # Pass value as a list
                    slave=64
                )
            )
            
            _LOGGER.debug(f"Waiting for device to process the command...")
            # Add a longer delay for the device to process the command
            await asyncio.sleep(10)
            _LOGGER.debug("Resuming after wait period")
            
            self._attr_native_value = value
            self._last_written_value = value  # Update last written value
            
        except Exception as err:
            _LOGGER.error(f"Failed to write max charge value: {err}")
        
class SAXBatteryMaxDischargeNumber(NumberEntity):
    """SAX Battery Maximum Discharge Power number."""
    
    def __init__(self, sax_battery_data, max_value):
        self._data_manager = sax_battery_data
        self._attr_unique_id = f"{DOMAIN}_max_discharge"
        self._attr_name = "Maximum Discharge Power"
        self._attr_native_min_value = 0
        self._attr_native_max_value = max_value
        self._attr_native_step = 50
        self._attr_native_unit_of_measurement = UnitOfPower.WATT     
        self._attr_native_value = max_value   
        self._last_written_value = None  # Track the last written value
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._data_manager.device_id)},
            "name": "SAX Battery System",
            "manufacturer": "SAX",
            "model": "SAX Battery",
            "sw_version": "1.0",
        }

    async def async_added_to_hass(self):
        """Set up periodic updates."""
        self._remove_interval = async_track_time_interval(
            self.hass, self._periodic_write, timedelta(minutes=2)
        )

    async def async_will_remove_from_hass(self):
        """Clean up on removal."""
        if hasattr(self, '_remove_interval'):
            self._remove_interval()

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        if value == self._attr_native_max_value and self._last_written_value == value:
            # Skip if value is at max and already set
            return
        
        await self._write_value(value)

    async def _periodic_write(self, _):
        """Write the value periodically."""
        if self._attr_native_value is not None:
            if self._attr_native_value == self._attr_native_max_value and self._last_written_value == self._attr_native_max_value:
                # Skip periodic writes for max value
                return
            await self._write_value(self._attr_native_value)

    async def _write_value(self, value: float):
        """Write the value to the hardware."""
        try:
            client = self._data_manager.master_battery._data_manager.modbus_clients[
                self._data_manager.master_battery.battery_id
            ]

            # Get the battery count
            battery_count = len(self._data_manager.batteries)
            # Calculate the per-battery value
            per_battery_value = int(value / battery_count)

            import asyncio
            # Add a small delay before writing
            await asyncio.sleep(0.1)
            
            _LOGGER.debug(f"Setting maximum charge power to {int(value)}W")
            
            # Use write_registers with the slave parameter as a keyword argument
            result = await self._data_manager.hass.async_add_executor_job(
                lambda: client.write_registers(
                    43,  # Register for max discharge
                    [per_battery_value],  # Pass value as a list
                    slave=64
                )
            )
            
            _LOGGER.debug(f"Waiting for device to process the command...")
            # Add a longer delay for the device to process the command
            await asyncio.sleep(10)
            _LOGGER.debug("Resuming after wait period")
            
            self._attr_native_value = value
            self._last_written_value = value  # Update last written value
            
        except Exception as err:
            _LOGGER.error(f"Failed to write max charge value: {err}")
