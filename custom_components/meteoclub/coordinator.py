"""MeteoClub Data Coordinator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MeteoClubApi, MeteoClubApiError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Models used for weather entity forecasts
DAILY_FORECAST_MODEL = "gfs"
HOURLY_FORECAST_MODEL = "icon_eu"


class MeteoClubCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage data fetching from MeteoClub."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: MeteoClubApi,
        city_id: int,
        city_name: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{city_name}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.city_id = city_id
        self.city_name = city_name
        self.city_info: dict[str, Any] | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the API."""
        try:
            # Get city info if we don't have it yet
            if self.city_info is None:
                self.city_info = await self.api.get_city(self.city_id)
                if self.city_info is None:
                    raise UpdateFailed(f"City {self.city_id} not found")

            # Get the latest observation
            observation = await self.api.get_latest_observation(self.city_id)

            # Get forecasts for weather entity (next 7 days)
            now = datetime.now(timezone.utc)
            forecast_end = now + timedelta(days=7)
            
            # Fetch GFS for daily and ICON_EU for hourly forecasts
            # all_versions=False to get only the latest forecast per time slot
            gfs_forecasts = []
            icon_forecasts = []
            
            try:
                gfs_data = await self.api.get_forecasts(
                    self.city_id,
                    model=DAILY_FORECAST_MODEL,
                    all_versions=False,
                    start_date=now.isoformat(),
                    end_date=forecast_end.isoformat(),
                )
                gfs_forecasts = gfs_data.get("forecasts", []) if gfs_data else []
            except Exception as err:
                _LOGGER.warning("Failed to fetch GFS forecasts: %s", err)
            
            try:
                icon_data = await self.api.get_forecasts(
                    self.city_id,
                    model=HOURLY_FORECAST_MODEL,
                    all_versions=False,
                    start_date=now.isoformat(),
                    end_date=forecast_end.isoformat(),
                )
                icon_forecasts = icon_data.get("forecasts", []) if icon_data else []
            except Exception as err:
                _LOGGER.warning("Failed to fetch ICON_EU forecasts: %s", err)

            return {
                "city": self.city_info,
                "observation": observation,
                "forecasts_daily": gfs_forecasts,
                "forecasts_hourly": icon_forecasts,
            }

        except MeteoClubApiError as err:
            raise UpdateFailed(f"Error fetching data: {err}") from err
