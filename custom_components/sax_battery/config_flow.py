"""Config flow for SAX Battery integration."""

from __future__ import annotations

import logging
from typing import Any
import uuid

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_PILOT_INTERVAL,
    CONF_BATTERY_COUNT,
    CONF_DEVICE_ID,
    CONF_ENABLE_SOLAR_CHARGING,
    CONF_LIMIT_POWER,
    CONF_MASTER_BATTERY,
    CONF_MIN_SOC,
    CONF_PF_SENSOR,
    CONF_PILOT_FROM_HA,
    CONF_POWER_SENSOR,
    CONF_PRIORITY_DEVICES,
    DEFAULT_AUTO_PILOT_INTERVAL,
    DEFAULT_MIN_SOC,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class SAXBatteryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SAX Battery."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._battery_count: int | None = None
        self._device_id: str = str(uuid.uuid4())  # Generate unique device ID
        self._pilot_from_ha: bool = False
        self._limit_power: bool = False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SAXBatteryOptionsFlowHandler:
        """Create the options flow."""
        return SAXBatteryOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store battery count and move to control options
            self._battery_count = user_input[CONF_BATTERY_COUNT]
            self._data.update(user_input)
            self._data[CONF_DEVICE_ID] = self._device_id  # Store device ID
            return await self.async_step_control_options()

        # Initial form - just ask for battery count
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BATTERY_COUNT, default=1): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=3)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_control_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle control options step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._pilot_from_ha = user_input[CONF_PILOT_FROM_HA]
            self._limit_power = user_input[CONF_LIMIT_POWER]
            self._data.update(user_input)

            # Debug logging to verify configuration storage
            _LOGGER.debug(
                "Control options saved: pilot_from_ha=%s, limit_power=%s",
                self._pilot_from_ha,
                self._limit_power,
            )

            # Route to appropriate next step based on selections
            if self._pilot_from_ha:
                return await self.async_step_pilot_options()
            else:  # noqa: RET505
                # Skip pilot-specific steps if not enabled
                return await self.async_step_battery_config()

        return self.async_show_form(
            step_id="control_options",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PILOT_FROM_HA, default=False): bool,
                    vol.Required(CONF_LIMIT_POWER, default=False): bool,
                }
            ),
            errors=errors,
            description_placeholders={
                "pilot_description": "Enable pilot mode to control battery power (registers 41, 42)",
                "limit_description": "Enable power limits to set max charge/discharge (registers 43, 44)",
            },
        )

    async def async_step_pilot_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure pilot options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Custom validation that allows us to show specific error messages
            validation_passed = True

            try:
                min_soc = int(user_input.get(CONF_MIN_SOC, DEFAULT_MIN_SOC))
                if not 0 <= min_soc <= 100:
                    errors[CONF_MIN_SOC] = "invalid_min_soc"
                    validation_passed = False
            except (ValueError, TypeError):
                errors[CONF_MIN_SOC] = "invalid_min_soc"
                validation_passed = False

            try:
                auto_pilot_interval = int(
                    user_input.get(
                        CONF_AUTO_PILOT_INTERVAL, DEFAULT_AUTO_PILOT_INTERVAL
                    )
                )
                if not 5 <= auto_pilot_interval <= 300:
                    errors[CONF_AUTO_PILOT_INTERVAL] = "invalid_interval"
                    validation_passed = False
            except (ValueError, TypeError):
                errors[CONF_AUTO_PILOT_INTERVAL] = "invalid_interval"
                validation_passed = False

            if validation_passed:
                self._data.update(user_input)
                return await self.async_step_sensors()

        # Create schema without strict validation to allow custom error handling
        return self.async_show_form(
            step_id="pilot_options",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MIN_SOC, default=DEFAULT_MIN_SOC): vol.Any(
                        int, str
                    ),
                    vol.Required(
                        CONF_AUTO_PILOT_INTERVAL, default=DEFAULT_AUTO_PILOT_INTERVAL
                    ): vol.Any(int, str),
                    vol.Required(CONF_ENABLE_SOLAR_CHARGING, default=True): bool,
                }
            ),
            errors=errors,
            description_placeholders={
                "min_soc_description": "Minimum State of Charge (%) to prevent deep discharge",
                "interval_description": "Update interval in seconds for pilot calculations",
                "solar_description": "Enable solar charging control logic",
            },
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure power and PF sensors."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_priority_devices()

        # Create schema based on pilot configuration
        schema = {}
        if self._pilot_from_ha:
            schema.update(
                {
                    vol.Required(CONF_POWER_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="sensor",
                        )
                    ),
                    vol.Required(CONF_PF_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="sensor",
                        )
                    ),
                }
            )

        # If no sensors are needed, skip this step
        if not schema:
            return await self.async_step_priority_devices()

        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "power_sensor_description": "Select smart meter power sensor for grid measurements",
                "pf_sensor_description": "Select power factor sensor for control calculations",
            },
        )

    async def async_step_priority_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure priority devices."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_battery_config()

        return self.async_show_form(
            step_id="priority_devices",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_PRIORITY_DEVICES): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            multiple=True,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "priority_devices_description": "Select devices that should have priority over battery usage (e.g., EV charger, heat pump)"
            },
        )

    async def async_step_battery_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure individual batteries."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)

            # Debug logging before creating entry
            _LOGGER.debug("Final configuration data: %s", self._data)
            _LOGGER.info(
                "Creating SAX Battery entry with limit_power=%s, pilot_from_ha=%s",
                self._data.get(CONF_LIMIT_POWER, False),
                self._data.get(CONF_PILOT_FROM_HA, False),
            )

            # Create the entry with all collected data
            return self.async_create_entry(
                title="SAX Battery",
                data=self._data,
            )

        # Generate schema for all batteries
        schema: dict[vol.Marker, Any] = {}
        battery_choices = []
        battery_count = self._battery_count or 0  # Default to 0 if None

        for i in range(1, battery_count + 1):
            battery_id = f"battery_{chr(96 + i)}"
            battery_choices.append(battery_id)

            schema[vol.Required(f"{battery_id}_host")] = str
            schema[vol.Required(f"{battery_id}_port", default=DEFAULT_PORT)] = vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            )

        # Add master battery selection only if more than 1 battery
        if battery_count > 1:
            schema[vol.Required(CONF_MASTER_BATTERY, default="battery_a")] = vol.In(
                battery_choices
            )
        else:
            # For single battery, automatically set battery_a as master
            self._data[CONF_MASTER_BATTERY] = "battery_a"

        return self.async_show_form(
            step_id="battery_config",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "battery_description": "Configure IP addresses and ports for each battery",
                "master_description": "Select which battery will be the master for control operations",
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the integration."""
        # Get existing entry data
        if user_input is not None:
            # Debug logging for reconfiguration
            _LOGGER.debug("Reconfiguration data: %s", user_input)

            return self.async_create_entry(
                title="SAX Battery",
                data=user_input,
            )

        # Load existing configuration data
        entry_id = self.context.get("entry_id")
        if entry_id is None:
            return self.async_abort(reason="unknown")

        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return self.async_abort(reason="unknown")

        # Copy existing data to allow modification
        self._data = dict(entry.data)
        self._battery_count = self._data.get(CONF_BATTERY_COUNT, 1)
        self._pilot_from_ha = self._data.get(CONF_PILOT_FROM_HA, False)
        self._limit_power = self._data.get(CONF_LIMIT_POWER, False)

        # Start reconfiguration from control options
        return await self.async_step_control_options()


class SAXBatteryOptionsFlowHandler(config_entries.OptionsFlow):
    """SAX Battery config flow options handler."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize SAX Battery options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            # Get the current configuration values
            current_pilot_from_ha = self.config_entry.data.get(
                CONF_PILOT_FROM_HA, False
            )
            current_limit_power = self.config_entry.data.get(CONF_LIMIT_POWER, False)

            # Extract pilot-specific options from user input
            pilot_options = {}
            if CONF_MIN_SOC in user_input:
                pilot_options[CONF_MIN_SOC] = user_input[CONF_MIN_SOC]
            if CONF_AUTO_PILOT_INTERVAL in user_input:
                pilot_options[CONF_AUTO_PILOT_INTERVAL] = user_input[
                    CONF_AUTO_PILOT_INTERVAL
                ]
            if CONF_ENABLE_SOLAR_CHARGING in user_input:
                pilot_options[CONF_ENABLE_SOLAR_CHARGING] = user_input[
                    CONF_ENABLE_SOLAR_CHARGING
                ]

            # Build result data - always include feature toggles
            result_data = {
                CONF_PILOT_FROM_HA: user_input.get(
                    CONF_PILOT_FROM_HA, current_pilot_from_ha
                ),
                CONF_LIMIT_POWER: user_input.get(CONF_LIMIT_POWER, current_limit_power),
            }

            # Only include pilot-specific options when pilot is enabled
            if user_input.get(CONF_PILOT_FROM_HA, current_pilot_from_ha):
                result_data.update(pilot_options)

            _LOGGER.debug("Options flow result data: %s", result_data)

            return self.async_create_entry(title="", data=result_data)

        # Get current configuration
        pilot_enabled = self.config_entry.data.get(CONF_PILOT_FROM_HA, False)
        limit_power_enabled = self.config_entry.data.get(CONF_LIMIT_POWER, False)

        schema: dict[vol.Marker, Any] = {}

        # Always show feature toggle options
        schema.update(
            {
                vol.Optional(
                    CONF_PILOT_FROM_HA,
                    default=self.config_entry.options.get(
                        CONF_PILOT_FROM_HA,
                        self.config_entry.data.get(CONF_PILOT_FROM_HA, False),
                    ),
                ): bool,
                vol.Optional(
                    CONF_LIMIT_POWER,
                    default=self.config_entry.options.get(
                        CONF_LIMIT_POWER,
                        self.config_entry.data.get(CONF_LIMIT_POWER, False),
                    ),
                ): bool,
            }
        )

        # Show pilot-specific options if pilot is currently enabled
        if pilot_enabled:
            schema.update(
                {
                    vol.Optional(
                        CONF_MIN_SOC,
                        default=self.config_entry.options.get(
                            CONF_MIN_SOC,
                            self.config_entry.data.get(CONF_MIN_SOC, DEFAULT_MIN_SOC),
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                    vol.Optional(
                        CONF_AUTO_PILOT_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_AUTO_PILOT_INTERVAL,
                            self.config_entry.data.get(
                                CONF_AUTO_PILOT_INTERVAL, DEFAULT_AUTO_PILOT_INTERVAL
                            ),
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=300)),
                    vol.Optional(
                        CONF_ENABLE_SOLAR_CHARGING,
                        default=self.config_entry.options.get(
                            CONF_ENABLE_SOLAR_CHARGING,
                            self.config_entry.data.get(
                                CONF_ENABLE_SOLAR_CHARGING, True
                            ),
                        ),
                    ): bool,
                }
            )

        # Show informative description based on current feature states
        description_placeholders = {
            "feature_toggles": "Enable or disable pilot mode (registers 41,42) and power limits (registers 43,44)",
        }

        if pilot_enabled:
            description_placeholders["pilot_options"] = "Configure pilot mode settings"
        else:
            description_placeholders["pilot_options"] = (
                "Pilot mode is disabled - enable it above to configure settings"
            )

        if limit_power_enabled:
            description_placeholders["power_limit_status"] = (
                "Power limits are enabled (registers 43,44 active)"
            )
        else:
            description_placeholders["power_limit_status"] = "Power limits are disabled"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            description_placeholders=description_placeholders,
        )
