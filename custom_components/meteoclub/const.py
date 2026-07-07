"""MeteoClub - Home Assistant Custom Integration Constants."""

DOMAIN = "meteoclub"

# Configuration keys (use CONF_USERNAME and CONF_PASSWORD from homeassistant.const)
CONF_SERVER_URL = "server_url"

# Default values
DEFAULT_SERVER_URL = "http://localhost:8000"
DEFAULT_SCAN_INTERVAL = 300  # 5 minutes

# API endpoints
API_FAVORITES = "/favorites"
API_CITIES = "/cities"
API_CITY = "/cities/{city_id}"
API_OBSERVATIONS = "/observations/city/{city_id}"
API_FORECASTS = "/forecasts/city/{city_id}"

# Sensor types
SENSOR_TYPES = {
    "temperature": {
        "name": "Temperature",
        "unit": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer",
        "field": "temperature",
    },
    "humidity": {
        "name": "Humidity",
        "unit": "%",
        "device_class": "humidity",
        "state_class": "measurement",
        "icon": "mdi:water-percent",
        "field": "humidity_percent",
    },
    "pressure": {
        "name": "Pressure",
        "unit": "hPa",
        "device_class": "pressure",
        "state_class": "measurement",
        "icon": "mdi:gauge",
        "field": "pressure_hpa",
    },
    "wind_speed": {
        "name": "Wind Speed",
        "unit": "km/h",
        "device_class": "wind_speed",
        "state_class": "measurement",
        "icon": "mdi:weather-windy",
        "field": "wind_speed_kmh",
    },
    "wind_gust": {
        "name": "Wind Gust",
        "unit": "km/h",
        "device_class": "wind_speed",
        "state_class": "measurement",
        "icon": "mdi:weather-windy-variant",
        "field": "wind_gust_kmh",
    },
    "wind_direction": {
        "name": "Wind Direction",
        "unit": None,
        "device_class": None,
        "state_class": None,
        "icon": "mdi:compass",
        "field": "wind_direction",
    },
    "precipitation": {
        "name": "Precipitation",
        "unit": "mm",
        "device_class": "precipitation",
        "state_class": "measurement",
        "icon": "mdi:weather-rainy",
        "field": "precipitation_mm",
    },
    "dew_point": {
        "name": "Dew Point",
        "unit": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer-water",
        "field": "dew_point",
    },
    "visibility": {
        "name": "Visibility",
        "unit": "km",
        "device_class": "distance",
        "state_class": "measurement",
        "icon": "mdi:eye",
        "field": "visibility_km",
    },
    "weather_condition": {
        "name": "Weather Condition",
        "unit": None,
        "device_class": None,
        "state_class": None,
        "icon": "mdi:weather-partly-cloudy",
        "field": "weather_condition",
    },
    "cloud_cover": {
        "name": "Cloud Cover",
        "unit": None,
        "device_class": None,
        "state_class": None,
        "icon": "mdi:cloud",
        "field": "cloud_cover",
    },
}
