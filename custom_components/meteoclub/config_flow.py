"""Config flow for MeteoClub integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MeteoClubApi, MeteoClubAuthError, MeteoClubConnectionError
from .const import CONF_SERVER_URL, DEFAULT_SERVER_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class MeteoClubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MeteoClub."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step - server configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            server_url = user_input[CONF_SERVER_URL]
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            # Test the connection by fetching favorites
            session = async_get_clientsession(self.hass)
            api = MeteoClubApi(session, server_url, username, password)

            try:
                favorites = await api.get_favorites()

                if not favorites:
                    errors["base"] = "no_favorites"
                else:
                    # Set unique ID based on server URL and username
                    await self.async_set_unique_id(f"meteoclub_{username}@{server_url}")
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"MeteoClub ({username})",
                        data={
                            CONF_SERVER_URL: server_url,
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                        },
                    )

            except MeteoClubAuthError:
                errors["base"] = "invalid_auth"
            except MeteoClubConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected error during connection test")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERVER_URL, default=DEFAULT_SERVER_URL): str,
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

