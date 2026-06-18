"""Weather channel for Mimir Platform.

Renders live weather images using OpenWeatherMap data. Each configured
city/layout is a sub-channel — assign different displays to different screens.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .models import DisplayStore, Settings, WeatherCache, WeatherDisplay
from .renderer import WeatherRenderer
from . import fetcher as _fetcher

_PLUGIN_DIR = Path(__file__).parent
logger = logging.getLogger("mimir.channels.weather")

# Preview dimensions per layout family
_PREVIEW_SIZES = {
    "landscape": (800, 480),
    "portrait":  (480, 800),
    "square":    (600, 600),
    "auto":      (800, 480),  # default for auto
}


class WeatherChannel:
    def __init__(self, channel_dir: str):
        self.channel_dir = Path(channel_dir)
        self.data_dir = self.channel_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        plugin_json = self.channel_dir / "plugin.json"
        self._meta: Dict[str, Any] = {}
        if plugin_json.exists():
            try:
                self._meta = json.loads(plugin_json.read_text())
            except Exception:
                pass

        self.settings = self._load_settings()
        self.store = DisplayStore(self.data_dir / "displays.json")
        self.cache = WeatherCache(self.data_dir / "weather_cache.json")
        self.renderer = WeatherRenderer(self.data_dir / "icons")
        self.last_error: Optional[str] = None

        logger.info("[Weather] Initialized at %s, %d displays", self.channel_dir, len(self.store.all()))

    @property
    def id(self) -> str:
        return self._meta.get("id", "com.mimir.weather")

    # ------------------------------------------------------------------
    # Settings

    def _settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    def _load_settings(self) -> Settings:
        p = self._settings_path()
        if p.exists():
            try:
                return Settings.from_dict(json.loads(p.read_text()))
            except Exception as exc:
                logger.warning("[Weather] Settings load failed: %s", exc)
        return Settings()

    def _save_settings(self) -> None:
        self._settings_path().write_text(json.dumps(self.settings.to_dict(), indent=2))

    # ------------------------------------------------------------------
    # Weather data (with cache)

    async def _get_weather(self, display: WeatherDisplay) -> Dict[str, Any]:
        """Returns {"current", "forecast", "extras"} — fetches if stale."""
        if not self.settings.api_key:
            raise ValueError("API key not configured")

        needs_refresh = self.cache.needs_refresh(display.lat, display.lon, display.units, self.settings.cache_minutes)

        if not needs_refresh:
            entry = self.cache.get(display.lat, display.lon, display.units)
            extras = await self._get_extras(display)
            return {"current": entry["current"], "forecast": self.cache.get_forecast(display.lat, display.lon, display.units), "extras": extras}

        try:
            current, forecast = await asyncio.gather(
                asyncio.to_thread(_fetcher.get_current_weather, display.lat, display.lon, self.settings.api_key, display.units),
                asyncio.to_thread(_fetcher.get_forecast,        display.lat, display.lon, self.settings.api_key, display.units),
            )
            self.cache.set(display.lat, display.lon, display.units, current, forecast)
            self.last_error = None
        except Exception as exc:
            self.last_error = str(exc)
            entry = self.cache.get(display.lat, display.lon, display.units)
            if entry:
                logger.warning("[Weather] Fetch failed, using stale cache: %s", exc)
                current = entry["current"]
                forecast = self.cache.get_forecast(display.lat, display.lon, display.units)
            else:
                raise

        extras = await self._get_extras(display)
        return {"current": current, "forecast": forecast, "extras": extras}

    async def _get_extras(self, display: WeatherDisplay) -> Dict[str, Any]:
        """Fetches optional data (air quality, UV/dew point) in parallel. Never raises."""
        needs_aq  = display.show_air_quality
        needs_uv  = display.show_uv or display.show_dew_point

        tasks = []
        if needs_aq:
            tasks.append(asyncio.to_thread(_fetcher.get_air_quality, display.lat, display.lon, self.settings.api_key))
        if needs_uv:
            tasks.append(asyncio.to_thread(_fetcher.get_onecall_extras, display.lat, display.lon, self.settings.api_key, display.units))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        extras: Dict[str, Any] = {}
        idx = 0
        if needs_aq:
            r = results[idx]; idx += 1
            extras["air_quality"] = r if isinstance(r, dict) else None
        if needs_uv:
            r = results[idx]; idx += 1
            extras["onecall"] = r if isinstance(r, dict) else None
        return extras

    # ------------------------------------------------------------------
    # Mimir channel protocol

    def get_manifest(self) -> Dict[str, Any]:
        displays = self.store.all()
        return {
            "id": self.id,
            "name": self._meta.get("name", "Weather"),
            "version": self._meta.get("version", "1.0.0"),
            "description": self._meta.get("description", ""),
            "icon": self._meta.get("icon", "cloud"),
            "capabilities": {
                "supports_upload": False,
                "supports_subchannels": True,
            },
            "ui": {
                "components": {"manager": f"/api/channels/{self.id}/ui/manage.esm.js"},
                "elements": {"manager": "x-weather-manager"},
            },
            "healthy": bool(self.settings.api_key) and self.last_error is None,
            "setup_required": not bool(self.settings.api_key),
            "display_count": len(displays),
        }

    def supports_subchannels(self) -> bool:
        return True

    def get_subchannels(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": d.id,
                "name": d.name,
                "image_count": 1,
                "type": "subchannel",
                "city": d.city_name,
                "country": d.country,
                "units": d.units,
                "layout": d.layout,
                "theme": d.theme,
            }
            for d in self.store.all()
        ]

    def get_subchannel(self, subchannel_id: str) -> Optional[Dict[str, Any]]:
        d = self.store.get(subchannel_id)
        return d.to_dict() if d else None

    # ------------------------------------------------------------------
    # Image request

    async def request_image(self, request_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.settings.api_key:
            return {"success": False, "error": "OWM API key not configured — open the channel manager"}

        data = request_data or {}
        display_id = (
            data.get("subchannel_id")
            or data.get("gallery_id")
            or (data.get("settings") or {}).get("subChannelId")
        )

        display = self.store.get(display_id) if display_id else (self.store.all() or [None])[0]
        if not display:
            return {"success": False, "error": "No weather display configured — add one in the channel manager"}

        # Resolve render dimensions
        resolution = (data.get("settings") or {}).get("resolution") or data.get("resolution")
        width, height = 800, 480
        if resolution and len(resolution) == 2:
            try:
                width, height = int(resolution[0]), int(resolution[1])
            except (TypeError, ValueError):
                pass

        try:
            weather = await self._get_weather(display)
            img_bytes = await asyncio.to_thread(
                self.renderer.render,
                weather["current"], weather["forecast"]["daily"], display, width, height,
                weather["forecast"]["hourly"], weather.get("extras"),
            )
            return {
                "success": True,
                "bytes": img_bytes,
                "content_type": "image/jpeg",
                "preferred_transport": "bytes",
            }
        except Exception as exc:
            logger.error("[Weather] Render failed: %s", exc)
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Router

    def get_router(self) -> APIRouter:
        router = APIRouter()
        _ui_dir = _PLUGIN_DIR / "ui"

        @router.get("/ui/{filename:path}")
        async def serve_ui(filename: str):
            file_path = (_ui_dir / filename).resolve()
            try:
                file_path.relative_to(_ui_dir.resolve())
            except ValueError:
                raise HTTPException(403, "Forbidden")
            if not file_path.exists():
                raise HTTPException(404, f"Not found: {filename}")
            ctype = "application/javascript" if filename.endswith(".js") else "text/css"
            return Response(content=file_path.read_bytes(), media_type=ctype,
                            headers={"Cache-Control": "no-cache"})

        @router.get("/manifest")
        async def get_manifest():
            return JSONResponse(self.get_manifest())

        @router.get("/subchannels")
        async def list_subchannels():
            return JSONResponse(self.get_subchannels())

        @router.post("/subchannels")
        async def create_display(request: Request):
            body = await request.json()
            display = self.store.create(body)
            return JSONResponse(display.to_dict(), status_code=201)

        @router.get("/subchannels/{display_id}")
        async def get_display(display_id: str):
            d = self.store.get(display_id)
            if not d:
                raise HTTPException(404, "Display not found")
            return JSONResponse(d.to_dict())

        @router.put("/subchannels/{display_id}")
        async def update_display(display_id: str, request: Request):
            body = await request.json()
            d = self.store.update(display_id, body)
            if not d:
                raise HTTPException(404, "Display not found")
            return JSONResponse(d.to_dict())

        @router.delete("/subchannels/{display_id}")
        async def delete_display(display_id: str):
            if not self.store.delete(display_id):
                raise HTTPException(404, "Display not found")
            return JSONResponse({"success": True})

        @router.get("/subchannels/{display_id}/preview")
        async def preview_display(display_id: str, w: int = 0, h: int = 0):
            d = self.store.get(display_id)
            if not d:
                raise HTTPException(404, "Display not found")
            pw, ph = (w, h) if w and h else _PREVIEW_SIZES.get(d.layout, _PREVIEW_SIZES["auto"])
            if not self.settings.api_key:
                raise HTTPException(400, "API key not configured")
            try:
                weather = await self._get_weather(d)
                img = await asyncio.to_thread(
                    self.renderer.render, weather["current"], weather["forecast"]["daily"], d, pw, ph,
                    weather["forecast"]["hourly"], weather.get("extras"),
                )
                return Response(content=img, media_type="image/jpeg",
                                headers={"Cache-Control": "no-store"})
            except Exception as exc:
                raise HTTPException(500, str(exc))

        @router.post("/preview")
        async def preview_config(request: Request):
            """Render a preview from an unsaved config (used during add/edit flow)."""
            body = await request.json()
            config_data = body.get("config", body)
            pw = int(body.get("w", 800))
            ph = int(body.get("h", 480))

            if not self.settings.api_key:
                raise HTTPException(400, "API key not configured")

            try:
                display = WeatherDisplay.from_dict(config_data)
            except Exception as exc:
                raise HTTPException(422, f"Invalid config: {exc}")

            try:
                weather = await self._get_weather(display)
                img = await asyncio.to_thread(
                    self.renderer.render, weather["current"], weather["forecast"]["daily"], display, pw, ph,
                    weather["forecast"]["hourly"], weather.get("extras"),
                )
                return Response(content=img, media_type="image/jpeg",
                                headers={"Cache-Control": "no-store"})
            except Exception as exc:
                raise HTTPException(500, str(exc))

        @router.get("/settings")
        async def get_settings():
            return JSONResponse(self.settings.to_public_dict())

        @router.put("/settings")
        async def update_settings(request: Request):
            body = await request.json()
            if "api_key" in body and not str(body["api_key"]).startswith("••••"):
                self.settings.api_key = body["api_key"]
            if "cache_minutes" in body:
                self.settings.cache_minutes = int(body["cache_minutes"])
            self._save_settings()
            return JSONResponse({"success": True, "settings": self.settings.to_public_dict()})

        @router.post("/validate-key")
        async def validate_key(request: Request):
            body = await request.json()
            key = body.get("api_key", "").strip()
            result = await asyncio.to_thread(_fetcher.validate_api_key, key)
            if result["valid"]:
                self.settings.api_key = key
                self._save_settings()
            return JSONResponse(result)

        @router.get("/search-city")
        async def search_city(q: str = ""):
            if not q or not self.settings.api_key:
                return JSONResponse([])
            results = await asyncio.to_thread(_fetcher.search_city, q, self.settings.api_key)
            return JSONResponse(results)

        @router.get("/status")
        async def get_status():
            return JSONResponse({
                "displays": self.get_subchannels(),
                "last_error": self.last_error,
                "setup_required": not bool(self.settings.api_key),
                "settings": self.settings.to_public_dict(),
            })

        @router.post("/request-image")
        async def request_image_binary(request: Request):
            body: Dict[str, Any] = {}
            try:
                body = await request.json()
            except Exception:
                pass
            result = await self.request_image(body)
            if not result.get("success"):
                raise HTTPException(500, result.get("error", "render failed"))
            img_bytes = result.get("bytes")
            if not img_bytes:
                raise HTTPException(500, "No image produced")
            fingerprint = hashlib.sha256(img_bytes).hexdigest()[:32]
            return Response(
                content=img_bytes,
                media_type="image/jpeg",
                headers={"X-Content-Fingerprint": fingerprint, "Cache-Control": "no-store"},
            )

        logger.info("[Weather] Router registered, %d displays", len(self.store.all()))
        return router


ChannelClass = WeatherChannel
