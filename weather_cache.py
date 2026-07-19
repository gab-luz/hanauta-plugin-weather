#!/usr/bin/env python3
"""One-shot weather cache fetcher for hanauta-service plugin system.

Called by hanauta-service via hanauta-service-plugin.json.  Reads the
configured city and poll interval from settings, fetches the forecast
from Open-Meteo, and writes an atomic JSON cache to
~/.local/state/hanauta/service/weather.json so the weather popup can
load data instantly.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib import parse, request

STATE_DIR = Path(
    os.environ.get("HANAUTA_SERVICE_STATE_DIR")
    or os.environ.get("HANAUTA_STATE_DIR")
    or Path.home() / ".local" / "state" / "hanauta",
)
SERVICE_DIR = STATE_DIR / "service"
WEATHER_CACHE = SERVICE_DIR / "weather.json"
SETTINGS_FILE = Path(
    os.environ.get("HANAUTA_SETTINGS_PATH")
    or STATE_DIR / "notification-center" / "settings.json"
)
WEATHER_API = "https://api.open-meteo.com/v1/forecast"
MIN_POLL_MINUTES = 15


def _load_weather_settings() -> dict[str, Any] | None:
    try:
        payload = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    weather = payload.get("weather", {})
    if not isinstance(weather, dict):
        return None
    if not weather.get("enabled", False):
        return None
    return weather


def _extract_city(weather: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return {
            "name": str(weather.get("name", "")).strip(),
            "latitude": float(weather["latitude"]),
            "longitude": float(weather["longitude"]),
            "timezone": str(weather.get("timezone", "auto")).strip() or "auto",
        }
    except Exception:
        return None


def _fetch_payload(city: dict[str, Any]) -> dict[str, Any] | None:
    params = parse.urlencode(
        {
            "latitude": f"{city['latitude']:.5f}",
            "longitude": f"{city['longitude']:.5f}",
            "timezone": city["timezone"],
            "forecast_days": "7",
            "current": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "precipitation",
                    "pressure_msl",
                    "weather_code",
                    "wind_speed_10m",
                    "is_day",
                ]
            ),
            "daily": ",".join(
                [
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_probability_max",
                    "sunrise",
                    "sunset",
                ]
            ),
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "wind_speed_10m",
                    "wind_gusts_10m",
                    "visibility",
                    "uv_index",
                    "weather_code",
                    "precipitation_probability",
                    "precipitation",
                    "rain",
                    "snowfall",
                ]
            ),
        }
    )
    url = f"{WEATHER_API}?{params}"
    req = request.Request(url, headers={"User-Agent": "Hanauta Weather/1.0"})
    try:
        with request.urlopen(req, timeout=8.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_cache(city: dict[str, Any], payload: dict[str, Any]) -> bool:
    import time as _time

    cache = {
        "requested": {
            "latitude": city["latitude"],
            "longitude": city["longitude"],
            "timezone": city["timezone"],
        },
        "payload": payload,
        "updated_at": _time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        SERVICE_DIR.mkdir(parents=True, exist_ok=True)
        tmp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(SERVICE_DIR),
                prefix="weather-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(json.dumps(cache, ensure_ascii=True, separators=(",", ":")))
                handle.flush()
                os.fsync(handle.fileno())
                tmp = Path(handle.name)
            os.replace(str(tmp), str(WEATHER_CACHE))
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def main() -> int:
    weather = _load_weather_settings()
    if weather is None:
        return 0

    city = _extract_city(weather)
    if city is None:
        return 0

    payload = _fetch_payload(city)
    if payload is None:
        return 1

    ok = _write_cache(city, payload)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
