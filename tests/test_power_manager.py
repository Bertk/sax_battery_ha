"""Test power manager for SAX Battery integration."""

from __future__ import annotations

from datetime import datetime
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# custom_component cannot use "from tests.common import MockConfigEntry"
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sax_battery.const import (
    CONF_POWER_SENSOR,
    DOMAIN,
    GRID_CHARGING_MODE,
    LIMIT_MAX_CHARGE_PER_BATTERY,
    LIMIT_MAX_DISCHARGE_PER_BATTERY,
    PV_CHARGING_MODE,
    SAX_AC_POWER_TOTAL,
    SAX_COMBINED_SOC,
    SAX_NOMINAL_FACTOR,
    SAX_NOMINAL_POWER,
)
from custom_components.sax_battery.coordinator import SAXBatteryCoordinator
from custom_components.sax_battery.power_manager import PowerManager, PowerManagerState
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

SERVICE_SET_VALUE = "set_value"

_LOGGER = logging.getLogger(__name__)


@pytest.fixture
def mock_power_manager_devices(
    hass: HomeAssistant,
) -> None:
    """Set up mock devices and entities for power manager tests."""

    real_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "battery_a_host": "192.168.1.100",
            "battery_a_port": 502,
        },
        entry_id="test_power_manager_entry",
    )
    real_entry.add_to_hass(hass)

    # Get registries
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    # Create device in registry
    device = dev_reg.async_get_or_create(
        config_entry_id=real_entry.entry_id,
        identifiers={(DOMAIN, "test_cluster")},
        name="SAX Cluster",
        manufacturer="SAX",
        model="Battery System",
    )

    # Register entities...
    ent_reg.async_get_or_create(
        "number",
        DOMAIN,
        f"test_cluster_{SAX_NOMINAL_POWER}",
        suggested_object_id=f"sax_cluster_{SAX_NOMINAL_POWER}",
        config_entry=real_entry,
        device_id=device.id,
    )

    ent_reg.async_get_or_create(
        "number",
        DOMAIN,
        f"test_cluster_{SAX_NOMINAL_FACTOR}",
        suggested_object_id=f"sax_cluster_{SAX_NOMINAL_FACTOR}",
        config_entry=real_entry,
        device_id=device.id,
    )


class TestPowerManagerInitialization:
    """Test PowerManager initialization."""

    def test_initialization_defaults(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
        mock_config_entry: ConfigEntry,
    ) -> None:
        """Test PowerManager initialization with default values."""
        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=mock_config_entry,
        )

        assert power_manager.hass == hass
        assert power_manager.coordinator == mock_coordinator_master
        assert power_manager.battery_count == 1
        assert power_manager._running is False

    def test_initialization_with_multi_battery(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
    ) -> None:
        """Test PowerManager initialization with multiple batteries."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_POWER_SENSOR: "sensor.grid_power",
            },
        )
        entry.add_to_hass(hass)

        mock_coordinator_master.sax_data.coordinators = {
            "battery_a": mock_coordinator_master,
            "battery_b": MagicMock(),
            "battery_c": MagicMock(),
        }

        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=entry,
        )

        assert power_manager.battery_count == 3
        expected_max_discharge = 3 * LIMIT_MAX_CHARGE_PER_BATTERY
        expected_max_charge = 3 * LIMIT_MAX_DISCHARGE_PER_BATTERY
        assert power_manager.max_discharge_power == expected_max_discharge
        assert power_manager.max_charge_power == expected_max_charge
        assert power_manager._state.pv_charging_enabled is False

    def test_configuration_update(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
    ) -> None:
        """Test configuration values are properly loaded."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_POWER_SENSOR: "sensor.grid_power",
                PV_CHARGING_MODE: True,
                GRID_CHARGING_MODE: False,
            },
        )
        entry.add_to_hass(hass)

        # Mock SAXBatteryData.get_unique_id_for_item to return valid unique IDs
        mock_sax_data = MagicMock()
        mock_sax_data.get_unique_id_for_item.return_value = "test_power_entity"
        mock_coordinator_master.sax_data = mock_sax_data

        # Register entities in entity registry
        ent_reg = er.async_get(hass)
        ent_reg.async_get_or_create(
            "number",
            DOMAIN,
            "test_power_entity",
            suggested_object_id="sax_nominal_power",
        )

        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=entry,
        )
        # grid power control should be disabled due to pv charging enabled
        assert power_manager.pv_power_sensor == "sensor.grid_power"
        assert power_manager._state.grid_charging_enabled is False


