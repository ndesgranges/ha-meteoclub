"""Weather platform for MeteoClub.

Provides a native Home Assistant weather entity for each favorite city.
Current conditions from observations, forecasts from weather models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MeteoClubCoordinator


def map_condition(raw_condition: str | None) -> str | None:
    """Map MeteoClub/meteociel condition strings to HA weather conditions.

    HA conditions: clear-night, cloudy, exceptional, fog, hail, lightning,
    lightning-rainy, partlycloudy, pouring, rainy, snowy, snowy-rainy, sunny,
    windy, windy-variant.

    Meteociel picto ``alt``/``title`` attributes are French descriptions such as
    "Ensoleillé", "Peu nuageux", "Pluie forte", "Nuit claire"... Rules are
    ordered so that more specific / compound patterns are checked before
    broader single-word matches (e.g. "peu nuageux" must win over "nuageux",
    "pluie forte" over "pluie", "pluie et neige" over both).
    """
    if not raw_condition:
        return None

    text = raw_condition.lower().strip()

    # (substring, HA condition) — evaluated in order, first match wins.
    rules: list[tuple[str, str]] = [
        # Thunderstorm + rain (meteociel: "Risque d'orage ... avec pluie modérée à forte")
        ("avec pluie modérée", "lightning-rainy"),
        ("avec pluie forte", "lightning-rainy"),
        ("avec pluie", "lightning-rainy"),
        ("averses orageuses", "lightning-rainy"),

        # Thunderstorm without rain (meteociel: "Risque d'orage faible/fort")
        ("risque d'orage", "lightning"),
        ("orageuse", "lightning-rainy"),
        ("orageux", "lightning-rainy"),
        ("orages", "lightning-rainy"),
        ("orage", "lightning-rainy"),
        ("thunderstorm", "lightning-rainy"),
        ("thunder", "lightning"),
        ("éclair", "lightning"),
        ("storm", "lightning-rainy"),

        # Mixed precipitation / freezing rain (before plain rain/snow)
        ("pluie et neige", "snowy-rainy"),
        ("pluie verglaçante", "snowy-rainy"),
        ("neige fondue", "snowy-rainy"),
        ("neige mêlée", "snowy-rainy"),
        ("verglas", "snowy-rainy"),
        ("sleet", "snowy-rainy"),

        # Hail / graupel
        ("grêle", "hail"),
        ("grésil", "hail"),
        ("hail", "hail"),

        # Snow
        ("neige forte", "snowy"),
        ("fortes chutes de neige", "snowy"),
        ("chutes de neige", "snowy"),
        ("neige faible", "snowy"),
        ("neige", "snowy"),
        ("flocons", "snowy"),
        ("snow", "snowy"),

        # Heavy rain / heavy showers (before regular rain — meteociel: "Averses de pluie fortes")
        ("averses de pluie fortes", "pouring"),
        ("averses de pluie forte", "pouring"),
        ("pluie forte", "pouring"),
        ("fortes pluies", "pouring"),
        ("pluies fortes", "pouring"),
        ("fortes averses", "pouring"),
        ("averses fortes", "pouring"),
        ("heavy rain", "pouring"),
        ("pouring", "pouring"),
        ("déluge", "pouring"),

        # Regular rain / drizzle / showers
        ("averses de pluie", "rainy"),
        ("averses", "rainy"),
        ("averse", "rainy"),
        ("bruine", "rainy"),
        ("drizzle", "rainy"),
        ("pluie faible", "rainy"),
        ("pluie modérée", "rainy"),
        ("pluie", "rainy"),
        ("pluvieux", "rainy"),
        ("rain", "rainy"),

        # Fog / mist (meteociel: "Brumes ou brouillard")
        ("brouillard", "fog"),
        ("brumeux", "fog"),
        ("brumes", "fog"),
        ("brume", "fog"),
        ("fog", "fog"),
        ("mist", "fog"),

        # Night clear (before day rules so "nuit claire" wins over "clair")
        ("nuit claire", "clear-night"),
        ("nuit dégagée", "clear-night"),
        ("nuit étoilée", "clear-night"),
        ("clear night", "clear-night"),

        # Partly cloudy (before cloudy so "peu nuageux" wins over "nuageux";
        # meteociel: "Mitigé" = variable/mixed sky, "Voilé" = veiled/hazy)
        ("mitigé", "partlycloudy"),
        ("mitigée", "partlycloudy"),
        ("peu nuageux", "partlycloudy"),
        ("peu nuageuse", "partlycloudy"),
        ("partiellement nuageux", "partlycloudy"),
        ("partiellement nuageuse", "partlycloudy"),
        ("éclaircies", "partlycloudy"),
        ("ciel voilé", "partlycloudy"),
        ("voilé", "partlycloudy"),
        ("voilée", "partlycloudy"),
        ("partly", "partlycloudy"),

        # Cloudy / overcast
        ("très nuageux", "cloudy"),
        ("nuageux", "cloudy"),
        ("nuageuse", "cloudy"),
        ("couvert", "cloudy"),
        ("couverte", "cloudy"),
        ("overcast", "cloudy"),
        ("cloudy", "cloudy"),
        ("gris", "cloudy"),

        # Wind
        ("tempête", "windy"),
        ("rafales", "windy"),
        ("vent fort", "windy"),
        ("venteux", "windy"),
        ("windy", "windy"),

        # Clear / sunny day (last so more specific patterns win)
        ("ensoleillé", "sunny"),
        ("ensoleillée", "sunny"),
        ("soleil", "sunny"),
        ("ciel dégagé", "sunny"),
        ("dégagé", "sunny"),
        ("dégagée", "sunny"),
        ("ciel clair", "sunny"),
        ("beau temps", "sunny"),
        ("beau", "sunny"),
        ("clear", "sunny"),
        ("sunny", "sunny"),
    ]

    for needle, ha_condition in rules:
        if needle in text:
            return ha_condition

    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MeteoClub weather entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[int, MeteoClubCoordinator] = data["coordinators"]
    favorites: list[dict[str, Any]] = data["favorites"]

    entities = []

    for favorite in favorites:
        city = favorite["city"]
        city_id = city["id"]
        city_name = city["name"]
        coordinator = coordinators[city_id]

        entities.append(
            MeteoClubWeather(
                coordinator=coordinator,
                city_id=city_id,
                city_name=city_name,
            )
        )

    async_add_entities(entities)


class MeteoClubWeather(CoordinatorEntity[MeteoClubCoordinator], WeatherEntity):
    """Weather entity for a MeteoClub city."""

    _attr_has_entity_name = True
    _attr_name = None  # Use device name as entity name
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(
        self,
        coordinator: MeteoClubCoordinator,
        city_id: int,
        city_name: str,
    ) -> None:
        """Initialize the weather entity."""
        super().__init__(coordinator)
        self._city_id = city_id
        self._city_name = city_name
        self._attr_unique_id = f"{DOMAIN}_{city_id}_weather"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this weather entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._city_id))},
            name=self._city_name,
            manufacturer="MeteoClub",
            model="Weather Station",
        )

    @property
    def _observation(self) -> dict[str, Any] | None:
        """Get current observation data."""
        if self.coordinator.data:
            return self.coordinator.data.get("observation")
        return None

    @property
    def native_temperature(self) -> float | None:
        """Return current temperature."""
        if obs := self._observation:
            return obs.get("temperature")
        return None

    @property
    def native_pressure(self) -> float | None:
        """Return current pressure."""
        if obs := self._observation:
            return obs.get("pressure_hpa")
        return None

    @property
    def humidity(self) -> float | None:
        """Return current humidity."""
        if obs := self._observation:
            return obs.get("humidity_percent")
        return None

    @property
    def native_wind_speed(self) -> float | None:
        """Return current wind speed."""
        if obs := self._observation:
            return obs.get("wind_speed_kmh")
        return None

    @property
    def native_wind_gust_speed(self) -> float | None:
        """Return current wind gust speed."""
        if obs := self._observation:
            return obs.get("wind_gust_kmh")
        return None

    @property
    def wind_bearing(self) -> float | str | None:
        """Return current wind bearing."""
        if obs := self._observation:
            return obs.get("wind_direction")
        return None

    @property
    def native_visibility(self) -> float | None:
        """Return current visibility in km."""
        if obs := self._observation:
            return obs.get("visibility_km")
        return None

    @property
    def native_dew_point(self) -> float | None:
        """Return current dew point."""
        if obs := self._observation:
            return obs.get("dew_point")
        return None

    @property
    def cloud_coverage(self) -> int | None:
        """Return current cloud coverage percentage."""
        if obs := self._observation:
            # cloud_cover is a string description, try to parse percentage
            cloud = obs.get("cloud_cover")
            if cloud and isinstance(cloud, (int, float)):
                return int(cloud)
        return None

    @property
    def condition(self) -> str | None:
        """Return current weather condition."""
        if obs := self._observation:
            raw_condition = obs.get("weather_condition")
            return map_condition(raw_condition)
        return None

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return daily forecast from GFS model."""
        if not self.coordinator.data:
            return None

        forecasts = self.coordinator.data.get("forecasts_daily", [])
        if not forecasts:
            return None

        # Group all forecasts by date to calculate min/max
        daily_data: dict[str, list[dict]] = {}
        for fc in forecasts:
            forecast_for = fc.get("forecast_for")
            if not forecast_for:
                continue

            dt = datetime.fromisoformat(forecast_for.replace("Z", "+00:00"))
            date_key = dt.strftime("%Y-%m-%d")

            if date_key not in daily_data:
                daily_data[date_key] = []
            daily_data[date_key].append({"fc": fc, "hour": dt.hour})

        # Convert to HA Forecast format
        result: list[Forecast] = []
        for date_key in sorted(daily_data.keys()):
            day_forecasts = daily_data[date_key]

            # Calculate min/max temperatures from all forecasts of the day
            temps = [
                f["fc"].get("temperature")
                for f in day_forecasts
                if f["fc"].get("temperature") is not None
            ]
            temp_max = max(temps) if temps else None
            temp_min = min(temps) if temps else None

            # Sum precipitation for the day
            precip_total = sum(
                f["fc"].get("precipitation_mm") or 0
                for f in day_forecasts
            )

            # Pick noon forecast for other fields (condition, humidity, wind)
            # Fallback to first forecast if no noon available
            noon_fc = next(
                (f["fc"] for f in day_forecasts if 11 <= f["hour"] <= 13),
                day_forecasts[0]["fc"]
            )

            forecast: Forecast = {
                "datetime": f"{date_key}T12:00:00Z",
                "native_temperature": temp_max,
                "native_templow": temp_min,
                "humidity": noon_fc.get("humidity_percent"),
                "native_precipitation": precip_total if precip_total > 0 else None,
                "native_wind_speed": noon_fc.get("wind_speed_kmh"),
                "wind_bearing": noon_fc.get("wind_direction"),
                "condition": map_condition(noon_fc.get("weather_description")),
            }
            result.append(forecast)

        return result if result else None

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Return hourly forecast from ICON_EU model."""
        if not self.coordinator.data:
            return None

        forecasts = self.coordinator.data.get("forecasts_hourly", [])
        if not forecasts:
            return None

        # Convert to HA Forecast format
        result: list[Forecast] = []
        for fc in forecasts:
            forecast_for = fc.get("forecast_for")
            if not forecast_for:
                continue

            forecast: Forecast = {
                "datetime": forecast_for,
                "native_temperature": fc.get("temperature"),
                "humidity": fc.get("humidity_percent"),
                "native_precipitation": fc.get("precipitation_mm"),
                "native_wind_speed": fc.get("wind_speed_kmh"),
                "wind_bearing": fc.get("wind_direction"),
                "condition": map_condition(fc.get("weather_description")),
            }
            result.append(forecast)

        # Sort by datetime and limit to 48 hours
        result.sort(key=lambda x: x.get("datetime", ""))
        return result[:48] if result else None
