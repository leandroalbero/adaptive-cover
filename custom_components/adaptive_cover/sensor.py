"""Sensor platform for Adaptive Cover integration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import pandas as pd
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .calculation import AdaptiveVerticalCover, AdaptiveHorizontalCover, AdaptiveTiltCover, NormalCoverState
from .const import (
    CONF_SENSOR_TYPE,
    DOMAIN, _LOGGER,
)
from .coordinator import AdaptiveDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Adaptive Cover config entry."""

    name = config_entry.data["name"]
    coordinator: AdaptiveDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    sensor = AdaptiveCoverSensorEntity(
        config_entry.entry_id, hass, config_entry, name, coordinator
    )
    start = AdaptiveCoverTimeSensorEntity(
        config_entry.entry_id,
        hass,
        config_entry,
        name,
        "Start Sun",
        "start",
        "mdi:sun-clock-outline",
        coordinator,
    )
    end = AdaptiveCoverTimeSensorEntity(
        config_entry.entry_id,
        hass,
        config_entry,
        name,
        "End Sun",
        "end",
        "mdi:sun-clock",
        coordinator,
    )
    control = AdaptiveCoverControlSensorEntity(
        config_entry.entry_id, hass, config_entry, name, coordinator
    )
    forecast = AdaptiveCoverForecastSensor(
        config_entry.entry_id,
        hass,
        config_entry,
        name,
        coordinator
    )

    async_add_entities([sensor, start, end, control, forecast])


class AdaptiveCoverSensorEntity(
    CoordinatorEntity[AdaptiveDataUpdateCoordinator], SensorEntity
):
    """Adaptive Cover Sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:sun-compass"
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        hass,
        config_entry,
        name: str,
        coordinator: AdaptiveDataUpdateCoordinator,
    ) -> None:
        """Initialize adaptive_cover Sensor."""
        super().__init__(coordinator=coordinator)
        self.type = {
            "cover_blind": "Vertical",
            "cover_awning": "Horizontal",
            "cover_tilt": "Tilt",
        }
        self.coordinator = coordinator
        self.data = self.coordinator.data
        self._sensor_name = "Cover Position"
        self._attr_unique_id = f"{unique_id}_{self._sensor_name}"
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._device_name = self.type[self.config_entry.data[CONF_SENSOR_TYPE]]
        self._device_id = unique_id

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.data = self.coordinator.data
        self.async_write_ha_state()

    @property
    def name(self):
        """Name of the entity."""
        return f"{self._sensor_name} {self._name}"

    @property
    def native_value(self) -> str | None:
        """Handle when entity is added."""
        return self.data.states["state"]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
        )

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:  # noqa: D102
        return self.data.attributes


class AdaptiveCoverTimeSensorEntity(
    CoordinatorEntity[AdaptiveDataUpdateCoordinator], SensorEntity
):
    """Adaptive Cover Time Sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        hass,
        config_entry,
        name: str,
        sensor_name: str,
        key: str,
        icon: str,
        coordinator: AdaptiveDataUpdateCoordinator,
    ) -> None:
        """Initialize adaptive_cover Sensor."""
        super().__init__(coordinator=coordinator)
        self.type = {
            "cover_blind": "Vertical",
            "cover_awning": "Horizontal",
            "cover_tilt": "Tilt",
        }
        self._attr_icon = icon
        self.key = key
        self.coordinator = coordinator
        self.data = self.coordinator.data
        self._attr_unique_id = f"{unique_id}_{sensor_name}"
        self._device_id = unique_id
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._cover_type = self.config_entry.data["sensor_type"]
        self._sensor_name = sensor_name
        self._device_name = self.type[config_entry.data[CONF_SENSOR_TYPE]]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.data = self.coordinator.data
        self.async_write_ha_state()

    @property
    def name(self):
        """Name of the entity."""
        return f"{self._sensor_name} {self._name}"

    @property
    def native_value(self) -> str | None:
        """Handle when entity is added."""
        return self.data.states[self.key]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
        )


