"""Tests for weather channel models — verifies mimir_utils migration is correct."""
import json
import time
from pathlib import Path

import pytest

# Add the channel package to sys.path so we can import without a full install
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from channels.weather.models import DisplayStore, Settings, WeatherCache, WeatherDisplay


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert s.api_key == ""
        assert s.cache_minutes == 30

    def test_to_dict(self):
        s = Settings(api_key="abc123", cache_minutes=60)
        d = s.to_dict()
        assert d == {"api_key": "abc123", "cache_minutes": 60}

    def test_to_public_dict_masks_key(self):
        s = Settings(api_key="sk-abc1234567890")
        pub = s.to_public_dict()
        assert pub["api_key"] == "••••••••7890"
        assert "sk-abc" not in pub["api_key"]

    def test_to_public_dict_short_key(self):
        s = Settings(api_key="abc")
        pub = s.to_public_dict()
        assert pub["api_key"] == "••••••••"

    def test_to_public_dict_empty_key_not_masked(self):
        s = Settings(api_key="")
        pub = s.to_public_dict()
        assert pub["api_key"] == ""

    def test_from_dict_full(self):
        s = Settings.from_dict({"api_key": "mykey", "cache_minutes": 45})
        assert s.api_key == "mykey"
        assert s.cache_minutes == 45

    def test_from_dict_ignores_unknown_keys(self):
        s = Settings.from_dict({"api_key": "x", "unknown_field": True, "cache_minutes": 10})
        assert s.api_key == "x"
        assert s.cache_minutes == 10

    def test_from_dict_partial(self):
        s = Settings.from_dict({"api_key": "only-key"})
        assert s.api_key == "only-key"
        assert s.cache_minutes == 30  # default preserved


# ---------------------------------------------------------------------------
# DisplayStore
# ---------------------------------------------------------------------------

@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "displays.json"


@pytest.fixture
def store(store_path):
    return DisplayStore(store_path)


_DISPLAY_DATA = {
    "name": "Office",
    "city_name": "Boston",
    "country": "US",
    "lat": 42.36,
    "lon": -71.06,
    "units": "imperial",
}


class TestDisplayStore:
    def test_empty_on_new_file(self, store):
        assert store.all() == []
        assert store.count() == 0

    def test_create_assigns_uuid_and_created_at(self, store):
        d = store.create(_DISPLAY_DATA)
        assert d.id
        assert d.created_at
        assert d.name == "Office"
        assert d.city_name == "Boston"

    def test_create_persists_to_disk(self, store, store_path):
        store.create(_DISPLAY_DATA)
        raw = json.loads(store_path.read_text())
        assert len(raw) == 1
        assert raw[0]["name"] == "Office"

    def test_all_returns_copy(self, store):
        store.create(_DISPLAY_DATA)
        items = store.all()
        items.clear()
        assert store.count() == 1  # original unaffected

    def test_get_by_id(self, store):
        d = store.create(_DISPLAY_DATA)
        found = store.get(d.id)
        assert found is not None
        assert found.id == d.id

    def test_get_missing_returns_none(self, store):
        assert store.get("does-not-exist") is None

    def test_update_changes_field(self, store):
        d = store.create(_DISPLAY_DATA)
        updated = store.update(d.id, {**_DISPLAY_DATA, "name": "Home"})
        assert updated.name == "Home"
        assert store.get(d.id).name == "Home"

    def test_update_preserves_created_at(self, store):
        d = store.create(_DISPLAY_DATA)
        original_created_at = d.created_at
        updated = store.update(d.id, {**_DISPLAY_DATA, "name": "Home"})
        assert updated.created_at == original_created_at

    def test_update_missing_returns_none(self, store):
        assert store.update("no-such-id", _DISPLAY_DATA) is None

    def test_delete_existing(self, store):
        d = store.create(_DISPLAY_DATA)
        assert store.delete(d.id) is True
        assert store.count() == 0

    def test_delete_missing_returns_false(self, store):
        assert store.delete("ghost") is False

    def test_reload_from_disk(self, store_path):
        s1 = DisplayStore(store_path)
        d = s1.create(_DISPLAY_DATA)
        # Load from same file in a new instance
        s2 = DisplayStore(store_path)
        assert s2.count() == 1
        assert s2.get(d.id).name == "Office"

    def test_reload_assigns_uuid_to_legacy_entries(self, store_path):
        """Entries without 'id' get auto-assigned a UUID on load."""
        store_path.write_text(json.dumps([
            {"name": "Legacy", "city_name": "NYC", "country": "US",
             "lat": 40.7, "lon": -74.0}
        ]))
        s = DisplayStore(store_path)
        items = s.all()
        assert len(items) == 1
        assert items[0].id  # auto-assigned

    def test_create_preserves_explicit_id(self, store):
        d = store.create({**_DISPLAY_DATA, "id": "my-fixed-id"})
        assert d.id == "my-fixed-id"

    def test_update_persists_to_disk(self, store, store_path):
        d = store.create(_DISPLAY_DATA)
        store.update(d.id, {**_DISPLAY_DATA, "name": "Updated"})
        raw = json.loads(store_path.read_text())
        assert raw[0]["name"] == "Updated"