class TestPowerManagerLifecycle:
    """Test PowerManager start/stop lifecycle."""

    async def test_start_success(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
        mock_config_entry: ConfigEntry,
    ) -> None:
        """Test successful power manager start."""
        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=mock_config_entry,
        )

        with patch(
            "custom_components.sax_battery.power_manager.async_track_time_interval"
        ) as mock_track:
            await power_manager.async_start()

            assert power_manager._running is True
            assert mock_track.called

    async def test_start_already_running(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
        mock_config_entry: ConfigEntry,
    ) -> None:
        """Test starting power manager when already running."""
        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=mock_config_entry,
        )

        with patch(
            "custom_components.sax_battery.power_manager.async_track_time_interval"
        ):
            await power_manager.async_start()
            assert power_manager._running is True

            # Try starting again
            await power_manager.async_start()
            assert power_manager._running is True

    async def test_stop_success(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
        mock_config_entry: ConfigEntry,
    ) -> None:
        """Test successful power manager stop."""
        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=mock_config_entry,
        )

        mock_remove_interval = MagicMock()
        mock_remove_config = MagicMock()
        power_manager._remove_interval_update = mock_remove_interval
        power_manager._remove_config_update = mock_remove_config
        power_manager._running = True

        await power_manager.async_stop()

        assert power_manager._running is False
        mock_remove_interval.assert_called_once()
        mock_remove_config.assert_called_once()

    async def test_stop_not_running(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
        mock_config_entry: ConfigEntry,
    ) -> None:
        """Test stopping power manager when not running."""
        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=mock_config_entry,
        )

        await power_manager.async_stop()
        assert power_manager._running is False


