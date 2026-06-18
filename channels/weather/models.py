from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


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
    show_forecast: bool = True
    forecast_days: int = 3        # 1–5
    show_humidity: bool = True
    show_wind: bool = True
    show_feels_like: bool = True
    show_high_low: bool = True
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
class Settings:
    api_key: str = ""
    cache_minutes: int = 30

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> Dict[str, Any]:
        d = self.to_dict()
        if d.get("api_key"):
            d["api_key"] = "••••••••" + d["api_key"][-4:]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Settings":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


class DisplayStore:
    """CRUD persistence for WeatherDisplay list."""

    def __init__(self, path: Path):
        self._path = path
        self._displays: List[WeatherDisplay] = self._load()

    def _load(self) -> List[WeatherDisplay]:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                displays = []
                dirty = False
                for d in raw:
                    if not d.get("id"):
                        d["id"] = str(uuid.uuid4())
                        dirty = True
                    displays.append(WeatherDisplay.from_dict(d))
                if dirty:
                    self._path.write_text(json.dumps([x.to_dict() for x in displays], indent=2))
                return displays
            except Exception:
                pass
        return []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([d.to_dict() for d in self._displays], indent=2))

    def all(self) -> List[WeatherDisplay]:
        return list(self._displays)

    def get(self, display_id: str) -> Optional[WeatherDisplay]:
        return next((d for d in self._displays if d.id == display_id), None)

    def create(self, data: Dict[str, Any]) -> WeatherDisplay:
        display = WeatherDisplay.create(data)
        self._displays.append(display)
        self._save()
        return display

    def update(self, display_id: str, data: Dict[str, Any]) -> Optional[WeatherDisplay]:
        display = self.get(display_id)
        if not display:
            return None
        # Preserve id and created_at
        data["id"] = display_id
        data["created_at"] = display.created_at
        updated = WeatherDisplay.from_dict(data)
        self._displays = [updated if d.id == display_id else d for d in self._displays]
        self._save()
        return updated

    def delete(self, display_id: str) -> bool:
        before = len(self._displays)
        self._displays = [d for d in self._displays if d.id != display_id]
        if len(self._displays) < before:
            self._save()
            return True
        return False


class WeatherCache:
    """Caches OWM API responses per (lat, lon, units) to avoid excessive API calls."""

    def __init__(self, path: Path):
        self._path = path
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))

    def _key(self, lat: float, lon: float, units: str) -> str:
        return f"{lat:.2f}_{lon:.2f}_{units}"

    def get(self, lat: float, lon: float, units: str) -> Optional[Dict[str, Any]]:
        return self._data.get(self._key(lat, lon, units))

    def needs_refresh(self, lat: float, lon: float, units: str, ttl_minutes: int) -> bool:
        entry = self.get(lat, lon, units)
        if not entry:
            return True
        return time.time() - entry.get("fetched_at", 0) > ttl_minutes * 60

    def set(self, lat: float, lon: float, units: str, current: Dict, forecast: List) -> None:
        self._data[self._key(lat, lon, units)] = {
            "current": current,
            "forecast": forecast,
            "fetched_at": time.time(),
        }
        self._save()
