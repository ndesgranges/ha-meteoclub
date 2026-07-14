"""WebSocket API for MeteoClub dashboard."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    DASHBOARD_METRICS,
    DOMAIN,
    FORECAST_MODELS,
    HORIZON_OPTIONS,
    MODEL_NAMES,
)

_LOGGER = logging.getLogger(__name__)

# Timeout for API requests in seconds (includes retry time)
# API client has 60s timeout per request with up to 3 retries
API_TIMEOUT = 120


def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register the WebSocket API handlers."""
    websocket_api.async_register_command(hass, websocket_get_config)
    websocket_api.async_register_command(hass, websocket_get_chart_data)
    websocket_api.async_register_command(hass, websocket_get_cities)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "meteoclub/config",
    }
)
@callback
def websocket_get_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return MeteoClub dashboard configuration."""
    connection.send_result(
        msg["id"],
        {
            "models": [
                {"id": model, "name": MODEL_NAMES.get(model, model.upper())}
                for model in FORECAST_MODELS
            ],
            "metrics": [
                {
                    "id": key,
                    "name": info["name"],
                    "unit": info["unit"],
                    "icon": info["icon"],
                }
                for key, info in DASHBOARD_METRICS.items()
            ],
            "horizons": HORIZON_OPTIONS,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "meteoclub/cities",
    }
)
@callback
def websocket_get_cities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return list of configured cities."""
    cities = []

    for entry_data in hass.data.get(DOMAIN, {}).values():
        favorites = entry_data.get("favorites", [])
        for fav in favorites:
            city = fav.get("city", {})
            cities.append(
                {
                    "id": city.get("id"),
                    "name": city.get("name"),
                    "department": city.get("department"),
                }
            )

    connection.send_result(msg["id"], {"cities": cities})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "meteoclub/chart_data",
        vol.Required("city_id"): int,
        vol.Required("metric"): str,
        vol.Required("horizon_days"): int,
        vol.Required("models"): [str],
        vol.Optional("start_date"): str,
        vol.Optional("end_date"): str,
    }
)
@websocket_api.async_response
async def websocket_get_chart_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return chart data for observations vs forecasts comparison.

    This fetches:
    - Observations for the date range
    - For each selected model: forecasts that were made `horizon_days` before
      the observation time

    Example: If horizon_days=3 and we're looking at observation for July 10th,
    we want the forecast that was issued on July 7th predicting July 10th.
    """
    city_id = msg["city_id"]
    metric = msg["metric"]
    horizon_days = msg["horizon_days"]
    selected_models = msg["models"]

    # Validate metric
    if metric not in DASHBOARD_METRICS:
        connection.send_error(msg["id"], "invalid_metric", f"Unknown metric: {metric}")
        return

    metric_info = DASHBOARD_METRICS[metric]
    field = metric_info["field"]

    # Find the API client for this city
    api = None
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if "api" in entry_data:
            # Check if this entry has this city
            favorites = entry_data.get("favorites", [])
            for fav in favorites:
                if fav.get("city", {}).get("id") == city_id:
                    api = entry_data["api"]
                    break
        if api:
            break

    if not api:
        connection.send_error(
            msg["id"], "city_not_found", f"City {city_id} not found in configuration"
        )
        return

    # Parse date range (default: last 7 days)
    now = datetime.now(timezone.utc)
    if "end_date" in msg and msg["end_date"]:
        end_date = datetime.fromisoformat(msg["end_date"].replace("Z", "+00:00"))
    else:
        end_date = now

    if "start_date" in msg and msg["start_date"]:
        start_date = datetime.fromisoformat(msg["start_date"].replace("Z", "+00:00"))
    else:
        start_date = end_date - timedelta(days=7)

    try:
        # Fetch observations for the date range - use server-side filtering
        observations_data = await api.get_observations(
            city_id,
            page_size=500,  # API max is 500
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )

        observations = observations_data.get("observations", [])

        # Build observation series from the filtered results
        observation_series = []
        for obs in observations:
            obs_time_str = obs.get("observed_at")
            if not obs_time_str:
                continue

            value = obs.get(field)
            if value is not None:
                observation_series.append(
                    {
                        "time": obs_time_str,
                        "value": value,
                    }
                )

        # Sort by time
        observation_series.sort(key=lambda x: x["time"])

        # Build forecast series for each model
        forecast_series = {}

        # Calculate date range for forecasts
        # We need forecasts where forecast_for is in our observation range
        forecast_start = start_date.isoformat()
        forecast_end = end_date.isoformat()

        for model in selected_models:
            if model not in FORECAST_MODELS:
                continue

            try:
                # Fetch forecasts for this model with timeout and date filtering
                forecasts_data = await asyncio.wait_for(
                    api.get_forecasts(
                        city_id,
                        model=model,
                        start_date=forecast_start,
                        end_date=forecast_end,
                    ),
                    timeout=API_TIMEOUT,
                )
                forecasts = forecasts_data.get("forecasts", []) if forecasts_data else []
            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout fetching %s forecasts for city %d", model, city_id)
                forecasts = []
            except Exception as err:
                _LOGGER.warning("Error fetching %s forecasts: %s", model, err)
                forecasts = []

            model_series = []

            # For each observation time, find the appropriate forecast
            for obs_point in observation_series:
                obs_time = datetime.fromisoformat(
                    obs_point["time"].replace("Z", "+00:00")
                )

                best_forecast = None
                best_score = None

                for fc in forecasts:
                    forecast_for_str = fc.get("forecast_for")
                    issued_at_str = fc.get("issued_at")

                    if not forecast_for_str or not issued_at_str:
                        continue

                    forecast_for = datetime.fromisoformat(
                        forecast_for_str.replace("Z", "+00:00")
                    )
                    issued_at = datetime.fromisoformat(
                        issued_at_str.replace("Z", "+00:00")
                    )

                    # Check if this forecast predicts for roughly the obs_time
                    # (within 3 hours tolerance)
                    forecast_diff = abs((forecast_for - obs_time).total_seconds())
                    if forecast_diff > 3 * 3600:
                        continue

                    if horizon_days == 0:
                        # Special case: "Latest" - find the most recently issued
                        # forecast that predicts for this observation time
                        # (must be issued before or at observation time)
                        if issued_at > obs_time:
                            continue
                        # Score: prefer most recent (smaller is better, so negate)
                        score = -issued_at.timestamp() + forecast_diff
                    else:
                        # Normal case: find forecast issued around target horizon
                        target_issued = obs_time - timedelta(days=horizon_days)
                        issued_diff = abs((issued_at - target_issued).total_seconds())
                        if issued_diff > 12 * 3600:
                            continue
                        # Score: prefer exact matches
                        score = forecast_diff + issued_diff

                    if best_score is None or score < best_score:
                        best_forecast = fc
                        best_score = score

                if best_forecast:
                    value = best_forecast.get(field)
                    if value is not None:
                        model_series.append(
                            {
                                "time": obs_point["time"],
                                "value": value,
                                "issued_at": best_forecast.get("issued_at"),
                                "forecast_for": best_forecast.get("forecast_for"),
                            }
                        )

            forecast_series[model] = model_series

        connection.send_result(
            msg["id"],
            {
                "metric": {
                    "id": metric,
                    "name": metric_info["name"],
                    "unit": metric_info["unit"],
                },
                "horizon_days": horizon_days,
                "observations": observation_series,
                "forecasts": forecast_series,
            },
        )

    except Exception as err:
        _LOGGER.exception("Error fetching chart data")
        connection.send_error(msg["id"], "fetch_error", str(err))
