from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .mimir_utils import JsonCache, JsonStore, SettingsMixin


@dataclass
class WeatherDisplay:
    """A single configured weather display (sub-channel)."""
    id: str
    name: str
    city_name: str
    country: str
    lat: float
    lon: float
    units: str = "imperial"       # "imperial" | "metric"
    layout: str = "auto"          # "auto" | "landscape" | "portrait" | "square"
    theme: str = "dark"           # "dark" | "light"
    style: str = "minimal"        # "minimal" | "modern" | "ios"
    timezone: str = "UTC"         # IANA timezone name e.g. "America/New_York"
    show_forecast: bool = True
    forecast_days: int = 3        # 1–5
    show_hourly: bool = False
    show_humidity: bool = True
    show_wind: bool = True
    show_feels_like: bool = True
    show_high_low: bool = True
    show_uv: bool = False
    show_dew_point: bool = False
    show_visibility: bool = False
    show_air_quality: bool = False
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WeatherDisplay":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def create(cls, data: Dict[str, Any]) -> "WeatherDisplay":
        data = dict(data)
        if not data.get("id"):
            data["id"] = str(uuid.uuid4())
        if not data.get("created_at"):
            data["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return cls.from_dict(data)


@dataclass
class Settings(SettingsMixin):
    api_key: str = ""
    cache_minutes: int = 30


class DisplayStore(JsonStore[WeatherDisplay]):
    def _from_dict(self, d: Dict[str, Any]) -> WeatherDisplay:
        return WeatherDisplay.from_dict(d)

    def _to_dict(self, item: WeatherDisplay) -> Dict[str, Any]:
        return item.to_dict()

    def _new_item(self, data: Dict[str, Any]) -> WeatherDisplay:
        # WeatherDisplay.create() adds UUID + created_at
        return WeatherDisplay.create(data)


class WeatherCache(JsonCache):
    """Caches OWM API responses per (lat, lon, units) to avoid excessive API calls."""

    def _make_key(self, lat: float, lon: float, units: str) -> str:
        return f"{lat:.2f}_{lon:.2f}_{units}"

    def get(self, lat: float, lon: float, units: str) -> Optional[Dict[str, Any]]:
        return self._data.get(self._make_key(lat, lon, units))

    def needs_refresh(self, lat: float, lon: float, units: str, ttl_minutes: int) -> bool:
        entry = self.get(lat, lon, units)
        if not entry:
            return True
        return time.time() - entry.get("fetched_at", 0) > ttl_minutes * 60

    def set(self, lat: float, lon: float, units: str, current: Dict, forecast: Dict) -> None:
        self._data[self._make_key(lat, lon, units)] = {
            "current": current,
            "forecast": forecast,  # {"daily": [...], "hourly": [...]}
            "fetched_at": time.time(),
        }
        self._save()

    def get_forecast(self, lat: float, lon: float, units: str) -> Dict[str, Any]:
        """Returns forecast dict, upgrading old list-format cache entries gracefully."""
        entry = self.get(lat, lon, units)
        if not entry:
            return {"daily": [], "hourly": []}
        raw = entry.get("forecast", [])
        if isinstance(raw, list):
            return {"daily": raw, "hourly": []}
        return raw
