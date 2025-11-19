"""Sensor entity tests for the WeatherKit integration."""

from typing import Any

import pytest

from homeassistant.core import HomeAssistant

from . import init_integration, mock_weather_response


@pytest.mark.parametrize(
    ("entity_name", "expected_value"),
    [
        ("sensor.home_precipitation_intensity", 0.7),
        ("sensor.home_pressure_trend", "rising"),
    ],
)
async def test_sensor_values(
    hass: HomeAssistant, entity_name: str, expected_value: Any
) -> None:
    """Test that various sensor values match what we expect."""
    with mock_weather_response():
        await init_integration(hass)

    state = hass.states.get(entity_name)
    assert state
    assert state.state == str(expected_value)


async def test_next_hour_forecast_sensor(hass: HomeAssistant) -> None:
    """Test the NextHourForecast sensor."""
    with mock_weather_response(has_next_hour_forecast=True):
        await init_integration(hass)

    state = hass.states.get("sensor.home_next_hour_forecast")
    assert state
    assert state.state == "0.5"
    assert state.attributes["device_class"] == "precipitation_intensity"
    assert state.attributes["unit_of_measurement"] == "mm/h"
    assert state.attributes["forecast_start"] == "2023-09-08T22:03:04Z"
    assert state.attributes["forecast_end"] == "2023-09-08T23:03:04Z"
    assert state.attributes["minute_count"] == 6
    assert len(state.attributes["minutes"]) == 6

    # Check first minute data
    first_minute = state.attributes["minutes"][0]
    assert first_minute["start_time"] == "2023-09-08T22:03:04Z"
    assert first_minute["precipitation_intensity"] == 0.5
    assert first_minute["precipitation_chance"] == 0.3
    assert first_minute["precipitation_type"] == "rain"


async def test_next_hour_forecast_sensor_not_available(hass: HomeAssistant) -> None:
    """Test that NextHourForecast sensor is not created when data is unavailable."""
    with mock_weather_response(has_next_hour_forecast=False):
        await init_integration(hass)

    state = hass.states.get("sensor.home_next_hour_forecast")
    assert state is None
