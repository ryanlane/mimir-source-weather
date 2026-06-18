"""HTML-based weather renderer.

Builds a Jinja2 template from weather data and renders it to JPEG bytes via
the server's shared html_renderer_service (Playwright/Chromium).

Raises HtmlRendererUnavailableError if the service isn't available so the
caller can fall back to the PIL renderer.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mimir.channels.weather.web_renderer")

_TEMPLATE_DIR = Path(__file__).parent / "templates"

# OWM icon prefix → (sky_top, sky_bottom) for the iOS gradient
_SKY = {
    "01d": ("#1565C0", "#42A5F5"),
    "01n": ("#0D1B4B", "#1A3A7A"),
    "02d": ("#1976D2", "#64B5F6"),
    "02n": ("#0F2050", "#1E3A80"),
    "03d": ("#455A64", "#90A4AE"),
    "03n": ("#263238", "#455A64"),
    "04d": ("#546E7A", "#90A4AE"),
    "04n": ("#263238", "#455A64"),
    "09d": ("#37474F", "#78909C"),
    "09n": ("#1C2A31", "#37474F"),
    "10d": ("#1A3A5C", "#5B8DB8"),
    "10n": ("#0D1F33", "#1E3A5C"),
    "11d": ("#1A1A2E", "#30304E"),
    "11n": ("#0D0D1A", "#1A1A2E"),
    "13d": ("#90A4AE", "#CFD8DC"),
    "13n": ("#455A64", "#78909C"),
    "50d": ("#607D8B", "#90A4AE"),
    "50n": ("#37474F", "#607D8B"),
}


def _sky_colors(icon_code: str):
    return _SKY.get(icon_code, _SKY.get(icon_code[:3], ("#1565C0", "#42A5F5")))


# HTML styles that route to this renderer
HTML_STYLES = {"minimal-web", "modern-web", "ios-web"}


class WeatherHtmlRenderer:
    def __init__(self, icons_dir: Path) -> None:
        self.icons_dir = icons_dir
        self._jinja = self._make_jinja()

    def _make_jinja(self):
        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape
            env = Environment(
                loader=FileSystemLoader(str(_TEMPLATE_DIR)),
                autoescape=select_autoescape(["html"]),
            )
            # Expose zip() inside templates
            env.globals["zip"] = zip
            return env
        except ImportError:
            logger.warning("[web-renderer] jinja2 not installed — HTML styles unavailable")
            return None

    # ------------------------------------------------------------------
    # Icon helpers

    def _icon_uri(self, icon_code: str, theme: str) -> str:
        """Return a base64 data URI for the icon so the template needs no network."""
        try:
            from .fetcher import get_google_icon_bytes
            raw = get_google_icon_bytes(icon_code, theme, self.icons_dir)
            if raw:
                b64 = base64.b64encode(raw).decode()
                return f"data:image/png;base64,{b64}"
        except Exception as exc:
            logger.debug("[web-renderer] icon load failed %s: %s", icon_code, exc)
        return ""

    # ------------------------------------------------------------------
    # Data preparation

    def _temp(self, value: float, units: str) -> str:
        sym = "°F" if units == "imperial" else "°C"
        return f"{round(value)}{sym}"

    def _speed(self, value: float, units: str) -> str:
        return f"{round(value)} mph" if units == "imperial" else f"{round(value)} m/s"

    def _uv_label(self, uv: float) -> str:
        if uv < 3:  return "Low"
        if uv < 6:  return "Moderate"
        if uv < 8:  return "High"
        if uv < 11: return "Very High"
        return "Extreme"

    def _now_str(self, tz_name: str) -> str:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name or "UTC")
        except Exception:
            from datetime import timezone
            tz = timezone.utc
        return datetime.now(tz).strftime("%-I:%M %p")

    def _layout_for(self, display, width: int, height: int) -> str:
        layout = display.layout
        if layout == "auto":
            aspect = width / height
            layout = "landscape" if aspect >= 1.2 else ("portrait" if aspect <= 0.85 else "square")
        return layout

    def prepare_context(
        self,
        current: Dict,
        forecast: List[Dict],
        cfg,
        width: int,
        height: int,
        hourly: Optional[List[Dict]] = None,
        extras: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Build the Jinja2 template context from weather data and display config."""
        hourly = hourly or []
        extras = extras or {}
        onecall = extras.get("onecall") or {}
        aq = extras.get("air_quality") or {}
        theme = cfg.theme
        units = cfg.units
        layout = self._layout_for(cfg, width, height)

        # Current icon
        icon_code = current["weather"][0]["icon"]
        sky_top, sky_bottom = _sky_colors(icon_code)

        # Details — only include ones the user has enabled
        details: List[Dict] = []
        if cfg.show_feels_like:
            details.append({"label": "Feels Like", "value": self._temp(current["main"]["feels_like"], units)})
        if cfg.show_humidity:
            details.append({"label": "Humidity", "value": f"{current['main']['humidity']}%"})
        if cfg.show_wind:
            details.append({"label": "Wind", "value": self._speed(current["wind"]["speed"], units)})
        if cfg.show_uv and onecall.get("uv_index") is not None:
            uv = onecall["uv_index"]
            details.append({"label": "UV Index", "value": f"{uv:.0f} {self._uv_label(uv)}"})
        if cfg.show_dew_point:
            dp = onecall.get("dew_point")
            if dp is None:
                dp = current["main"]["temp"] - (100 - current["main"]["humidity"]) / 5
            details.append({"label": "Dew Point", "value": self._temp(dp, units)})
        if cfg.show_visibility and current.get("visibility") is not None:
            vis = current["visibility"]
            val = f"{vis / 1609:.1f} mi" if units == "imperial" else f"{vis / 1000:.1f} km"
            details.append({"label": "Visibility", "value": val})
        if cfg.show_air_quality and aq.get("aqi") is not None:
            details.append({"label": "Air Quality", "value": f"AQI {aq['aqi']} · {aq['aqi_label']}"})

        # Hourly slots
        hourly_items = []
        if cfg.show_hourly:
            for slot in (hourly or [])[:8]:
                try:
                    hr = int(slot["dt_txt"][11:13])
                    label = f"{hr % 12 or 12}{'am' if hr < 12 else 'pm'}"
                except Exception:
                    label = "--"
                hourly_items.append({
                    "time":   label,
                    "icon":   self._icon_uri(slot["icon"], theme),
                    "temp":   self._temp(slot["temp"], units),
                    "precip": slot.get("pop", 0),
                })

        # Daily forecast
        forecast_items = []
        if cfg.show_forecast:
            for day in (forecast or [])[:cfg.forecast_days]:
                try:
                    abbr = datetime.strptime(day["date"], "%Y-%m-%d").strftime("%a").upper()
                except Exception:
                    abbr = day["date"][:3].upper()
                forecast_items.append({
                    "day":  abbr,
                    "icon": self._icon_uri(day["icon"], theme),
                    "high": self._temp(day["temp_max"], units),
                    "low":  self._temp(day["temp_min"], units),
                })

        return {
            # Location
            "city":    current.get("name", cfg.city_name),
            "country": current.get("sys", {}).get("country", cfg.country),
            # Current
            "temp":       self._temp(current["main"]["temp"], units),
            "condition":  current["weather"][0]["description"].title(),
            "icon":       self._icon_uri(icon_code, theme),
            "icon_code":  icon_code,
            # H/L
            "high":       self._temp(current["main"]["temp_max"], units) if cfg.show_high_low else None,
            "low":        self._temp(current["main"]["temp_min"], units) if cfg.show_high_low else None,
            # Lists
            "details":  details,
            "hourly":   hourly_items,
            "forecast": forecast_items,
            # Meta
            "updated": self._now_str(cfg.timezone),
            "theme":   theme,
            "layout":  layout,
            "width":   width,
            "height":  height,
            # iOS sky gradient
            "sky_top":    sky_top,
            "sky_bottom": sky_bottom,
        }

    # ------------------------------------------------------------------
    # Public render entry point

    async def render(
        self,
        current: Dict,
        forecast: List[Dict],
        cfg,
        width: int,
        height: int,
        hourly: Optional[List[Dict]] = None,
        extras: Optional[Dict] = None,
    ) -> bytes:
        """Render weather data to JPEG bytes using the HTML template for cfg.style."""
        if self._jinja is None:
            raise RuntimeError("jinja2 not installed")

        try:
            from app.services.html_renderer import (
                HtmlRendererUnavailableError,
                html_renderer_service,
            )
        except ImportError as exc:
            raise RuntimeError("html_renderer_service not available (not running inside Mimir server)") from exc

        if not html_renderer_service.available:
            from app.services.html_renderer import HtmlRendererUnavailableError
            raise HtmlRendererUnavailableError("Chromium not running")

        # Map style → template file
        template_map = {
            "minimal-web": "minimal.html",
            "modern-web":  "modern.html",
            "ios-web":     "ios.html",
        }
        template_name = template_map.get(cfg.style, "minimal.html")

        try:
            template = self._jinja.get_template(template_name)
        except Exception as exc:
            raise RuntimeError(f"Template '{template_name}' not found: {exc}") from exc

        ctx = self.prepare_context(current, forecast, cfg, width, height, hourly, extras)
        html = template.render(**ctx)

        return await html_renderer_service.render(html, width, height)
