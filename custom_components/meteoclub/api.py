"""MeteoClub API Client."""

from __future__ import annotations

from typing import Any

import aiohttp
from aiohttp import BasicAuth

from .const import (
    API_CITY,
    API_FAVORITES,
    API_FORECASTS,
    API_OBSERVATIONS,
)


class MeteoClubApiError(Exception):
    """Base exception for MeteoClub API errors."""


class MeteoClubAuthError(MeteoClubApiError):
    """Authentication error."""


class MeteoClubConnectionError(MeteoClubApiError):
    """Connection error."""


class MeteoClubApi:
    """MeteoClub API client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        server_url: str,
        username: str,
        password: str,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._server_url = server_url.rstrip("/")
        self._auth = BasicAuth(username, password)

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Make an authenticated request to the API."""
        url = f"{self._server_url}{endpoint}"

        try:
            async with self._session.request(
                method,
                url,
                auth=self._auth,
                params=params,
            ) as response:
                if response.status == 401:
                    raise MeteoClubAuthError("Invalid credentials")
                if response.status == 403:
                    raise MeteoClubAuthError("Access forbidden")
                if response.status == 404:
                    return None
                if response.status >= 400:
                    text = await response.text()
                    raise MeteoClubApiError(f"API error {response.status}: {text}")
                return await response.json()
        except aiohttp.ClientError as err:
            raise MeteoClubConnectionError(f"Connection error: {err}") from err

    async def test_connection(self) -> bool:
        """Test the connection to the server by fetching favorites."""
        try:
            await self.get_favorites()
            return True
        except MeteoClubApiError:
            return False

    async def get_favorites(self) -> list[dict[str, Any]]:
        """Get the user's favorite cities."""
        result = await self._request("GET", API_FAVORITES)
        return result if result else []

    async def get_city(self, city_id: int) -> dict[str, Any] | None:
        """Get a specific city."""
        endpoint = API_CITY.format(city_id=city_id)
        return await self._request("GET", endpoint)

    async def get_observations(
        self,
        city_id: int,
        page: int = 1,
        page_size: int = 100,
        date: str | None = None,
    ) -> dict[str, Any]:
        """Get observations for a city."""
        endpoint = API_OBSERVATIONS.format(city_id=city_id)
        params = {"page": page, "page_size": page_size}
        if date:
            params["date"] = date
        return await self._request("GET", endpoint, params=params)

    async def get_forecasts(
        self,
        city_id: int,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Get forecasts for a city."""
        endpoint = API_FORECASTS.format(city_id=city_id)
        params = {}
        if model:
            params["model"] = model
        return await self._request("GET", endpoint, params=params)

    async def get_latest_observation(self, city_id: int) -> dict[str, Any] | None:
        """Get the most recent observation for a city."""
        data = await self.get_observations(city_id, page_size=1)
        if data and data.get("observations"):
            return data["observations"][0]
        return None
