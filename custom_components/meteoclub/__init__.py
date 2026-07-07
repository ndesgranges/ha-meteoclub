"""MeteoClub - Home Assistant Custom Integration.

Fetches weather data from a MeteoClub server and creates sensors
for each favorite weather station (city).
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MeteoClubApi
from .const import CONF_SERVER_URL, DOMAIN
from .coordinator import MeteoClubCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


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

    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