# ---------------------------------------------------------------------------
# WeatherCache
# ---------------------------------------------------------------------------

@pytest.fixture
def cache_path(tmp_path):
    return tmp_path / "weather_cache.json"


@pytest.fixture
def cache(cache_path):
    return WeatherCache(cache_path)


_CURRENT = {"temp": 72, "description": "Clear", "icon": "01d"}
_FORECAST = {"daily": [{"date": "2026-06-27", "temp_min": 65, "temp_max": 80}], "hourly": []}


class TestWeatherCache:
    def test_needs_refresh_when_empty(self, cache):
        assert cache.needs_refresh(42.36, -71.06, "imperial", 30) is True

    def test_set_then_no_refresh_needed(self, cache):
        cache.set(42.36, -71.06, "imperial", _CURRENT, _FORECAST)
        assert cache.needs_refresh(42.36, -71.06, "imperial", 30) is False

    def test_get_returns_entry(self, cache):
        cache.set(42.36, -71.06, "imperial", _CURRENT, _FORECAST)
        entry = cache.get(42.36, -71.06, "imperial")
        assert entry is not None
        assert entry["current"]["temp"] == 72

    def test_get_missing_returns_none(self, cache):
        assert cache.get(0.0, 0.0, "metric") is None

    def test_different_keys_independent(self, cache):
        cache.set(42.36, -71.06, "imperial", _CURRENT, _FORECAST)
        cache.set(51.51, -0.13, "metric", {"temp": 15}, {"daily": [], "hourly": []})
        boston = cache.get(42.36, -71.06, "imperial")
        london = cache.get(51.51, -0.13, "metric")
        assert boston["current"]["temp"] == 72
        assert london["current"]["temp"] == 15

    def test_needs_refresh_after_ttl_expires(self, cache):
        cache.set(42.36, -71.06, "imperial", _CURRENT, _FORECAST)
        # Fake an old fetched_at timestamp
        key = "42.36_-71.06_imperial"
        cache._data[key]["fetched_at"] = time.time() - 3600  # 1 hour ago
        assert cache.needs_refresh(42.36, -71.06, "imperial", 30) is True

    def test_persists_to_disk(self, cache, cache_path):
        cache.set(42.36, -71.06, "imperial", _CURRENT, _FORECAST)
        raw = json.loads(cache_path.read_text())
        assert "42.36_-71.06_imperial" in raw

    def test_reload_from_disk(self, cache_path):
        c1 = WeatherCache(cache_path)
        c1.set(42.36, -71.06, "imperial", _CURRENT, _FORECAST)
        c2 = WeatherCache(cache_path)
        assert c2.get(42.36, -71.06, "imperial") is not None

    def test_get_forecast_returns_dict(self, cache):
        cache.set(42.36, -71.06, "imperial", _CURRENT, _FORECAST)
        fc = cache.get_forecast(42.36, -71.06, "imperial")
        assert "daily" in fc
        assert "hourly" in fc

    def test_get_forecast_upgrades_old_list_format(self, cache):
        """Old cache entries stored forecast as a plain list — upgrade gracefully."""
        key = "42.36_-71.06_imperial"
        cache._data[key] = {
            "current": _CURRENT,
            "forecast": [{"date": "2026-06-27"}],  # old list format
            "fetched_at": time.time(),
        }
        fc = cache.get_forecast(42.36, -71.06, "imperial")
        assert fc["daily"] == [{"date": "2026-06-27"}]
        assert fc["hourly"] == []

    def test_get_forecast_missing_returns_empty(self, cache):
        fc = cache.get_forecast(0.0, 0.0, "metric")
        assert fc == {"daily": [], "hourly": []}

    def test_corrupt_cache_file_starts_empty(self, cache_path):
        cache_path.write_text("not valid json {{{{")
        c = WeatherCache(cache_path)
        assert c.needs_refresh(42.36, -71.06, "imperial", 30) is True