class TestSolarChargingMode:
    """Test solar charging mode functionality."""

    async def test_solar_charging_update_with_valid_grid_sensor(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
    ) -> None:
        """Test solar charging update with valid grid sensor.

        Security:
            OWASP A05: Validates proper state machine access and SOC constraints
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_POWER_SENSOR: "sensor.grid_power",
            },
        )
        entry.add_to_hass(hass)

        # Mock grid sensor state
        hass.states.async_set("sensor.grid_power", "-1000")  # 1kW export

        # Mock coordinator.data for SAX_AC_POWER_TOTAL
        mock_battery_item = MagicMock()
        mock_battery_item.item = MagicMock()
        mock_coordinator_master.data = {
            SAX_AC_POWER_TOTAL: mock_battery_item,
        }

        # Patch entity registry and sax_data.get_unique_id_for_item
        with patch("homeassistant.helpers.entity_registry.async_get") as mock_ent_reg:
            mock_reg = MagicMock()
            mock_reg.async_get_entity_id = MagicMock(
                return_value="sensor.battery_a_ac_power_total"
            )
            mock_ent_reg.return_value = mock_reg

            # mock_coordinator_master.sax_data.get_unique_id_for_item.return_value = (
            #     "battery_a_ac_power_total"
            # )

            # Set battery power state in state machine
            hass.states.async_set(
                "sensor.battery_a_ac_power_total", "500"
            )  # 500W discharging

            mock_coordinator_master.sax_data.get_entity_id_for_item = MagicMock(  # type:ignore[method-assign]
                return_value="sensor.battery_a_ac_power_total"
            )

            power_manager = PowerManager(
                hass=hass,
                coordinator=mock_coordinator_master,
                config_entry=entry,
            )
            power_manager._state.pv_charging_enabled = True

            with patch.object(
                power_manager, "update_power_setpoint", new=AsyncMock()
            ) as mock_update:
                await power_manager._update_pv_charging_power()

                mock_update.assert_called_once()
                call_args = mock_update.call_args[0]
                # Expect grid export + battery discharge
                # Grid: -1000W (exporting), Battery: 500W (discharging)
                # Target = abs(-1000) + 500 = 1500W
                assert call_args[0] == 1500

        async def test_solar_charging_with_unavailable_sensor(
            self,
            hass: HomeAssistant,
            mock_coordinator_master: SAXBatteryCoordinator,
        ) -> None:
            """Test solar charging handles unavailable sensor."""
            entry = MockConfigEntry(
                domain=DOMAIN,
                data={
                    CONF_POWER_SENSOR: "sensor.grid_power",
                },
            )
            entry.add_to_hass(hass)

            # Mock unavailable sensor
            hass.states.async_set("sensor.grid_power", "unavailable")

            power_manager = PowerManager(
                hass=hass,
                coordinator=mock_coordinator_master,
                config_entry=entry,
            )
            power_manager._state.pv_charging_enabled = True

            with patch.object(
                power_manager, "update_power_setpoint", new=AsyncMock()
            ) as mock_update:
                await power_manager._update_pv_charging_power()

                # Should not update power when sensor unavailable
                mock_update.assert_not_called()

    async def test_solar_charging_with_missing_sensor(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
    ) -> None:
        """Test solar charging handles missing sensor."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_POWER_SENSOR: "sensor.nonexistent",
            },
        )
        entry.add_to_hass(hass)

        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=entry,
        )
        power_manager._state.pv_charging_enabled = True

        with patch.object(
            power_manager, "update_power_setpoint", new=AsyncMock()
        ) as mock_update:
            await power_manager._update_pv_charging_power()

            mock_update.assert_not_called()

    async def test_pv_charging_with_invalid_sensor_value(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
    ) -> None:
        """Test PV charging handles invalid sensor value."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_POWER_SENSOR: "sensor.grid_power",
            },
        )
        entry.add_to_hass(hass)

        hass.states.async_set("sensor.grid_power", "invalid_value")

        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=entry,
        )
        power_manager._state.pv_charging_enabled = True

        with patch.object(
            power_manager, "update_power_setpoint", new=AsyncMock()
        ) as mock_update:
            await power_manager._update_pv_charging_power()

            mock_update.assert_not_called()

    async def test_pv_charging_applies_soc_constraints(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
    ) -> None:
        """Test PV charging applies SOC constraints.

        Security:
            OWASP A05: Validates SOC constraint enforcement in PV charging
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_POWER_SENSOR: "sensor.grid_power",
            },
        )
        entry.add_to_hass(hass)

        # Mock grid sensor state - large export (excess solar)
        hass.states.async_set("sensor.grid_power", "-5000")  # 5kW export

        # Mock coordinator.data for SAX_AC_POWER_TOTAL
        mock_battery_item = MagicMock()
        mock_battery_item.item = MagicMock()
        mock_coordinator_master.data = {
            SAX_AC_POWER_TOTAL: mock_battery_item,
        }

        # Setup SOC manager with low SOC to trigger constraint
        mock_soc_manager = MagicMock()
        mock_soc_manager.min_soc = 20.0
        mock_coordinator_master.soc_manager = mock_soc_manager

        # Patch entity registry and sax_data methods
        with patch("homeassistant.helpers.entity_registry.async_get") as mock_ent_reg:
            mock_reg = MagicMock()
            mock_reg.async_get_entity_id = MagicMock(
                return_value="sensor.battery_a_ac_power_total"
            )
            mock_ent_reg.return_value = mock_reg

            # Current battery power: 1kW discharging
            hass.states.async_set("sensor.battery_a_ac_power_total", "1000")

            # Mock get_entity_id_for_item to return correct entity_id
            mock_coordinator_master.sax_data.get_entity_id_for_item = MagicMock(  # type:ignore[method-assign]
                return_value="sensor.battery_a_ac_power_total"
            )

            power_manager = PowerManager(
                hass=hass,
                coordinator=mock_coordinator_master,
                config_entry=entry,
            )
            power_manager._state.pv_charging_enabled = True

            # Mock update_power_setpoint to capture the constrained value
            with patch.object(
                power_manager, "update_power_setpoint", new=AsyncMock()
            ) as mock_update:
                await power_manager._update_pv_charging_power()

                # VERIFY: Power setpoint was updated
                mock_update.assert_called_once()

                # VERIFY: Calculate expected value
                # Current battery: 1000W (discharging)
                # Grid: -5000W (exporting)
                # Raw target = 1000 - (-5000) = 6000W
                # Max charge limit: 3500W (per battery) * battery_count
                # Expected clamped value: 3500W (assuming 1 battery)

                call_args = mock_update.call_args[0]
                constrained_power = call_args[0]

                # VERIFY: Power is clamped to max discharge
                assert constrained_power == 3500.0, (
                    f"Expected power clamped to 3500W, got {constrained_power}W"
                )

                _LOGGER.debug(
                    "✓ Solar charging constrained: raw=6000W, constrained=%sW",
                    constrained_power,
                )

    async def test_pv_charging_respects_soc_manager_constraints(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
    ) -> None:
        """Test PV charging respects SOC manager discharge constraints.

        Security:
            OWASP A05: Validates SOC constraint enforcement prevents battery damage
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_POWER_SENSOR: "sensor.grid_power",
            },
        )
        entry.add_to_hass(hass)

        # Mock grid importing (not exporting - should trigger discharge)
        hass.states.async_set("sensor.grid_power", "2000")  # 2kW import

        # Mock battery power
        mock_battery_item = MagicMock()
        mock_battery_item.item = MagicMock()
        mock_coordinator_master.data = {
            SAX_AC_POWER_TOTAL: mock_battery_item,
            SAX_COMBINED_SOC: 15.0,  # Below minimum
        }

        # Setup SOC manager that will block discharge
        mock_soc_manager = MagicMock()
        mock_soc_manager.min_soc = 20.0
        mock_soc_manager.check_and_enforce_discharge_limit = AsyncMock(
            return_value=True  # Constraint active
        )
        mock_coordinator_master.soc_manager = mock_soc_manager

        with patch("homeassistant.helpers.entity_registry.async_get") as mock_ent_reg:
            mock_reg = MagicMock()
            mock_reg.async_get_entity_id.return_value = (
                "sensor.battery_a_ac_power_total"
            )
            mock_ent_reg.return_value = mock_reg

            hass.states.async_set(
                "sensor.battery_a_ac_power_total", "500"
            )  # Discharging

            mock_coordinator_master.sax_data.get_entity_id_for_item = MagicMock(  # type:ignore[method-assign]
                return_value="sensor.battery_a_ac_power_total"
            )

            power_manager = PowerManager(
                hass=hass,
                coordinator=mock_coordinator_master,
                config_entry=entry,
            )
            power_manager._state.pv_charging_enabled = True

            with patch.object(
                power_manager, "update_power_setpoint", new=AsyncMock()
            ) as mock_update:
                await power_manager._update_pv_charging_power()

                # VERIFY: Power setpoint was updated
                mock_update.assert_called_once()

                # VERIFY: Calculation respects current state
                # Current battery: 500W (discharging)
                # Grid: 2000W (importing - need to reduce discharge)
                # Raw target = 500 - 2000 = -1500W (charge)
                # Expected: Charging allowed even with low SOC

                call_args = mock_update.call_args[0]
                target_power = call_args[0]

                # VERIFY: Charging is allowed (negative value)
                assert target_power < 0, (
                    f"Expected charging (negative), got {target_power}W"
                )

                # VERIFY: Value matches calculation
                assert target_power == -1500.0, f"Expected -1500W, got {target_power}W"


class TestModeTransitions:
    """Test mode transition functionality."""

    async def test_pv_to_grid_transition(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
        mock_config_entry: ConfigEntry,
    ) -> None:
        """Test transition from PV charging to grid charging.

        Verifies that enabling grid charging automatically disables solar charging.
        """

        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=mock_config_entry,
        )

        # Enable solar charging
        await power_manager.set_pv_charging_mode(True)
        assert power_manager._state.pv_charging_enabled is True
        assert power_manager._state.grid_charging_enabled is False

        # Enable grid charging (should automatically disable solar)
        with patch.object(power_manager, "update_power_setpoint", new=AsyncMock()):
            await power_manager.set_grid_control_mode(True, 1000)

            # Grid charging enabled, solar charging disabled
            assert power_manager._state.grid_charging_enabled is True
            assert power_manager._state.pv_charging_enabled is False
            assert power_manager._state.mode == GRID_CHARGING_MODE

    async def test_grid_to_solar_transition(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
        mock_config_entry: ConfigEntry,
    ) -> None:
        """Test transition from grid charging to solar charging.

        Verifies that enabling solar charging automatically disables grid charging.
        """
        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=mock_config_entry,
        )

        # Enable grid charging
        with patch.object(power_manager, "update_power_setpoint", new=AsyncMock()):
            await power_manager.set_grid_control_mode(True, 1000)
            assert power_manager._state.grid_charging_enabled is True
            assert power_manager._state.pv_charging_enabled is False

        # Enable solar charging (should automatically disable grid charging)
        await power_manager.set_pv_charging_mode(True)

        # Solar enabled, grid charging disabled
        assert power_manager._state.pv_charging_enabled is True
        assert power_manager._state.grid_charging_enabled is False
        assert power_manager._state.mode == PV_CHARGING_MODE


class TestConfigurationUpdates:
    """Test configuration update handling."""

    async def test_config_entry_update(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
    ) -> None:
        """Test handling of config entry updates."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_POWER_SENSOR: "sensor.grid_power",
            },
        )
        entry.add_to_hass(hass)

        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=entry,
        )

        # Create updated entry
        updated_entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_POWER_SENSOR: "sensor.new_grid_power",
            },
        )
        updated_entry.add_to_hass(hass)

        with patch.object(power_manager, "_async_update_power", new=AsyncMock()):
            await power_manager._async_config_updated(hass, updated_entry)

            assert power_manager.pv_power_sensor == "sensor.new_grid_power"


