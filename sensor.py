"""WeatherKit sensors."""

from apple_weatherkit import DataSetType

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolumetricFlux
from homeassistant.core import HomeAssistant
from homeassistant.helpers import translation
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_CURRENT_WEATHER, ATTR_FORECAST_NEXT_HOUR, DOMAIN, LOGGER
from .coordinator import WeatherKitDataUpdateCoordinator
from .entity import WeatherKitEntity

SENSORS = (
    SensorEntityDescription(
        key="precipitationIntensity",
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
    ),
    SensorEntityDescription(
        key="pressureTrend",
        device_class=SensorDeviceClass.ENUM,
        options=["rising", "falling", "steady"],
        translation_key="pressure_trend",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add sensor entities from a config_entry."""
    coordinator: WeatherKitDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    entities = [WeatherKitSensor(coordinator, description) for description in SENSORS]

    # Add NextHourForecast sensor if the data set is supported
    if (
        coordinator.supported_data_sets
        and DataSetType.NEXT_HOUR_FORECAST in coordinator.supported_data_sets
    ):
        entities.append(WeatherKitNextHourForecastSensor(coordinator))

    async_add_entities(entities)


class WeatherKitSensor(
    CoordinatorEntity[WeatherKitDataUpdateCoordinator], WeatherKitEntity, SensorEntity
):
    """WeatherKit sensor entity."""

    def __init__(
        self,
        coordinator: WeatherKitDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        WeatherKitEntity.__init__(
            self, coordinator, unique_id_suffix=entity_description.key
        )
        self.entity_description = entity_description

    @property
    def native_value(self) -> StateType:
        """Return native value from coordinator current weather."""
        return self.coordinator.data[ATTR_CURRENT_WEATHER][self.entity_description.key]


class WeatherKitNextHourForecastSensor(
    CoordinatorEntity[WeatherKitDataUpdateCoordinator], WeatherKitEntity, SensorEntity
):
    """WeatherKit NextHourForecast sensor entity."""

    _attr_translation_key = "next_hour_forecast"

    def __init__(
        self,
        coordinator: WeatherKitDataUpdateCoordinator,
    ) -> None:
        """Initialize the NextHourForecast sensor."""
        super().__init__(coordinator)
        WeatherKitEntity.__init__(
            self, coordinator, unique_id_suffix="next_hour_forecast"
        )

    @property
    def native_value(self) -> StateType:
        """Return a human-readable forecast summary."""
        if not self.coordinator.last_update_success:
            # Coordinator update failed, sensor should be unavailable
            return None

        if not self.coordinator.data:
            # No data available yet
            return None

        if ATTR_FORECAST_NEXT_HOUR not in self.coordinator.data:
            # Log a warning if data set is supported but data is missing
            if (
                self.coordinator.supported_data_sets
                and DataSetType.NEXT_HOUR_FORECAST
                in self.coordinator.supported_data_sets
            ):
                LOGGER.warning(
                    "Next hour forecast data set is supported but not in API response"
                )
            return None

        next_hour_data = self.coordinator.data[ATTR_FORECAST_NEXT_HOUR]
        if not next_hour_data:
            return self._translate_state("no_precipitation")

        minutes = next_hour_data.get("minutes", [])

        if not minutes:
            return self._translate_state("no_precipitation")

        # Only consider the next 60 minutes, even if API returns more
        minutes = minutes[:60]

        return self._generate_forecast_summary(minutes)

    def _generate_forecast_summary(self, minutes: list[dict]) -> str:
        """Generate a human-readable forecast summary from minute-by-minute data."""
        # Find when precipitation starts and stops
        precipitation_periods = []
        current_period_start = None
        current_period_type = None
        current_period_max_intensity = 0.0

        for i, minute in enumerate(minutes):
            intensity = minute.get("precipitationIntensity", 0.0)
            precip_type = minute.get("precipitationType", "clear")

            # Check if precipitation is starting
            if intensity > 0.0 and current_period_start is None:
                current_period_start = i
                current_period_type = precip_type
                current_period_max_intensity = intensity
            # Check if precipitation continues
            elif intensity > 0.0 and current_period_start is not None:
                current_period_max_intensity = max(
                    current_period_max_intensity, intensity
                )
                if precip_type != "clear":
                    current_period_type = precip_type
            # Check if precipitation stops
            elif intensity == 0.0 and current_period_start is not None:
                precipitation_periods.append(
                    {
                        "start": current_period_start,
                        "end": i - 1,
                        "type": current_period_type,
                        "max_intensity": current_period_max_intensity,
                    }
                )
                current_period_start = None
                current_period_type = None
                current_period_max_intensity = 0.0

        # Handle case where precipitation continues to the end
        if current_period_start is not None:
            precipitation_periods.append(
                {
                    "start": current_period_start,
                    "end": len(minutes) - 1,
                    "type": current_period_type,
                    "max_intensity": current_period_max_intensity,
                }
            )

        # Generate summary text
        if not precipitation_periods:
            return self._translate_state("no_precipitation")

        summary_parts = []
        for period in precipitation_periods:
            start_minute = period["start"]
            end_minute = period["end"]
            duration = end_minute - start_minute + 1
            precip_type = period["type"]
            max_intensity = period["max_intensity"]

            # Get translated precipitation description
            precip_desc_key = self._get_precipitation_description_key(
                precip_type, max_intensity
            )
            precip_desc = self._translate_state(precip_desc_key)

            # Build the description using translations
            if start_minute == 0:
                if duration == 1:
                    summary_parts.append(
                        self._translate_forecast("now", {"precipitation": precip_desc})
                    )
                else:
                    summary_parts.append(
                        self._translate_forecast(
                            "for_next_minutes",
                            {"precipitation": precip_desc, "duration": str(duration)},
                        )
                    )
            elif duration == 1:
                summary_parts.append(
                    self._translate_forecast(
                        "in_minutes",
                        {
                            "precipitation": precip_desc,
                            "minutes": str(start_minute),
                        },
                    )
                )
            else:
                summary_parts.append(
                    self._translate_forecast(
                        "starting_in_minutes_lasting",
                        {
                            "precipitation": precip_desc,
                            "start_minutes": str(start_minute),
                            "duration": str(duration),
                        },
                    )
                )

        return (
            "; ".join(summary_parts)
            if summary_parts
            else self._translate_state("no_precipitation")
        )

    def _get_precipitation_description_key(
        self, precip_type: str, max_intensity: float
    ) -> str:
        """Get the translation key for precipitation description."""
        # Determine intensity prefix
        if max_intensity < 2.5:
            intensity_prefix = "light_"
        elif max_intensity < 10.0:
            intensity_prefix = "moderate_"
        else:
            intensity_prefix = "heavy_"

        # Map precipitation type to translation key
        if precip_type == "rain":
            return f"{intensity_prefix}rain"
        if precip_type == "snow":
            return f"{intensity_prefix}snow"
        if precip_type == "sleet":
            return f"{intensity_prefix}sleet"
        if precip_type == "hail":
            return f"{intensity_prefix}hail"
        return f"{intensity_prefix}precipitation"

    def _translate_state(self, state_key: str) -> str:
        """Translate a state key."""
        translations = translation.async_get_cached_translations(
            self.hass, self.hass.config.language, "entity", DOMAIN
        )
        translation_key = (
            f"component.{DOMAIN}.entity.sensor.next_hour_forecast.state.{state_key}"
        )
        return translations.get(translation_key, state_key.replace("_", " ").title())

    def _translate_forecast(self, key: str, placeholders: dict[str, str]) -> str:
        """Translate a forecast pattern with placeholders."""
        # Templates from strings.json - use these directly to ensure placeholders work
        templates = {
            "now": "{precipitation} now",
            "for_next_minutes": "{precipitation} for the next {duration} minutes",
            "in_minutes": "{precipitation} in {minutes} minutes",
            "starting_in_minutes_lasting": "{precipitation} starting in {start_minutes} minutes, lasting {duration} minutes",
        }

        template = templates.get(key, key.replace("_", " "))

        try:
            return template.format(**placeholders)
        except (KeyError, ValueError) as e:
            LOGGER.warning(
                "Failed to format forecast template '%s' with placeholders %s: %s",
                key,
                placeholders,
                e,
            )
            return template

    @property
    def icon(self) -> str | None:
        """Return the icon based on the forecast."""
        if (
            not self.coordinator.data
            or ATTR_FORECAST_NEXT_HOUR not in self.coordinator.data
        ):
            return "mdi:weather-partly-cloudy"

        # Check if it's currently daylight or nighttime
        current_weather = self.coordinator.data.get(ATTR_CURRENT_WEATHER, {})
        is_daylight = current_weather.get("daylight", True)

        next_hour_data = self.coordinator.data[ATTR_FORECAST_NEXT_HOUR]
        minutes = next_hour_data.get("minutes", [])

        if not minutes:
            # No precipitation expected - use day/night appropriate icon
            return "mdi:weather-sunny" if is_daylight else "mdi:weather-night"

        # Use the same logic as _generate_forecast_summary to find precipitation periods
        precipitation_periods = []
        current_period_start = None
        current_period_type = None
        current_period_max_intensity = 0.0

        for i, minute in enumerate(minutes):
            intensity = minute.get("precipitationIntensity", 0.0)
            precip_type = minute.get("precipitationType", "clear")

            # Check if precipitation is starting
            if intensity > 0.0 and current_period_start is None:
                current_period_start = i
                current_period_type = precip_type
                current_period_max_intensity = intensity
            # Check if precipitation continues
            elif intensity > 0.0 and current_period_start is not None:
                current_period_max_intensity = max(
                    current_period_max_intensity, intensity
                )
                if precip_type != "clear":
                    current_period_type = precip_type
            # Check if precipitation stops
            elif intensity == 0.0 and current_period_start is not None:
                precipitation_periods.append(
                    {
                        "start": current_period_start,
                        "end": i - 1,
                        "type": current_period_type,
                        "max_intensity": current_period_max_intensity,
                    }
                )
                current_period_start = None
                current_period_type = None
                current_period_max_intensity = 0.0

        # Handle case where precipitation continues to the end
        if current_period_start is not None:
            precipitation_periods.append(
                {
                    "start": current_period_start,
                    "end": len(minutes) - 1,
                    "type": current_period_type,
                    "max_intensity": current_period_max_intensity,
                }
            )

        # Get the first precipitation period to determine icon
        if not precipitation_periods:
            # No precipitation found - use day/night appropriate icon
            return "mdi:weather-sunny" if is_daylight else "mdi:weather-night"

        first_period = precipitation_periods[0]
        precip_type = first_period["type"]
        max_intensity = first_period["max_intensity"]

        # Determine icon based on precipitation type and intensity
        if precip_type == "rain":
            if max_intensity < 2.5:
                return "mdi:weather-rainy"
            return "mdi:weather-pouring"
        if precip_type == "snow":
            if max_intensity < 2.5:
                return "mdi:weather-snowy"
            return "mdi:weather-snowy-heavy"
        if precip_type == "sleet":
            return "mdi:weather-snowy-rainy"
        if precip_type == "hail":
            return "mdi:weather-hail"
        return "mdi:weather-rainy"

    @property
    def extra_state_attributes(self) -> dict[str, StateType]:
        """Return additional state attributes with minute-by-minute forecast."""
        if (
            not self.coordinator.data
            or ATTR_FORECAST_NEXT_HOUR not in self.coordinator.data
        ):
            return {}

        next_hour_data = self.coordinator.data[ATTR_FORECAST_NEXT_HOUR]
        attributes: dict[str, StateType] = {}

        # Add forecast metadata
        if "forecastStart" in next_hour_data:
            attributes["forecast_start"] = next_hour_data["forecastStart"]
        if "forecastEnd" in next_hour_data:
            attributes["forecast_end"] = next_hour_data["forecastEnd"]

        # Add minute-by-minute forecast data
        minutes = next_hour_data.get("minutes", [])
        if minutes:
            # Store as a list of dictionaries for each minute
            attributes["minutes"] = [
                {
                    "start_time": minute.get("startTime"),
                    "precipitation_intensity": minute.get("precipitationIntensity"),
                    "precipitation_chance": minute.get("precipitationChance"),
                    "precipitation_type": minute.get("precipitationType"),
                }
                for minute in minutes
            ]
            attributes["minute_count"] = len(minutes)

        return attributes
