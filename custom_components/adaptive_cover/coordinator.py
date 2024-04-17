"""The Coordinator for Adaptive Cover."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SERVICE_SET_COVER_POSITION,
    SERVICE_SET_COVER_TILT_POSITION,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.template import state_attr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .calculation import (
    AdaptiveDoubleRollerCover,
    AdaptiveHorizontalCover,
    AdaptiveTiltCover,
    AdaptiveVerticalCover,
    ClimateCoverData,
    ClimateCoverState,
    NormalCoverState,
)
from .const import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CONF_AWNING_ANGLE,
    CONF_AZIMUTH,
    CONF_CLIMATE_MODE,
    CONF_DEFAULT_HEIGHT,
    CONF_DELTA_POSITION,
    CONF_DELTA_TIME,
    CONF_DISTANCE,
    CONF_DOUBLE_ROLLER,
    CONF_ENTITIES,
    CONF_FOV_LEFT,
    CONF_FOV_RIGHT,
    CONF_HEIGHT_WIN,
    CONF_INVERSE_STATE,
    CONF_LENGTH_AWNING,
    CONF_MANUAL_OVERRIDE_DURATION,
    CONF_MANUAL_OVERRIDE_RESET,
    CONF_MAX_POSITION,
    CONF_OUTSIDETEMP_ENTITY,
    CONF_PRESENCE_ENTITY,
    CONF_START_ENTITY,
    CONF_START_TIME,
    CONF_SUNRISE_OFFSET,
    CONF_SUNSET_OFFSET,
    CONF_SUNSET_POS,
    CONF_TEMP_ENTITY,
    CONF_TEMP_HIGH,
    CONF_TEMP_LOW,
    CONF_TILT_DEPTH,
    CONF_TILT_DISTANCE,
    CONF_TILT_MODE,
    CONF_WEATHER_ENTITY,
    CONF_WEATHER_STATE,
    DOMAIN,
    LOGGER,
)
from .helpers import get_datetime_from_state, get_last_updated, get_safe_state, get_time

_LOGGER = logging.getLogger(__name__)


@dataclass
class StateChangedData:
    """StateChangedData class."""

    entity_id: str
    old_state: State | None
    new_state: State | None


@dataclass
class AdaptiveCoverData:
    """AdaptiveCoverData class."""

    climate_mode_toggle: bool
    states: dict
    attributes: dict


class AdaptiveDataUpdateCoordinator(DataUpdateCoordinator[AdaptiveCoverData]):
    """Adaptive cover data update coordinator."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant) -> None:  # noqa: D107
        super().__init__(hass, LOGGER, name=DOMAIN)

        self._cover_type = self.config_entry.data.get("sensor_type")
        self._climate_mode = self.config_entry.options.get(CONF_CLIMATE_MODE, False)
        self._switch_mode = True if self._climate_mode else False
        self._inverse_state = self.config_entry.options.get(CONF_INVERSE_STATE, False)
        self._temp_toggle = False
        self._control_toggle = True
        self._double_toggle = self.config_entry.options.get(CONF_DOUBLE_ROLLER, True)
        self.manual_duration = self.config_entry.options.get(
            CONF_MANUAL_OVERRIDE_DURATION, {"minutes": 15}
        )
        self.cover_state_change = False
        self.state_change_data: StateChangedData | None = None
        self.manager = AdaptiveCoverManager(self.manual_duration)
        self.wait_for_target = {}
        self.target_call = {}

    async def async_config_entry_first_refresh(self):
        """Call the first update from config_entry."""
        await super().async_config_entry_first_refresh()
        if self._control_toggle:
            for cover in self.entities:
                await self.async_set_position(cover)

    async def async_check_entity_state_change(
        self, entity: str, old_state: State | None, new_state: State | None
    ) -> None:
        """Fetch and process state change event."""
        # self.state_change = True
        await self.async_refresh()

    async def async_check_cover_state_change(
        self, entity: str, old_state: State | None, new_state: State | None
    ) -> None:
        """Fetch and process state change event."""
        self.state_change_data = StateChangedData(entity, old_state, new_state)
        self.cover_state_change = True
        self.process_entity_state_change()
        await self.async_refresh()

    def process_entity_state_change(self):
        """Process state change event."""
        event = self.state_change_data
        _LOGGER.debug("Processing state change event: %s", event)
        entity_id = event.entity_id
        if self.wait_for_target.get(entity_id):
            current_position = event.new_state.attributes.get("current_position")
            if self._cover_type in ["cover_tilt", "cover_double_roller"]:
                current_tilt_position = event.new_state.attributes.get(
                    "current_tilt_position"
                )

            if self._cover_type == "cover_double_roller":
                cond_1 = current_tilt_position == self.target_call[entity_id].get(
                    "tilt"
                )
                if self.double_toggle:
                    cond_2 = current_position == self.target_call[entity_id].get(
                        "normal"
                    )
                    if current_tilt_position == cond_1 and current_position == cond_2:
                        self.wait_for_target[entity_id] = False
                        _LOGGER.debug(
                            "Positions tilt: %s and normal: %s  reached for %s",
                            current_tilt_position,
                            current_position,
                            entity_id,
                        )
                if cond_1:
                    self.wait_for_target[entity_id] = False
                    _LOGGER.debug(
                        "Position tilt: %s reached for %s",
                        current_tilt_position,
                        entity_id,
                    )
            if self._cover_type == "cover_tilt":
                if current_tilt_position == self.target_call.get(entity_id).get("tilt"):
                    self.wait_for_target[entity_id] = False
                    _LOGGER.debug(
                        "Position tilt: %s reached for %s",
                        current_tilt_position,
                        entity_id,
                    )
            else:
                if current_position == self.target_call.get(entity_id).get("normal"):
                    self.wait_for_target[entity_id] = False
                    _LOGGER.debug(
                        "Position normal: %s reached for %s",
                        current_position,
                        entity_id,
                    )
            _LOGGER.debug("Wait for target: %s", self.wait_for_target)

    async def _async_update_data(self) -> AdaptiveCoverData:
        self.entities = self.config_entry.options.get(CONF_ENTITIES, [])
        self.min_change = self.config_entry.options.get(CONF_DELTA_POSITION, 1)
        self.time_threshold = self.config_entry.options.get(CONF_DELTA_TIME, 2)
        self.start_time = self.config_entry.options.get(CONF_START_TIME)
        self.start_time_entity = self.config_entry.options.get(CONF_START_ENTITY)
        self.manual_reset = self.config_entry.options.get(
            CONF_MANUAL_OVERRIDE_RESET, False
        )
        self.manual_duration = self.config_entry.options.get(
            CONF_MANUAL_OVERRIDE_DURATION, {"minutes": 15}
        )

        self.manager.add_covers(self.entities)

        control_method = "intermediate"
        self.climate_state = None

        if self._climate_mode:
            climate_data_var = [
                self.hass,
                self.config_entry.options.get(CONF_TEMP_ENTITY),
                self.config_entry.options.get(CONF_TEMP_LOW),
                self.config_entry.options.get(CONF_TEMP_HIGH),
                self.config_entry.options.get(CONF_PRESENCE_ENTITY),
                self.config_entry.options.get(CONF_WEATHER_ENTITY),
                self.config_entry.options.get(CONF_WEATHER_STATE),
                self.config_entry.options.get(CONF_OUTSIDETEMP_ENTITY),
                self._temp_toggle,
                self._cover_type,
            ]
            climate = ClimateCoverData(*climate_data_var)
            self.climate_state = round(
                ClimateCoverState(self.get_blind_data(), climate).get_state()
            )
            climate_data = ClimateCoverState(
                self.get_blind_data(), climate
            ).climate_data
            if climate_data.is_summer and self.switch_mode:
                control_method = "summer"
            if climate_data.is_winter and self.switch_mode:
                control_method = "winter"

        self.default_state = round(NormalCoverState(self.get_blind_data()).get_state())

        if self.cover_state_change:
            self.manager.handle_state_change(
                self.state_change_data,
                self.state,
                self._cover_type,
                self.manual_reset,
                self.wait_for_target,
                self._double_toggle,
                self.slat_state,
            )
            self.cover_state_change = False  # reset state change
        await self.manager.reset_if_needed()

        if self.control_toggle:
            for cover in self.entities:
                if not self.manager.is_cover_manual(cover):
                    await self.async_handle_call_service(cover)

        return AdaptiveCoverData(
            climate_mode_toggle=self.switch_mode,
            states={
                "state": self.state,
                "double_state": self.slat_state
                if self._cover_type == "cover_double_roller"
                else None,
                "start": NormalCoverState(self.get_blind_data()).cover.solar_times()[0],
                "end": NormalCoverState(self.get_blind_data()).cover.solar_times()[1],
                "control": control_method,
                "sun_motion": NormalCoverState(self.get_blind_data()).cover.valid,
                "manual_override": self.manager.binary_cover_manual,
                "manual_list": self.manager.manual_controlled,
            },
            attributes={
                "default": self.config_entry.options.get(CONF_DEFAULT_HEIGHT),
                "sunset_default": self.config_entry.options.get(CONF_SUNSET_POS),
                "sunset_offset": self.config_entry.options.get(CONF_SUNSET_OFFSET),
                "azimuth_window": self.config_entry.options.get(CONF_AZIMUTH),
                "field_of_view": [
                    self.config_entry.options.get(CONF_FOV_LEFT),
                    self.config_entry.options.get(CONF_FOV_RIGHT),
                ],
                "wait_for_target": self.wait_for_target,
                "target_call": self.target_call,
                "manual": self.manager.manual_control,
            },
        )

    async def async_handle_call_service(self, entity):
        """Handle call service."""
        if (
            self.check_position(entity)
            and self.check_time_delta(entity)
            and self.after_start_time
        ):
            await self.async_set_position(entity)

    # This method calls the service to set the cover position.
    # The service called depends on the type of cover.

    async def async_set_position(self, entity: str) -> None:
        """Call service to set cover position based on cover type."""
        service = SERVICE_SET_COVER_POSITION
        service_tilt = SERVICE_SET_COVER_TILT_POSITION
        service_data = {"entity_id": entity}
        service_data_tilt = {"entity_id": entity}
        self.target_call[entity] = {}

        # Double roller cover.
        if self._cover_type == "cover_double_roller":
            self.wait_for_target[entity] = True
            self.target_call[entity]["tilt"] = self.slat_state
            service_data_tilt[ATTR_TILT_POSITION] = self.slat_state
            await self.hass.services.async_call(
                COVER_DOMAIN, service_tilt, service_data_tilt
            )
            _LOGGER.debug("Setting for %s slat to %s", entity, self.slat_state)
            if self.double_toggle:
                self.target_call[entity]["normal"] = self.state
                service_data[ATTR_POSITION] = self.state
                await self.hass.services.async_call(COVER_DOMAIN, service, service_data)
                _LOGGER.debug("Setting for %s cover to %s", entity, self.state)

        # Tilt only cover.
        elif self._cover_type == "cover_tilt":
            self.wait_for_target[entity] = True
            self.target_call[entity]["tilt"] = self.state
            service_data_tilt[ATTR_TILT_POSITION] = self.state
            await self.hass.services.async_call(
                COVER_DOMAIN, service_tilt, service_data_tilt
            )
            _LOGGER.debug("Setting for %s tilt to %s", entity, self.state)

        # Normal cover.
        else:
            self.wait_for_target[entity] = True
            self.target_call[entity]["normal"] = self.state
            service_data[ATTR_POSITION] = self.state
            await self.hass.services.async_call(COVER_DOMAIN, service, service_data)
            _LOGGER.debug("Setting for %s cover to %s", entity, self.state)

    def get_blind_data(self):
        """Assign correct class for type of blind."""
        if self._cover_type == "cover_blind":
            cover_data = AdaptiveVerticalCover(
                self.hass, *self.pos_sun, *self.common_data, *self.vertical_data
            )
        if self._cover_type == "cover_awning":
            cover_data = AdaptiveHorizontalCover(
                self.hass,
                *self.pos_sun,
                *self.common_data,
                *self.vertical_data,
                *self.horizontal_data,
            )
        if self._cover_type == "cover_tilt":
            cover_data = AdaptiveTiltCover(
                self.hass, *self.pos_sun, *self.common_data, *self.tilt_data
            )
        if self._cover_type == "cover_double_roller":
            cover_data = AdaptiveDoubleRollerCover(
                self.hass, *self.pos_sun, *self.common_data, *self.vertical_data
            )
        return cover_data

    @property
    def after_start_time(self):
        """Check if time is after start time."""
        if self.start_time_entity is not None:
            time = get_datetime_from_state(get_safe_state(self.start_time_entity))
            now = dt.datetime.now(dt.UTC)
            if now.date() == time.date():
                return now >= time
        if self.start_time is not None:
            time = get_time(self.start_time).time()
            now = dt.datetime.now().time()
            return now >= time
        return True

    def check_position(self, entity):
        """Check cover positions to reduce calls."""
        current_position = state_attr(self.hass, entity, "current_position")
        if self._cover_type in ["cover_tilt", "cover_double_roller"]:
            current_position = state_attr(self.hass, entity, "current_tilt_position")

        if current_position is not None:
            condition = abs(current_position - self.state) >= self.min_change
            if self._cover_type == "cover_double_roller" and self._double_toggle:
                return (
                    condition
                    or abs(
                        state_attr(self.hass, entity, "current_position")
                        - self.slat_state
                    )
                    >= self.min_change
                )
            return condition

    def check_time_delta(self, entity):
        """Check if time delta is passed."""
        now = dt.datetime.now(dt.UTC)
        last_updated = get_last_updated(entity, self.hass)
        if last_updated is not None:
            return now - last_updated >= dt.timedelta(minutes=self.time_threshold)
        return True

    @property
    def pos_sun(self):
        """Fetch information for sun position."""
        return [
            state_attr(self.hass, "sun.sun", "azimuth"),
            state_attr(self.hass, "sun.sun", "elevation"),
        ]

    @property
    def common_data(self):
        """Update shared parameters."""
        return [
            self.config_entry.options.get(CONF_SUNSET_POS),
            self.config_entry.options.get(CONF_SUNSET_OFFSET),
            self.config_entry.options.get(
                CONF_SUNRISE_OFFSET, self.config_entry.options.get(CONF_SUNSET_OFFSET)
            ),
            self.hass.config.time_zone,
            self.config_entry.options.get(CONF_FOV_LEFT),
            self.config_entry.options.get(CONF_FOV_RIGHT),
            self.config_entry.options.get(CONF_AZIMUTH),
            self.config_entry.options.get(CONF_DEFAULT_HEIGHT),
            self.config_entry.options.get(CONF_MAX_POSITION, 100),
        ]

    @property
    def vertical_data(self):
        """Update data for vertical blinds."""
        return [
            self.config_entry.options.get(CONF_DISTANCE),
            self.config_entry.options.get(CONF_HEIGHT_WIN),
        ]

    @property
    def horizontal_data(self):
        """Update data for horizontal blinds."""
        return [
            self.config_entry.options.get(CONF_LENGTH_AWNING),
            self.config_entry.options.get(CONF_AWNING_ANGLE),
        ]

    @property
    def tilt_data(self):
        """Update data for tilted blinds."""
        return [
            self.config_entry.options.get(CONF_TILT_DISTANCE),
            self.config_entry.options.get(CONF_TILT_DEPTH),
            self.config_entry.options.get(CONF_TILT_MODE),
        ]

    @property
    def state(self):
        """Handle the output of the state based on mode."""
        state = self.default_state
        if self._switch_mode:
            state = self.climate_state
        if self._inverse_state:
            state = 100 - state
        return state

    @property
    def slat_state(self):
        """Return the current sun percentage of the double roller."""
        if self._cover_type != "cover_double_roller":
            return None

        blind_data = self.get_blind_data()
        sun_percentage = NormalCoverState(blind_data).cover.calc_sun_percentage()

        if self._inverse_state:
            sun_percentage = 100 - sun_percentage

        return sun_percentage

    @property
    def switch_mode(self):
        """Let switch toggle climate mode."""
        return self._switch_mode

    @switch_mode.setter
    def switch_mode(self, value):
        self._switch_mode = value

    @property
    def temp_toggle(self):
        """Let switch toggle between inside or outside temperature."""
        return self._temp_toggle

    @temp_toggle.setter
    def temp_toggle(self, value):
        self._temp_toggle = value

    @property
    def control_toggle(self):
        """Toggle automation."""
        return self._control_toggle

    @control_toggle.setter
    def control_toggle(self, value):
        self._control_toggle = value

    @property
    def double_toggle(self):
        """Toggle automation."""
        return self._double_toggle

    @double_toggle.setter
    def double_toggle(self, value):
        self._double_toggle = value