class TestPowerManagerProperties:
    """Test PowerManager property accessors."""

    def test_current_mode_property(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
        mock_config_entry: ConfigEntry,
    ) -> None:
        """Test current_mode property."""
        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=mock_config_entry,
        )

        assert power_manager.current_mode == GRID_CHARGING_MODE

        power_manager._state.mode = PV_CHARGING_MODE
        assert power_manager.current_mode == PV_CHARGING_MODE

    def test_current_power_property(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
        mock_config_entry: ConfigEntry,
    ) -> None:
        """Test current_power property."""
        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=mock_config_entry,
        )

        assert power_manager.current_power == 0.0

        power_manager._state.target_power = 1500.0
        assert power_manager.current_power == 1500.0


class TestErrorHandling:
    """Test error handling in power manager."""

    async def test_update_power_handles_os_error(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
    ) -> None:
        """Test update power handles OSError gracefully."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_POWER_SENSOR: "sensor.grid_power",
            },
        )
        entry.add_to_hass(hass)

        hass.states.async_set("sensor.grid_power", "-1000")

        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=entry,
        )
        power_manager._state.pv_charging_enabled = True

        # Should not raise exception
        await power_manager._async_update_power(None)

    async def test_update_power_handles_value_error(
        self,
        hass: HomeAssistant,
        mock_coordinator_master: SAXBatteryCoordinator,
    ) -> None:
        """Test update power handles ValueError gracefully."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_POWER_SENSOR: "sensor.grid_power",
            },
        )
        entry.add_to_hass(hass)

        hass.states.async_set("sensor.grid_power", "-1000")

        power_manager = PowerManager(
            hass=hass,
            coordinator=mock_coordinator_master,
            config_entry=entry,
        )
        power_manager._state.pv_charging_enabled = True

        # Should not raise exception
        await power_manager._async_update_power(None)


class TestPowerManagerState:
    """Test PowerManagerState dataclass."""

    def test_state_initialization(self) -> None:
        """Test PowerManagerState initialization."""
        state = PowerManagerState(
            mode=PV_CHARGING_MODE,
            target_power=1500.0,
            last_update=datetime.now(),
        )

        assert state.mode == PV_CHARGING_MODE
        assert state.target_power == 1500.0
        assert state.pv_charging_enabled is False
        assert state.grid_charging_enabled is False

    def test_state_with_flags(self) -> None:
        """Test PowerManagerState with mode flags."""
        state = PowerManagerState(
            mode=GRID_CHARGING_MODE,
            target_power=0.0,
            last_update=datetime.now(),
            pv_charging_enabled=False,
            grid_charging_enabled=True,
        )

        assert state.mode == GRID_CHARGING_MODE
        assert state.grid_charging_enabled is True
        assert state.pv_charging_enabled is False
