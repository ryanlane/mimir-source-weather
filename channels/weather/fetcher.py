"""OpenWeatherMap HTTP helpers.

All network I/O is synchronous; callers wrap with asyncio.to_thread.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("mimir.channels.weather.fetcher")

_API_BASE = "https://api.openweathermap.org"
_ICON_URL = "https://openweathermap.org/img/wn/{code}@2x.png"
_USER_AGENT = "MimirWeather/1.0 (https://github.com/ryanlane/mimir)"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = _USER_AGENT
    return s


# ---------------------------------------------------------------------------
# API key

def validate_api_key(api_key: str) -> Dict[str, Any]:
    """Returns {valid, error}."""
    if not api_key or not api_key.strip():
        return {"valid": False, "error": "API key is empty"}
    try:
        resp = requests.get(
            f"{_API_BASE}/data/2.5/weather",
            params={"q": "London", "appid": api_key.strip()},
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
        )
        if resp.status_code == 401:
            return {"valid": False, "error": "Invalid API key — check your OpenWeatherMap account"}
        if resp.status_code == 429:
            return {"valid": False, "error": "Rate limit exceeded — wait a moment and try again"}
        resp.raise_for_status()
        return {"valid": True}
    except requests.exceptions.ConnectionError:
        return {"valid": False, "error": "Could not reach api.openweathermap.org — check network"}
    except Exception as exc:
        return {"valid": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Geocoding

def search_city(query: str, api_key: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Returns up to *limit* geocoding results for a city name query."""
    try:
        resp = requests.get(
            f"{_API_BASE}/geo/1.0/direct",
            params={"q": query, "limit": limit, "appid": api_key},
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        return [
            {
                "name": r.get("name", ""),
                "country": r.get("country", ""),
                "state": r.get("state", ""),
                "lat": r["lat"],
                "lon": r["lon"],
                "display_name": ", ".join(filter(None, [r.get("name"), r.get("state"), r.get("country")])),
            }
            for r in results
            if "lat" in r and "lon" in r
        ]
    except Exception as exc:
        logger.warning("[Weather] City search failed q=%r: %s", query, exc)
        return []


# ---------------------------------------------------------------------------
# Weather data

def get_current_weather(lat: float, lon: float, api_key: str, units: str = "imperial") -> Dict[str, Any]:
    resp = _session().get(
        f"{_API_BASE}/data/2.5/weather",
        params={"lat": lat, "lon": lon, "appid": api_key, "units": units},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_forecast(lat: float, lon: float, api_key: str, units: str = "imperial") -> List[Dict[str, Any]]:
    """Returns 5-day 3-hour forecast aggregated into daily summaries."""
    resp = _session().get(
        f"{_API_BASE}/data/2.5/forecast",
        params={"lat": lat, "lon": lon, "appid": api_key, "units": units, "cnt": 40},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("list", [])
    return _aggregate_daily(items)


def _aggregate_daily(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapses 3-hour slots into per-day summaries (skip today, return next 5)."""
    by_day: Dict[str, List] = defaultdict(list)
    for item in items:
        date = item.get("dt_txt", "")[:10]
        if date:
            by_day[date].append(item)

    daily = []
    for date, slots in sorted(by_day.items()):
        temps = [s["main"]["temp"] for s in slots]
        # Use the slot closest to noon for icon/description
        midday = min(slots, key=lambda s: abs(int(s.get("dt_txt", "00:00:00")[11:13]) - 12))
        daily.append({
            "date": date,
            "temp_min": min(temps),
            "temp_max": max(temps),
            "icon": midday["weather"][0]["icon"],
            "description": midday["weather"][0]["description"],
        })

    # daily[0] is today (partially elapsed) — skip it, return next 5
    return daily[1:6]


# ---------------------------------------------------------------------------
# Weather icons

def get_icon_bytes(icon_code: str, icons_dir: Path) -> Optional[bytes]:
    """Returns PNG bytes for an OWM icon code, downloading if not cached."""
    icon_path = icons_dir / f"{icon_code}.png"
    if not icon_path.exists():
        try:
            resp = requests.get(
                _ICON_URL.format(code=icon_code),
                headers={"User-Agent": _USER_AGENT},
                timeout=10,
            )
            if resp.status_code == 200:
                icon_path.write_bytes(resp.content)
            else:
                return None
        except Exception as exc:
            logger.warning("[Weather] Icon download failed code=%s: %s", icon_code, exc)
            return None
    try:
        return icon_path.read_bytes()
    except Exception:
        return None