class AdaptiveCoverManager:
    """Track position changes."""

    def __init__(self, reset_duration: dict[str:int]) -> None:
        """Initialize the AdaptiveCoverManager."""
        self.covers: set[str] = set()

        self.manual_control: dict[str, bool] = {}
        self.manual_control_time: dict[str, dt.datetime] = {}
        self.reset_duration = dt.timedelta(**reset_duration)

    def add_covers(self, entity):
        """Update set with entities."""
        self.covers.update(entity)

    def handle_state_change(
        self,
        states_data,
        our_state,
        blind_type,
        allow_reset,
        wait_target_call,
        double_toggle,
        slat_state,
    ):
        """Process state change event."""
        event = states_data
        if event is None:
            return
        entity_id = event.entity_id
        if entity_id not in self.covers:
            return
        if wait_target_call[entity_id]:
            return

        new_state = event.new_state

        new_position = new_state.attributes.get("current_position")
        second_position = new_state.attributes.get("current_position")
        if blind_type in ["cover_tilt", "cover_double_roller"]:
            new_position = new_state.attributes.get("current_tilt_position")

        state = our_state if blind_type != "cover_double_roller" else slat_state
        second_state = our_state if blind_type == "cover_double_roller" else 101
        if new_position != state:
            _LOGGER.debug(
                "Set manual control for %s, for at least %s seconds, reset_allowed: %s",
                entity_id,
                self.reset_duration.total_seconds(),
                allow_reset,
            )
            self.mark_manual_control(entity_id)
            self.set_last_updated(entity_id, new_state, allow_reset)
        if double_toggle and (
            new_position == state and second_position != second_state
        ):
            _LOGGER.debug(
                "Set manual control for %s, for at least %s seconds, reset_allowed: %s",
                entity_id,
                self.reset_duration.total_seconds(),
                allow_reset,
            )
            self.mark_manual_control(entity_id)
            self.set_last_updated(entity_id, new_state, allow_reset)

    def set_last_updated(self, entity_id, new_state, allow_reset):
        """Set last updated time for manual control."""
        if entity_id not in self.manual_control_time or allow_reset:
            last_updated = new_state.last_updated
            self.manual_control_time[entity_id] = last_updated
            _LOGGER.debug(
                "Updating last updated to %s for %s. Allow reset:%s",
                last_updated,
                entity_id,
                allow_reset,
            )
        elif not allow_reset:
            _LOGGER.debug(
                "Already time specified for %s, reset is not allowed by user setting:%s",
                entity_id,
                allow_reset,
            )

    def mark_manual_control(self, cover: str) -> None:
        """Mark cover as under manual control."""
        self.manual_control[cover] = True

    async def reset_if_needed(self):
        """Reset manual control state of the covers."""
        current_time = dt.datetime.now(dt.UTC)
        manual_control_time_copy = dict(self.manual_control_time)
        for entity_id, last_updated in manual_control_time_copy.items():
            if current_time - last_updated > self.reset_duration:
                _LOGGER.debug(
                    "Resetting manual override for %s, because duration has elapsed",
                    entity_id,
                )
                self.reset(entity_id)

    def reset(self, entity_id):
        """Reset manual control for a cover."""
        self.manual_control[entity_id] = False
        self.manual_control_time.pop(entity_id, None)
        _LOGGER.debug("Reset manual override for %s", entity_id)

    def is_cover_manual(self, entity_id):
        """Check if a cover is under manual control."""
        return self.manual_control.get(entity_id, False)

    @property
    def binary_cover_manual(self):
        """Check if any cover is under manual control."""
        return any(value for value in self.manual_control.values())

    @property
    def manual_controlled(self):
        """Get the list of covers under manual control."""
        return [k for k, v in self.manual_control.items() if v]
