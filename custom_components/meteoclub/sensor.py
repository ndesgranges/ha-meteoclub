"""Sensor platform for MeteoClub.

Creates sensor entities for weather data from MeteoClub stations.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SENSOR_TYPES
from .coordinator import MeteoClubCoordinator

# Map device class strings to actual device classes
DEVICE_CLASS_MAP = {
    "temperature": SensorDeviceClass.TEMPERATURE,
    "humidity": SensorDeviceClass.HUMIDITY,
    "pressure": SensorDeviceClass.ATMOSPHERIC_PRESSURE,
    "wind_speed": SensorDeviceClass.WIND_SPEED,
    "precipitation": SensorDeviceClass.PRECIPITATION,
    "distance": SensorDeviceClass.DISTANCE,
}

# Map unit strings to actual units
UNIT_MAP = {
    "°C": UnitOfTemperature.CELSIUS,
    "%": PERCENTAGE,
    "hPa": UnitOfPressure.HPA,
    "km/h": UnitOfSpeed.KILOMETERS_PER_HOUR,
    "mm": UnitOfPrecipitationDepth.MILLIMETERS,
    "km": UnitOfLength.KILOMETERS,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MeteoClub sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[int, MeteoClubCoordinator] = data["coordinators"]
    favorites: list[dict[str, Any]] = data["favorites"]

    entities = []

    # Create sensors for each favorite city
    for favorite in favorites:
        city = favorite["city"]
        city_id = city["id"]
        city_name = city["name"]
        coordinator = coordinators[city_id]

        for sensor_key, sensor_def in SENSOR_TYPES.items():
            entities.append(
                MeteoClubSensor(
                    coordinator=coordinator,
                    city_id=city_id,
                    city_name=city_name,
                    sensor_key=sensor_key,
                    sensor_def=sensor_def,
                )
            )

    async_add_entities(entities)


class MeteoClubSensor(CoordinatorEntity[MeteoClubCoordinator], SensorEntity):
    """A sensor representing a MeteoClub weather metric."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MeteoClubCoordinator,
        city_id: int,
        city_name: str,
        sensor_key: str,
        sensor_def: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._city_id = city_id
        self._city_name = city_name
        self._sensor_key = sensor_key
        self._sensor_def = sensor_def
        self._field = sensor_def["field"]

        # Entity attributes
        self._attr_unique_id = f"meteoclub_{city_id}_{sensor_key}"
        self._attr_name = sensor_def["name"]
        self._attr_icon = sensor_def.get("icon")

        # Unit of measurement
        unit = sensor_def.get("unit")
        if unit:
            self._attr_native_unit_of_measurement = UNIT_MAP.get(unit, unit)

        # Device class
        device_class_str = sensor_def.get("device_class")
        if device_class_str:
            self._attr_device_class = DEVICE_CLASS_MAP.get(device_class_str)

        # State class
        state_class = sensor_def.get("state_class")
        if state_class == "measurement":
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to group all sensors for this city."""
        city_info = self.coordinator.city_info or {}
        return DeviceInfo(
            identifiers={(DOMAIN, f"meteoclub_{self._city_id}")},
            name=f"MeteoClub {self._city_name}",
            manufacturer="MeteoClub",
            model="Weather Station",
            configuration_url=city_info.get("url"),
            sw_version=city_info.get("observation_code"),
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if not self.coordinator.data:
            return None

        observation = self.coordinator.data.get("observation")
        if not observation:
            return None

        return observation.get(self._field)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {}

        if not self.coordinator.data:
            return attrs

        observation = self.coordinator.data.get("observation")
        if observation:
            attrs["observed_at"] = observation.get("observed_at")
            attrs["scraped_at"] = observation.get("scraped_at")

        city = self.coordinator.data.get("city")
        if city:
            attrs["city_id"] = city.get("id")
            attrs["department"] = city.get("department")
            if city.get("latitude") and city.get("longitude"):
                attrs["latitude"] = city.get("latitude")
                attrs["longitude"] = city.get("longitude")
            if city.get("altitude"):
                attrs["altitude"] = city.get("altitude")

        return attrs

        return attrs
