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

_GOOGLE_ICONS_BASE = (
    "https://raw.githubusercontent.com/mrdarrengriffin/google-weather-icons/main/sets/set-4"
)

# Light set has all 52 icons; dark set has 30 (no day-specific suffixed icons).
# Separate mappings so we never request a filename that doesn't exist.
_OWM_TO_GOOGLE_LIGHT: dict[str, str] = {
    "01d": "clear_day",
    "01n": "clear_night",
    "02d": "partly_cloudy_day",
    "02n": "partly_cloudy_night",
    "03d": "mostly_cloudy_day",
    "03n": "mostly_cloudy_night",
    "04d": "cloudy",
    "04n": "cloudy",
    "09d": "scattered_showers_day",
    "09n": "scattered_showers_night",
    "10d": "rain_with_sunny",
    "10n": "showers_rain",
    "11d": "isolated_scattered_thunderstorms_day",
    "11n": "isolated_scattered_thunderstorms_night",
    "13d": "heavy_snow",
    "13n": "heavy_snow",
    "50d": "haze_fog_dust_smoke",
    "50n": "haze_fog_dust_smoke",
}

_OWM_TO_GOOGLE_DARK: dict[str, str] = {
    "01d": "sunny",
    "01n": "clear_night",
    "02d": "partly_cloudy",
    "02n": "partly_cloudy",
    "03d": "cloudy_with_sunny",
    "03n": "cloudy",
    "04d": "cloudy",
    "04n": "cloudy",
    "09d": "rain_with_cloudy",
    "09n": "rain_with_cloudy",
    "10d": "rain_with_sunny",
    "10n": "rain_with_cloudy",
    "11d": "thunderstorms",
    "11n": "thunderstorms",
    "13d": "heavy_snow",
    "13n": "heavy_snow",
    "50d": "windy",
    "50n": "windy",
}


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
    """Collapses 3-hour slots into per-day summaries (skip today, return next 5).

    OWM dt_txt is UTC. We derive 'today' from the first item in the payload
    rather than the system clock to avoid local/UTC timezone mismatches.
    """
    if not items:
        return []

    # First item is always the current UTC period — its date is "today" to skip.
    current_date = items[0].get("dt_txt", "")[:10]

    by_day: Dict[str, List] = defaultdict(list)
    for item in items:
        date = item.get("dt_txt", "")[:10]
        if date and date != current_date:
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

    return daily[:5]


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


def get_google_icon_bytes(icon_code: str, theme: str, icons_dir: Path) -> Optional[bytes]:
    """Returns PNG bytes for a Google Weather icon (set-4), downloading and converting if needed.

    Falls back to OWM icon if cairosvg is not installed or the download fails.
    theme: "dark" | "light"
    """
    safe_theme = theme if theme in ("light", "dark") else "dark"
    mapping = _OWM_TO_GOOGLE_DARK if safe_theme == "dark" else _OWM_TO_GOOGLE_LIGHT
    google_name = mapping.get(icon_code)
    if not google_name:
        return get_icon_bytes(icon_code, icons_dir)
    cache_path = icons_dir / f"google_{safe_theme}_{google_name}.png"
    if cache_path.exists():
        try:
            return cache_path.read_bytes()
        except Exception:
            pass

    svg_url = f"{_GOOGLE_ICONS_BASE}/{safe_theme}/{google_name}.svg"
    try:
        resp = requests.get(svg_url, headers={"User-Agent": _USER_AGENT}, timeout=10)
        if resp.status_code != 200:
            logger.warning("[Weather] Google icon not found url=%s status=%s", svg_url, resp.status_code)
            return get_icon_bytes(icon_code, icons_dir)
        svg_bytes = resp.content
    except Exception as exc:
        logger.warning("[Weather] Google icon download failed url=%s: %s", svg_url, exc)
        return get_icon_bytes(icon_code, icons_dir)

    try:
        import cairosvg
        png_bytes = cairosvg.svg2png(bytestring=svg_bytes, output_width=128, output_height=128)
        cache_path.write_bytes(png_bytes)
        return png_bytes
    except ImportError:
        logger.warning("[Weather] cairosvg not installed; falling back to OWM icon for %s", icon_code)
        return get_icon_bytes(icon_code, icons_dir)
    except Exception as exc:
        logger.warning("[Weather] cairosvg conversion failed icon=%s: %s", google_name, exc)
        return get_icon_bytes(icon_code, icons_dir)