class AdaptiveCoverControlSensorEntity(
    CoordinatorEntity[AdaptiveDataUpdateCoordinator], SensorEntity
):
    """Adaptive Cover Control method Sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "control"

    def __init__(
        self,
        unique_id: str,
        hass,
        config_entry,
        name: str,
        coordinator: AdaptiveDataUpdateCoordinator,
    ) -> None:
        """Initialize adaptive_cover Sensor."""
        super().__init__(coordinator=coordinator)
        self.type = {
            "cover_blind": "Vertical",
            "cover_awning": "Horizontal",
            "cover_tilt": "Tilt",
        }
        self.coordinator = coordinator
        self.data = self.coordinator.data
        self._sensor_name = "Control Method"
        self._attr_unique_id = f"{unique_id}_{self._sensor_name}"
        self._device_id = unique_id
        self.id = unique_id
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._cover_type = self.config_entry.data["sensor_type"]
        self._device_name = self.type[config_entry.data[CONF_SENSOR_TYPE]]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.data = self.coordinator.data
        self.async_write_ha_state()

    @property
    def name(self):
        """Name of the entity."""
        return f"{self._sensor_name} {self._name}"

    @property
    def native_value(self) -> str | None:
        """Handle when entity is added."""
        return self.data.states["control"]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
        )


class AdaptiveCoverForecastSensor(AdaptiveCoverSensorEntity):
    """Forecast sensor for Adaptive Cover."""

    _attr_icon = "mdi:chart-line"

    def __init__(
            self,
            unique_id: str,
            hass,
            config_entry,
            name: str,
            coordinator: AdaptiveDataUpdateCoordinator,
    ) -> None:
        """Initialize forecast sensor."""
        super().__init__(unique_id, hass, config_entry, name, coordinator)
        self._sensor_name = "Cover Forecast"
        self._attr_unique_id = f"{unique_id}_forecast"
        self._cover_type = config_entry.data.get(CONF_SENSOR_TYPE)
        self._forecast_data = None
        self._last_forecast = None

    def _generate_forecast(self) -> list:
        """Generate 24h forecast data with caching."""
        now = dt_util.utcnow()

        # Return cached data if less than 5 minutes old
        if (self._last_forecast and self._forecast_data and
                now - self._last_forecast < timedelta(minutes=5)):
            return self._forecast_data

        _LOGGER.debug("Generating new forecast data")

        try:
            # Get calculation class based on cover type
            cover_data = self._get_cover_calculator()
            if not cover_data:
                return []

            # Generate forecast points every 30 minutes instead of every 5
            times = pd.date_range(
                start=now,
                end=now + timedelta(hours=24),
                freq="30min",
                tz=dt_util.DEFAULT_TIME_ZONE
            )

            forecast = []

            for time in times:
                # Calculate sun position
                solar_azi = cover_data.sun_data.location.solar_azimuth(
                    time, cover_data.sun_data.elevation)
                solar_elev = cover_data.sun_data.location.solar_elevation(
                    time, cover_data.sun_data.elevation)

                # Update cover calculator with new sun position
                cover_data.sol_azi = solar_azi
                cover_data.sol_elev = solar_elev

                # Calculate position
                normal_state = NormalCoverState(cover_data)
                position = normal_state.get_state()

                # Add data point
                forecast.append({
                    "time": time.isoformat(),
                    "position": float(position),
                    "elevation": float(solar_elev),
                    "azimuth": float(solar_azi)
                })

            self._forecast_data = forecast
            self._last_forecast = now
            return forecast

        except Exception as err:
            _LOGGER.error("Error generating forecast: %s", err)
            return []

    def _get_cover_calculator(self):
        """Get the appropriate cover calculator."""
        try:
            options = self.config_entry.options
            if self._cover_type == "cover_blind":
                return AdaptiveVerticalCover(
                    self.hass,
                    *self.coordinator.pos_sun,
                    *self.coordinator.common_data(options),
                    *self.coordinator.vertical_data(options),
                )
            elif self._cover_type == "cover_awning":
                return AdaptiveHorizontalCover(
                    self.hass,
                    *self.coordinator.pos_sun,
                    *self.coordinator.common_data(options),
                    *self.coordinator.vertical_data(options),
                    *self.coordinator.horizontal_data(options),
                )
            elif self._cover_type == "cover_tilt":
                return AdaptiveTiltCover(
                    self.hass,
                    *self.coordinator.pos_sun,
                    *self.coordinator.common_data(options),
                    *self.coordinator.tilt_data(options),
                )
        except Exception as err:
            _LOGGER.error("Error creating cover calculator: %s", err)
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return forecast data in attributes."""
        attributes = super().extra_state_attributes or {}
        attributes["forecast"] = self._generate_forecast()
        return attributes

    @property
    def native_value(self) -> str | None:
        """Return the current forecast position."""
        forecast = self._generate_forecast()
        if forecast:
            return forecast[0]["position"]
        return None