"""MeteoClub - Home Assistant Custom Integration.

Fetches weather data from a MeteoClub server and creates sensors
for each favorite weather station (city). Also provides a weather
dashboard for comparing observation vs forecast accuracy.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MeteoClubApi
from .const import CONF_SERVER_URL, DOMAIN
from .coordinator import MeteoClubCoordinator
from .websocket import async_register_websocket_api

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "weather"]

# Frontend panel configuration
PANEL_URL = "/meteoclub-panel"
PANEL_TITLE = "MeteoClub"
PANEL_ICON = "mdi:weather-partly-cloudy"
PANEL_NAME = "meteoclub-panel"
PANEL_VERSION = "1.0.2"  # Bump this to bust cache on Android app


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the MeteoClub component."""
    hass.data.setdefault(DOMAIN, {})

    # Register WebSocket API
    async_register_websocket_api(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MeteoClub from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Extract configuration
    server_url = entry.data[CONF_SERVER_URL]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    # Create API client
    session = async_get_clientsession(hass)
    api = MeteoClubApi(session, server_url, username, password)

    # Fetch user's favorites
    favorites = await api.get_favorites()
    _LOGGER.info("Found %d favorite cities", len(favorites))

    # Create one coordinator per favorite city
    coordinators: dict[int, MeteoClubCoordinator] = {}
    for favorite in favorites:
        city = favorite["city"]
        city_id = city["id"]
        city_name = city["name"]

        coordinator = MeteoClubCoordinator(hass, api, city_id, city_name)
        await coordinator.async_config_entry_first_refresh()
        coordinators[city_id] = coordinator

    # Store data for use by platforms
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinators": coordinators,
        "favorites": favorites,
    }

    # Register frontend panel (only once)
    await _async_register_panel(hass)

    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Register the MeteoClub frontend panel."""
    # Check if panel is already registered
    if PANEL_NAME in hass.data.get("frontend_panels", {}):
        return

    # Path to our files
    frontend_path = Path(__file__).parent / "frontend"
    translations_path = Path(__file__).parent / "translations"

    # Register static paths for JS and translation files
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                url_path=f"/{DOMAIN}/frontend",
                path=str(frontend_path),
                cache_headers=False,
            ),
            StaticPathConfig(
                url_path=f"/{DOMAIN}/translations",
                path=str(translations_path),
                cache_headers=True,
            ),
        ]
    )

    # Register the panel
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=DOMAIN,
        config={
            "_panel_custom": {
                "name": PANEL_NAME,
                "module_url": f"/{DOMAIN}/frontend/meteoclub-panel.js?v={PANEL_VERSION}",
            }
        },
        require_admin=False,
    )

    _LOGGER.info("MeteoClub dashboard panel registered")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
