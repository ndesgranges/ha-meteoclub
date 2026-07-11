"""MeteoClub API Client."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp
from aiohttp import BasicAuth, ClientTimeout

from .const import (
    API_CITY,
    API_FAVORITES,
    API_FORECASTS,
    API_OBSERVATIONS,
)

_LOGGER = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds
REQUEST_TIMEOUT = 120  # seconds - increased for large responses


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
        self._timeout = ClientTimeout(total=REQUEST_TIMEOUT)

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        retries: int = MAX_RETRIES,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Make an authenticated request to the API with retry logic.

        Uses chunked reading to handle large responses that may cause
        ContentLengthError on slow or unreliable connections.
        """
        url = f"{self._server_url}{endpoint}"
        last_error = None

        for attempt in range(retries):
            try:
                async with self._session.request(
                    method,
                    url,
                    auth=self._auth,
                    params=params,
                    timeout=self._timeout,
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

                    # Read response body in chunks to handle large responses
                    # that may cause ContentLengthError
                    try:
                        body = await response.read()
                    except aiohttp.ClientPayloadError as payload_err:
                        # ContentLengthError is a subclass of ClientPayloadError
                        # Try to get whatever data was received before the error
                        _LOGGER.warning(
                            "Payload error reading %s: %s. Attempting partial read...",
                            endpoint, payload_err
                        )
                        # The response body might have partial data in the buffer
                        # Re-raise to trigger retry
                        raise

                    return json.loads(body)

            except (MeteoClubAuthError, MeteoClubApiError):
                # Don't retry auth errors or API errors
                raise
            except json.JSONDecodeError as err:
                _LOGGER.warning("Invalid JSON response from %s: %s", endpoint, err)
                last_error = err
                if attempt < retries - 1:
                    await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
                continue
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last_error = err
                if attempt < retries - 1:
                    delay = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                    _LOGGER.debug(
                        "Request to %s failed (attempt %d/%d): %s. Retrying in %ds...",
                        endpoint, attempt + 1, retries, err, delay
                    )
                    await asyncio.sleep(delay)
                else:
                    _LOGGER.warning(
                        "Request to %s failed after %d attempts: %s",
                        endpoint, retries, err
                    )

        raise MeteoClubConnectionError(f"Connection error after {retries} retries: {last_error}") from last_error

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
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Get observations for a city.

        Args:
            city_id: The city ID to get observations for.
            page: Page number (starts at 1).
            page_size: Number of observations per page (max 500).
            date: Filter to a specific day (YYYY-MM-DD).
            start_date: ISO date string to filter observations from this date.
            end_date: ISO date string to filter observations until this date.
        """
        endpoint = API_OBSERVATIONS.format(city_id=city_id)
        params = {"page": page, "page_size": page_size}
        if date:
            params["date"] = date
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return await self._request("GET", endpoint, params=params)

    async def get_forecasts(
        self,
        city_id: int,
        model: str | None = None,
        all_versions: bool = True,
        start_date: str | None = None,
        end_date: str | None = None,
        page_size: int = 200,
    ) -> dict[str, Any]:
        """Get forecasts for a city with automatic pagination.

        Fetches all pages of forecasts and returns them combined.
        Uses pagination to avoid large responses that may cause connection issues.

        Args:
            city_id: The city ID to get forecasts for.
            model: Optional filter by forecast model (gfs, wrf, arome, etc.).
            all_versions: If True, returns all historical forecast versions.
                         If False, returns only the latest forecast for each time slot.
                         Default True for dashboard comparison needs.
            start_date: Optional ISO date string to filter forecasts from this date.
            end_date: Optional ISO date string to filter forecasts until this date.
            page_size: Number of forecasts per page (default 200).
        """
        endpoint = API_FORECASTS.format(city_id=city_id)
        all_forecasts = []
        page = 1
        total = None

        while True:
            params = {
                "all_versions": str(all_versions).lower(),
                "page": page,
                "page_size": page_size,
            }
            if model:
                params["model"] = model
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

            result = await self._request("GET", endpoint, params=params)
            if not result:
                break

            forecasts = result.get("forecasts", [])
            all_forecasts.extend(forecasts)

            if total is None:
                total = result.get("total", 0)

            # Check if we've fetched all pages
            if len(all_forecasts) >= total or len(forecasts) < page_size:
                break

            page += 1

            # Safety limit to prevent infinite loops
            if page > 100:
                _LOGGER.warning("Pagination safety limit reached for forecasts")
                break

        return {
            "total": total or len(all_forecasts),
            "forecasts": all_forecasts,
        }

    async def get_latest_observation(self, city_id: int) -> dict[str, Any] | None:
        """Get the most recent observation for a city."""
        data = await self.get_observations(city_id, page_size=1)
        if data and data.get("observations"):
            return data["observations"][0]
        return None
