"""PIL-based weather image renderer.

Produces a JPEG image for a WeatherDisplay config at any resolution.
Supports three layout families — landscape, portrait, square — each
auto-selected from the aspect ratio when layout='auto'.

Font resolution order:
  1. channels/weather/assets/font.ttf  (user-supplied or pre-installed)
  2. Common Linux/macOS/Windows system fonts
  3. PIL built-in bitmap (always works, small/pixelated at large sizes)

For best results on Docker, add to your image:
  RUN apt-get install -y fonts-dejavu-core
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    from backports.zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # type: ignore

logger = logging.getLogger("mimir.channels.weather.renderer")

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL = True
except ImportError:
    _PIL = False
    logger.error("[Weather] Pillow not installed — rendering disabled")

_PLUGIN_DIR = Path(__file__).parent

_FONT_SEARCH = [
    _PLUGIN_DIR / "assets" / "font.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
    Path("/System/Library/Fonts/Helvetica.ttc"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
]

THEMES = {
    "dark": {
        "bg":        (11,  19,  20),
        "text":      (224, 224, 224),
        "secondary": (136, 136, 136),
        "accent":    (0,   200, 81),
        "divider":   (42,  58,  60),
        "card":      (22,  35,  37),
    },
    "light": {
        "bg":        (245, 245, 245),
        "text":      (26,  26,  26),
        "secondary": (85,  85,  85),
        "accent":    (3,   102, 0),
        "divider":   (200, 200, 200),
        "card":      (255, 255, 255),
    },
    "hc-dark": {
        "bg":        (0,   0,   0),
        "text":      (255, 255, 255),
        "secondary": (200, 200, 200),
        "accent":    (255, 255, 255),
        "divider":   (128, 128, 128),
        "card":      (24,  24,  24),
    },
    "hc-light": {
        "bg":        (255, 255, 255),
        "text":      (0,   0,   0),
        "secondary": (40,  40,  40),
        "accent":    (0,   0,   0),
        "divider":   (150, 150, 150),
        "card":      (220, 220, 220),
    },
}


class WeatherRenderer:
    def __init__(self, icons_dir: Path):
        self.icons_dir = icons_dir
        self.icons_dir.mkdir(parents=True, exist_ok=True)
        self._font_path: Optional[Path] = self._find_font_path()
        self._font_cache: Dict[int, Any] = {}
        self._icon_cache: Dict[str, Any] = {}
        if self._font_path:
            logger.info("[Weather] Using font: %s", self._font_path)
        else:
            logger.warning("[Weather] No TrueType font found — falling back to bitmap; install fonts-dejavu-core for better quality")

    def _find_font_path(self) -> Optional[Path]:
        for p in _FONT_SEARCH:
            if p.exists():
                return p
        return None

    def _font(self, size: int) -> Any:
        if size not in self._font_cache:
            if self._font_path:
                try:
                    self._font_cache[size] = ImageFont.truetype(str(self._font_path), size)
                    return self._font_cache[size]
                except Exception:
                    pass
            self._font_cache[size] = ImageFont.load_default()
        return self._font_cache[size]

    def _load_icon(self, icon_code: str, size: int, theme: str = "dark") -> Optional[Any]:
        key = f"{icon_code}_{size}_{theme}"
        if key in self._icon_cache:
            return self._icon_cache[key]

        from . import fetcher as _f
        raw = _f.get_google_icon_bytes(icon_code, theme, self.icons_dir)
        img = None
        if raw:
            try:
                img = Image.open(io.BytesIO(raw)).convert("RGBA").resize((size, size), Image.LANCZOS)
            except Exception as exc:
                logger.warning("[Weather] Icon resize failed: %s", exc)
        self._icon_cache[key] = img
        return img

    def _paste_icon(self, canvas: Any, icon_code: str, x: int, y: int, size: int, theme: str = "dark") -> None:
        img = self._load_icon(icon_code, size, theme)
        if img:
            canvas.paste(img, (x, y), img)

    def _text_w(self, draw: Any, text: str, font: Any) -> int:
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[2] - bb[0]

    def _draw_center(self, draw: Any, text: str, cx: int, y: int, font: Any, color: tuple) -> None:
        w = self._text_w(draw, text, font)
        draw.text((cx - w // 2, y), text, font=font, fill=color)

    # ------------------------------------------------------------------
    # Public entry point

    def render(self, current: Dict, forecast: List[Dict], display, width: int, height: int,
               hourly: Optional[List[Dict]] = None, extras: Optional[Dict] = None) -> bytes:
        if not _PIL:
            raise RuntimeError("Pillow not installed")

        hourly = hourly or []
        extras = extras or {}

        aspect = width / height
        layout = display.layout
        if layout == "auto":
            layout = "landscape" if aspect >= 1.2 else ("portrait" if aspect <= 0.85 else "square")

        style = getattr(display, "style", "minimal")
        t = THEMES.get(display.theme, THEMES["dark"])
        canvas = Image.new("RGB", (width, height), t["bg"])
        draw = ImageDraw.Draw(canvas)

        args = (canvas, draw, current, forecast, display, width, height, t, hourly, extras)
        if style == "modern":
            dispatch = {"landscape": self._modern_landscape, "portrait": self._modern_portrait, "square": self._modern_square}
        elif style == "ios":
            dispatch = {"landscape": self._ios_landscape, "portrait": self._ios_portrait, "square": self._ios_square}
        else:
            dispatch = {"landscape": self._landscape, "portrait": self._portrait, "square": self._square}

        dispatch[layout](*args)

        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=92, optimize=True)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Helpers

    @staticmethod
    def _now_str(tz_name: str) -> str:
        try:
            tz = ZoneInfo(tz_name or "UTC")
        except (ZoneInfoNotFoundError, Exception):
            tz = ZoneInfo("UTC")
        return datetime.now(tz).strftime("%-I:%M %p")

    @staticmethod
    def _temp(value: float, units: str) -> str:
        sym = "°F" if units == "imperial" else "°C"
        return f"{round(value)}{sym}"

    @staticmethod
    def _speed(value: float, units: str) -> str:
        return f"{round(value)} mph" if units == "imperial" else f"{round(value)} m/s"

    @staticmethod
    def _day_abbr(date_str: str) -> str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a").upper()
        except Exception:
            return date_str[:3].upper()

    # ------------------------------------------------------------------
    # Landscape layout

    def _landscape(self, canvas, draw, current, forecast, cfg, W, H, t, hourly=None, extras=None):
        pad = max(20, W // 40)
        split = int(W * 0.60)

        fs_city   = max(14, H // 22)
        fs_temp   = max(56, H // 4)
        fs_cond   = max(13, H // 28)
        fs_detail = max(11, H // 34)
        fs_fday   = max(11, H // 40)
        fs_ftemp  = max(11, H // 38)

        # ── Left panel ──────────────────────────────────────────────────
        city = f"{current.get('name', cfg.city_name)}, {current.get('sys', {}).get('country', cfg.country)}"
        draw.text((pad, pad), city, font=self._font(fs_city), fill=t["secondary"])

        icon_size = min(H // 3, split // 4)
        icon_y = pad + fs_city + pad // 2
        self._paste_icon(canvas, current["weather"][0]["icon"], pad, icon_y, icon_size, cfg.theme)

        # Temperature beside icon
        temp_str = self._temp(current["main"]["temp"], cfg.units)
        temp_font = self._font(fs_temp)
        th = draw.textbbox((0, 0), temp_str, font=temp_font)[3]
        ty = icon_y + (icon_size - th) // 2
        draw.text((pad + icon_size + pad // 2, ty), temp_str, font=temp_font, fill=t["text"])

        cy = icon_y + icon_size + pad // 2

        condition = current["weather"][0]["description"].title()
        draw.text((pad, cy), condition, font=self._font(fs_cond), fill=t["secondary"])
        cy += fs_cond + pad // 3

        # H/L and feels like
        bits1 = []
        if cfg.show_high_low:
            bits1.append(f"H:{self._temp(current['main']['temp_max'], cfg.units)}  L:{self._temp(current['main']['temp_min'], cfg.units)}")
        if cfg.show_feels_like:
            bits1.append(f"Feels {self._temp(current['main']['feels_like'], cfg.units)}")
        if bits1:
            draw.text((pad, cy), "   ·   ".join(bits1), font=self._font(fs_detail), fill=t["secondary"])
            cy += fs_detail + pad // 4

        bits2 = []
        if cfg.show_humidity:
            bits2.append(f"Humidity {current['main']['humidity']}%")
        if cfg.show_wind:
            bits2.append(f"Wind {self._speed(current['wind']['speed'], cfg.units)}")
        if bits2:
            draw.text((pad, cy), "   ·   ".join(bits2), font=self._font(fs_detail), fill=t["secondary"])

        # ── Divider ─────────────────────────────────────────────────────
        draw.line([(split, pad), (split, H - pad)], fill=t["divider"], width=1)

        # ── Right panel: forecast ────────────────────────────────────────
        if cfg.show_forecast and forecast:
            days = forecast[:cfg.forecast_days]
            rw = W - split - pad * 2
            col_w = rw // len(days)
            icon_sm = min(col_w - 8, H // 8)

            for i, day in enumerate(days):
                cx = split + pad + i * col_w + col_w // 2
                fy = pad
                self._draw_center(draw, self._day_abbr(day["date"]), cx, fy, self._font(fs_fday), t["secondary"])
                fy += fs_fday + 4
                self._paste_icon(canvas, day["icon"], cx - icon_sm // 2, fy, icon_sm, cfg.theme)
                fy += icon_sm + 4
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx, fy, self._font(fs_ftemp), t["text"])
                fy += fs_ftemp + 2
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx, fy, self._font(fs_ftemp), t["secondary"])

        # Timestamp bottom-right
        ts = f"Updated {self._now_str(cfg.timezone)}"
        tw = self._text_w(draw, ts, self._font(fs_detail))
        draw.text((W - pad - tw, H - pad - fs_detail), ts, font=self._font(fs_detail), fill=t["secondary"])

    # ------------------------------------------------------------------
    # Portrait layout

    def _portrait(self, canvas, draw, current, forecast, cfg, W, H, t, hourly=None, extras=None):
        pad = max(14, W // 28)

        fs_city   = max(12, W // 24)
        fs_temp   = max(48, W // 5)      # was W//4 — smaller so content sits higher
        fs_cond   = max(12, W // 28)
        fs_detail = max(11, W // 32)
        fs_fday   = max(10, W // 34)

        cy = pad

        city = f"{current.get('name', cfg.city_name)}, {current.get('sys', {}).get('country', cfg.country)}"
        self._draw_center(draw, city, W // 2, cy, self._font(fs_city), t["secondary"])
        cy += fs_city + pad // 3          # tighter gap: was + pad

        icon_size = min(W // 4, H // 9, 96)  # smaller + capped: was min(W//3, H//8)
        self._paste_icon(canvas, current["weather"][0]["icon"], W // 2 - icon_size // 2, cy, icon_size, cfg.theme)
        cy += icon_size + pad // 3

        temp_str = self._temp(current["main"]["temp"], cfg.units)
        self._draw_center(draw, temp_str, W // 2, cy, self._font(fs_temp), t["text"])
        cy += fs_temp + pad // 3

        self._draw_center(draw, current["weather"][0]["description"].title(), W // 2, cy, self._font(fs_cond), t["secondary"])
        cy += fs_cond + pad // 3

        if cfg.show_high_low:
            hl = f"H:{self._temp(current['main']['temp_max'], cfg.units)}   L:{self._temp(current['main']['temp_min'], cfg.units)}"
            self._draw_center(draw, hl, W // 2, cy, self._font(fs_detail), t["secondary"])
            cy += fs_detail + pad // 5

        if cfg.show_feels_like:
            self._draw_center(draw, f"Feels like {self._temp(current['main']['feels_like'], cfg.units)}",
                              W // 2, cy, self._font(fs_detail), t["secondary"])
            cy += fs_detail + pad // 5

        row = []
        if cfg.show_humidity:
            row.append(f"Humidity {current['main']['humidity']}%")
        if cfg.show_wind:
            row.append(f"Wind {self._speed(current['wind']['speed'], cfg.units)}")
        if row:
            self._draw_center(draw, "  ·  ".join(row), W // 2, cy, self._font(fs_detail), t["secondary"])
            cy += fs_detail + pad // 2

        draw.line([(pad * 2, cy), (W - pad * 2, cy)], fill=t["divider"], width=1)
        cy += pad // 2

        if cfg.show_forecast and forecast:
            days = forecast[:cfg.forecast_days]
            col_w = (W - pad * 2) // len(days)
            icon_sm = min(col_w - 8, W // 7)

            for i, day in enumerate(days):
                cx = pad + i * col_w + col_w // 2
                fy = cy + pad // 3
                self._draw_center(draw, self._day_abbr(day["date"]), cx, fy, self._font(fs_fday), t["secondary"])
                fy += fs_fday + 4
                self._paste_icon(canvas, day["icon"], cx - icon_sm // 2, fy, icon_sm, cfg.theme)
                fy += icon_sm + 4
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx, fy, self._font(fs_fday), t["text"])
                fy += fs_fday + 2
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx, fy, self._font(fs_fday), t["secondary"])

        self._draw_center(draw, f"Updated {self._now_str(cfg.timezone)}",
                          W // 2, H - pad - fs_detail, self._font(fs_detail), t["secondary"])

    # ------------------------------------------------------------------
    # Square layout

    def _square(self, canvas, draw, current, forecast, cfg, W, H, t, hourly=None, extras=None):
        pad = max(14, W // 36)

        fs_city   = max(11, W // 32)
        fs_temp   = max(38, W // 7)      # was W//6 — smaller so details+forecast fit
        fs_cond   = max(11, W // 34)
        fs_detail = max(10, W // 40)
        fs_fday   = max(9,  W // 44)

        cy = pad

        city = f"{current.get('name', cfg.city_name)}, {current.get('sys', {}).get('country', cfg.country)}"
        self._draw_center(draw, city, W // 2, cy, self._font(fs_city), t["secondary"])
        cy += fs_city + pad // 3

        # Icon + temp side-by-side, smaller icon so temp has room
        icon_size = min(W // 5, H // 7)
        icon_x = W // 4 - icon_size // 2
        self._paste_icon(canvas, current["weather"][0]["icon"], icon_x, cy, icon_size, cfg.theme)

        temp_str = self._temp(current["main"]["temp"], cfg.units)
        tf = self._font(fs_temp)
        bb = draw.textbbox((0, 0), temp_str, font=tf)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        draw.text((W * 3 // 4 - tw // 2, cy + (icon_size - th) // 2), temp_str, font=tf, fill=t["text"])
        cy += icon_size + pad // 3

        self._draw_center(draw, current["weather"][0]["description"].title(), W // 2, cy, self._font(fs_cond), t["secondary"])
        cy += fs_cond + pad // 3

        # Compact details: 2 rows instead of 4
        # Row 1: H/L
        # Row 2: Feels · Humidity · Wind
        df = self._font(fs_detail)
        row_h = fs_detail + 3
        detail_rows = []
        if cfg.show_high_low:
            detail_rows.append(
                f"H:{self._temp(current['main']['temp_max'], cfg.units)}  "
                f"L:{self._temp(current['main']['temp_min'], cfg.units)}"
            )
        sub = []
        if cfg.show_feels_like:
            sub.append(f"Feels {self._temp(current['main']['feels_like'], cfg.units)}")
        if cfg.show_humidity:
            sub.append(f"Hum {current['main']['humidity']}%")
        if cfg.show_wind:
            sub.append(f"Wind {self._speed(current['wind']['speed'], cfg.units)}")
        if sub:
            detail_rows.append("  ·  ".join(sub))

        for row in detail_rows:
            self._draw_center(draw, row, W // 2, cy, df, t["secondary"])
            cy += row_h
        cy += pad // 3

        draw.line([(pad * 2, cy), (W - pad * 2, cy)], fill=t["divider"], width=1)
        cy += pad // 2

        if cfg.show_forecast and forecast:
            days = forecast[:min(cfg.forecast_days, 5)]
            col_w = (W - pad * 2) // len(days)
            icon_sm = min(col_w - 6, W // 12)  # smaller forecast icons

            for i, day in enumerate(days):
                cx = pad + i * col_w + col_w // 2
                fy = cy + pad // 4
                self._draw_center(draw, self._day_abbr(day["date"]), cx, fy, self._font(fs_fday), t["secondary"])
                fy += fs_fday + 3
                self._paste_icon(canvas, day["icon"], cx - icon_sm // 2, fy, icon_sm, cfg.theme)
                fy += icon_sm + 3
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx, fy, self._font(fs_fday), t["text"])
                fy += fs_fday + 2
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx, fy, self._font(fs_fday), t["secondary"])

        self._draw_center(draw, f"Updated {self._now_str(cfg.timezone)}",
                          W // 2, H - pad - fs_detail, self._font(fs_detail), t["secondary"])

    # ------------------------------------------------------------------
    # Shared extras helpers

    def _extras_lines(self, current, cfg, extras):
        """Returns list of (label, value) pairs for enabled extras modules."""
        onecall = (extras or {}).get("onecall") or {}
        aq      = (extras or {}).get("air_quality") or {}
        lines = []

        if cfg.show_uv:
            uv = onecall.get("uv_index")
            if uv is not None:
                lines.append(("UV", f"{uv:.0f} {self._uv_label(uv)}"))

        if cfg.show_dew_point:
            dp = onecall.get("dew_point")
            if dp is None:
                t_val = current["main"]["temp"]
                rh    = current["main"]["humidity"]
                dp    = t_val - (100 - rh) / 5
            lines.append(("Dew Pt", self._temp(dp, cfg.units)))

        if cfg.show_visibility:
            vis = current.get("visibility")
            if vis is not None:
                if cfg.units == "imperial":
                    lines.append(("Visibility", f"{vis / 1609:.1f} mi"))
                else:
                    lines.append(("Visibility", f"{vis / 1000:.1f} km"))

        if cfg.show_air_quality and aq.get("aqi") is not None:
            lines.append(("Air Quality", f"AQI {aq['aqi']} - {aq['aqi_label']}"))

        return lines

    @staticmethod
    def _uv_label(uv):
        if uv < 3:  return "Low"
        if uv < 6:  return "Moderate"
        if uv < 8:  return "High"
        if uv < 11: return "Very High"
        return "Extreme"

    def _draw_hourly(self, canvas, draw, hourly, cfg, x, y, w, h, t):
        """Renders a horizontal hourly strip inside the box (x,y,w,h)."""
        if not hourly:
            return
        slots = hourly[:8]
        slot_w = w // len(slots)
        icon_sm = min(slot_w - 6, h // 3, 32)
        fs = max(9, h // 6)

        for i, slot in enumerate(slots):
            cx = x + i * slot_w + slot_w // 2
            sy = y + 4
            try:
                hr = int(slot["dt_txt"][11:13])
                label = f"{hr % 12 or 12}{'am' if hr < 12 else 'pm'}"
            except Exception:
                label = "--"
            self._draw_center(draw, label, cx, sy, self._font(fs), t["secondary"])
            sy += fs + 2
            self._paste_icon(canvas, slot["icon"], cx - icon_sm // 2, sy, icon_sm, cfg.theme)
            sy += icon_sm + 2
            self._draw_center(draw, self._temp(slot["temp"], cfg.units), cx, sy, self._font(fs), t["text"])
            sy += fs + 1
            if slot.get("pop"):
                self._draw_center(draw, f"{slot['pop']}%", cx, sy, self._font(fs), t["accent"])

    # ------------------------------------------------------------------
    # Modern style

    def _modern_landscape(self, canvas, draw, current, forecast, cfg, W, H, t, hourly=None, extras=None):
        pad = max(18, W // 44)
        extras = extras or {}
        for x in range(6):
            col = tuple(int(c * (1 - x / 6)) for c in t["accent"])
            draw.rectangle([(x, 0), (x, H)], fill=col)

        fs_city = max(13, H // 24)
        fs_temp = max(64, H // 3)
        fs_cond = max(14, H // 26)
        fs_det  = max(11, H // 34)
        fs_fday = max(11, H // 38)
        split   = int(W * 0.58)

        city = f"{current.get('name', cfg.city_name)},  {current.get('sys', {}).get('country', cfg.country)}"
        draw.text((pad + 10, pad), city.upper(), font=self._font(fs_city), fill=t["secondary"])

        icon_bg_size = min(H - pad * 2, split // 2)
        ghost = self._load_icon(current["weather"][0]["icon"], icon_bg_size, cfg.theme)
        if ghost:
            faded = ghost.copy()
            r, g, b, a = faded.split()
            a = a.point(lambda p: p * 25 // 100)
            faded = Image.merge("RGBA", (r, g, b, a))
            canvas.paste(faded, (split // 2 - icon_bg_size // 2, pad), faded)

        draw.text((pad + 12, pad + fs_city + 6), self._temp(current["main"]["temp"], cfg.units),
                  font=self._font(fs_temp), fill=t["text"])

        cond = current["weather"][0]["description"].title()
        cw = self._text_w(draw, cond, self._font(fs_cond)) + 16
        cy_pill = pad + fs_city + 6 + fs_temp + 6
        draw.rounded_rectangle([(pad + 10, cy_pill), (pad + 10 + cw, cy_pill + fs_cond + 10)], radius=6, fill=t["card"])
        draw.text((pad + 18, cy_pill + 5), cond, font=self._font(fs_cond), fill=t["accent"])
        cy = cy_pill + fs_cond + 18

        for flag, fn in [
            (cfg.show_high_low,   lambda: f"H {self._temp(current['main']['temp_max'], cfg.units)}  L {self._temp(current['main']['temp_min'], cfg.units)}"),
            (cfg.show_feels_like, lambda: f"Feels {self._temp(current['main']['feels_like'], cfg.units)}"),
            (cfg.show_humidity,   lambda: f"Humidity {current['main']['humidity']}%"),
            (cfg.show_wind,       lambda: f"Wind {self._speed(current['wind']['speed'], cfg.units)}"),
        ]:
            if flag:
                draw.text((pad + 12, cy), fn(), font=self._font(fs_det), fill=t["secondary"])
                cy += fs_det + 4
        for label, val in self._extras_lines(current, cfg, extras):
            draw.text((pad + 12, cy), f"{label}  {val}", font=self._font(fs_det), fill=t["secondary"])
            cy += fs_det + 4

        draw.line([(split, pad), (split, H - pad)], fill=t["divider"], width=1)

        rw = W - split - pad
        rx = split + pad // 2
        if cfg.show_hourly and hourly:
            hourly_h = H // 5
            self._draw_hourly(canvas, draw, hourly, cfg, rx, pad, rw, hourly_h,
                              {**t, "secondary": t["secondary"], "text": t["text"], "accent": t["accent"]})
            fc_y = pad + hourly_h + pad // 2
        else:
            fc_y = pad

        if cfg.show_forecast and forecast:
            days = forecast[:cfg.forecast_days]
            col_w = rw // len(days)
            icon_sm = min(col_w - 8, (H - fc_y - pad) // 4)
            for i, day in enumerate(days):
                cx2 = rx + i * col_w + col_w // 2
                fy = fc_y
                self._draw_center(draw, self._day_abbr(day["date"]), cx2, fy, self._font(fs_fday), t["secondary"])
                fy += fs_fday + 4
                self._paste_icon(canvas, day["icon"], cx2 - icon_sm // 2, fy, icon_sm, cfg.theme)
                fy += icon_sm + 4
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx2, fy, self._font(fs_fday), t["text"])
                fy += fs_fday + 2
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx2, fy, self._font(fs_fday), t["secondary"])

        ts = f"Updated {self._now_str(cfg.timezone)}"
        tw = self._text_w(draw, ts, self._font(fs_det))
        draw.text((W - pad - tw, H - pad - fs_det), ts, font=self._font(fs_det), fill=t["divider"])

    def _modern_portrait(self, canvas, draw, current, forecast, cfg, W, H, t, hourly=None, extras=None):
        pad = max(14, W // 28)
        extras = extras or {}
        bar_h = max(4, H // 120)
        draw.rectangle([(0, 0), (W, bar_h)], fill=t["accent"])

        fs_city = max(12, W // 24)
        fs_temp = max(52, W // 5)
        fs_cond = max(12, W // 30)
        fs_det  = max(10, W // 34)
        fs_fday = max(10, W // 36)
        cy = bar_h + pad

        city = f"{current.get('name', cfg.city_name)}, {current.get('sys', {}).get('country', cfg.country)}"
        self._draw_center(draw, city.upper(), W // 2, cy, self._font(fs_city), t["secondary"])
        cy += fs_city + pad // 2

        icon_size = min(W // 4, 96)
        self._paste_icon(canvas, current["weather"][0]["icon"], W // 2 - icon_size // 2, cy, icon_size, cfg.theme)
        cy += icon_size + pad // 4

        self._draw_center(draw, self._temp(current["main"]["temp"], cfg.units), W // 2, cy, self._font(fs_temp), t["text"])
        cy += fs_temp + pad // 4

        self._draw_center(draw, current["weather"][0]["description"].title(), W // 2, cy, self._font(fs_cond), t["accent"])
        cy += fs_cond + pad // 3

        details = []
        if cfg.show_high_low:
            details += [f"H {self._temp(current['main']['temp_max'], cfg.units)}", f"L {self._temp(current['main']['temp_min'], cfg.units)}"]
        if cfg.show_feels_like: details.append(f"Feels {self._temp(current['main']['feels_like'], cfg.units)}")
        if cfg.show_humidity:   details.append(f"Hum {current['main']['humidity']}%")
        if cfg.show_wind:       details.append(f"Wind {self._speed(current['wind']['speed'], cfg.units)}")
        for label, val in self._extras_lines(current, cfg, extras):
            details.append(f"{label} {val}")

        col_w2 = W // 2 - pad
        df = self._font(fs_det)
        for i in range(0, len(details), 2):
            left  = details[i]
            right = details[i + 1] if i + 1 < len(details) else ""
            lw = self._text_w(draw, left, df)
            draw.text((W // 2 - col_w2 // 2 - lw // 2, cy), left, font=df, fill=t["secondary"])
            if right:
                rw2 = self._text_w(draw, right, df)
                draw.text((W // 2 + col_w2 // 2 - rw2 // 2, cy), right, font=df, fill=t["secondary"])
            cy += fs_det + 4
        cy += pad // 3

        if cfg.show_hourly and hourly:
            draw.line([(pad * 2, cy), (W - pad * 2, cy)], fill=t["divider"], width=1)
            cy += pad // 3
            hourly_h = H // 7
            self._draw_hourly(canvas, draw, hourly, cfg, pad, cy, W - pad * 2, hourly_h, t)
            cy += hourly_h + pad // 3

        if cfg.show_forecast and forecast:
            draw.line([(pad * 2, cy), (W - pad * 2, cy)], fill=t["divider"], width=1)
            cy += pad // 3
            days = forecast[:cfg.forecast_days]
            col_w = (W - pad * 2) // len(days)
            icon_sm = min(col_w - 8, W // 7)
            for i, day in enumerate(days):
                cx2 = pad + i * col_w + col_w // 2
                fy = cy + pad // 4
                self._draw_center(draw, self._day_abbr(day["date"]), cx2, fy, self._font(fs_fday), t["secondary"])
                fy += fs_fday + 3
                self._paste_icon(canvas, day["icon"], cx2 - icon_sm // 2, fy, icon_sm, cfg.theme)
                fy += icon_sm + 3
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx2, fy, self._font(fs_fday), t["text"])
                fy += fs_fday + 2
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx2, fy, self._font(fs_fday), t["secondary"])

        self._draw_center(draw, f"Updated {self._now_str(cfg.timezone)}",
                          W // 2, H - pad - fs_det, self._font(fs_det), t["divider"])

    def _modern_square(self, canvas, draw, current, forecast, cfg, W, H, t, hourly=None, extras=None):
        pad = max(12, W // 36)
        extras = extras or {}
        draw.polygon([(0, 0), (W // 6, 0), (0, W // 6)], fill=t["accent"])

        fs_city = max(10, W // 34)
        fs_temp = max(40, W // 7)
        fs_cond = max(10, W // 36)
        fs_det  = max(9,  W // 42)
        fs_fday = max(9,  W // 46)
        cy = pad + 2

        city = f"{current.get('name', cfg.city_name)}, {current.get('sys', {}).get('country', cfg.country)}"
        self._draw_center(draw, city.upper(), W // 2, cy, self._font(fs_city), t["secondary"])
        cy += fs_city + pad // 3

        icon_size = min(W // 5, H // 7)
        self._paste_icon(canvas, current["weather"][0]["icon"], W // 4 - icon_size // 2, cy, icon_size, cfg.theme)
        temp_str = self._temp(current["main"]["temp"], cfg.units)
        tf = self._font(fs_temp)
        bb = draw.textbbox((0, 0), temp_str, font=tf)
        draw.text((W * 3 // 4 - (bb[2] - bb[0]) // 2, cy + (icon_size - (bb[3] - bb[1])) // 2),
                  temp_str, font=tf, fill=t["text"])
        cy += icon_size + pad // 3

        self._draw_center(draw, current["weather"][0]["description"].title(),
                          W // 2, cy, self._font(fs_cond), t["accent"])
        cy += fs_cond + pad // 4

        df = self._font(fs_det)
        rh = fs_det + 3
        if cfg.show_high_low:
            self._draw_center(draw,
                f"H:{self._temp(current['main']['temp_max'], cfg.units)}  L:{self._temp(current['main']['temp_min'], cfg.units)}",
                W // 2, cy, df, t["secondary"])
            cy += rh
        sub = []
        if cfg.show_feels_like: sub.append(f"Feels {self._temp(current['main']['feels_like'], cfg.units)}")
        if cfg.show_humidity:   sub.append(f"Hum {current['main']['humidity']}%")
        if cfg.show_wind:       sub.append(f"Wind {self._speed(current['wind']['speed'], cfg.units)}")
        if sub:
            self._draw_center(draw, "  ·  ".join(sub), W // 2, cy, df, t["secondary"])
            cy += rh
        for label, val in self._extras_lines(current, cfg, extras):
            self._draw_center(draw, f"{label}: {val}", W // 2, cy, df, t["secondary"])
            cy += rh
        cy += pad // 4

        draw.line([(pad * 2, cy), (W - pad * 2, cy)], fill=t["divider"], width=1)
        cy += pad // 3

        if cfg.show_hourly and hourly and cy + H // 6 < H - pad * 3:
            hourly_h = H // 7
            self._draw_hourly(canvas, draw, hourly, cfg, pad, cy, W - pad * 2, hourly_h, t)
            cy += hourly_h + pad // 3
            draw.line([(pad * 2, cy), (W - pad * 2, cy)], fill=t["divider"], width=1)
            cy += pad // 3

        if cfg.show_forecast and forecast:
            days = forecast[:min(cfg.forecast_days, 5)]
            col_w = (W - pad * 2) // len(days)
            icon_sm = min(col_w - 6, W // 12)
            for i, day in enumerate(days):
                cx2 = pad + i * col_w + col_w // 2
                fy = cy + pad // 4
                self._draw_center(draw, self._day_abbr(day["date"]), cx2, fy, self._font(fs_fday), t["secondary"])
                fy += fs_fday + 2
                self._paste_icon(canvas, day["icon"], cx2 - icon_sm // 2, fy, icon_sm, cfg.theme)
                fy += icon_sm + 2
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx2, fy, self._font(fs_fday), t["text"])
                fy += fs_fday + 1
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx2, fy, self._font(fs_fday), t["secondary"])

        self._draw_center(draw, f"Updated {self._now_str(cfg.timezone)}",
                          W // 2, H - pad - fs_det, self._font(fs_det), t["divider"])

    # ------------------------------------------------------------------
    # iOS style

    _SKY_GRADIENTS = {
        "01": [(15, 94, 156),   (91, 178, 229)],
        "02": [(55, 100, 150),  (130, 170, 210)],
        "03": [(80, 100, 130),  (150, 170, 200)],
        "04": [(70, 80, 100),   (130, 145, 165)],
        "09": [(50, 65, 90),    (100, 120, 150)],
        "10": [(45, 60, 85),    (95, 115, 145)],
        "11": [(30, 35, 55),    (75, 85, 115)],
        "13": [(130, 150, 175), (190, 210, 230)],
        "50": [(100, 110, 120), (155, 165, 175)],
    }
    _SKY_NIGHT = [(10, 15, 40), (30, 45, 85)]

    def _sky_gradient(self, canvas, icon_code, W, H):
        key = icon_code[:2]
        is_night = icon_code.endswith("n")
        stops = self._SKY_NIGHT if is_night else self._SKY_GRADIENTS.get(key, [(30, 60, 120), (100, 150, 200)])
        top, bot = stops[0], stops[1]
        draw = ImageDraw.Draw(canvas)
        for y in range(H):
            r = round(top[0] + (bot[0] - top[0]) * y / H)
            g = round(top[1] + (bot[1] - top[1]) * y / H)
            b = round(top[2] + (bot[2] - top[2]) * y / H)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

    def _frosted_rect(self, canvas, x, y, w, h):
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rounded_rectangle([(x, y), (x + w, y + h)], radius=max(8, w // 20), fill=(255, 255, 255, 38))
        combined = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        canvas.paste(combined)

    def _ios_landscape(self, canvas, draw, current, forecast, cfg, W, H, t, hourly=None, extras=None):
        extras = extras or {}
        icon_code = current["weather"][0]["icon"]
        self._sky_gradient(canvas, icon_code, W, H)
        draw = ImageDraw.Draw(canvas)

        pad   = max(16, W // 48)
        white = (255, 255, 255)
        dim   = (200, 220, 255)

        fs_city = max(13, H // 26)
        fs_temp = max(60, H // 3)
        fs_cond = max(13, H // 28)
        fs_det  = max(11, H // 36)
        fs_fday = max(10, H // 40)
        split   = int(W * 0.45)

        city = f"{current.get('name', cfg.city_name)}, {current.get('sys', {}).get('country', cfg.country)}"
        draw.text((pad, pad), city, font=self._font(fs_city), fill=dim)
        draw.text((pad, pad + fs_city + 4), self._temp(current["main"]["temp"], cfg.units),
                  font=self._font(fs_temp), fill=white)

        cy = pad + fs_city + 4 + fs_temp + 4
        draw.text((pad, cy), current["weather"][0]["description"].title(), font=self._font(fs_cond), fill=dim)
        cy += fs_cond + pad // 2

        for flag, fn in [
            (cfg.show_high_low,   lambda: f"H:{self._temp(current['main']['temp_max'], cfg.units)}  L:{self._temp(current['main']['temp_min'], cfg.units)}"),
            (cfg.show_feels_like, lambda: f"Feels {self._temp(current['main']['feels_like'], cfg.units)}"),
            (cfg.show_humidity,   lambda: f"Humidity {current['main']['humidity']}%"),
            (cfg.show_wind,       lambda: f"Wind {self._speed(current['wind']['speed'], cfg.units)}"),
        ]:
            if flag:
                draw.text((pad, cy), fn(), font=self._font(fs_det), fill=dim)
                cy += fs_det + 4
        for label, val in self._extras_lines(current, cfg, extras):
            draw.text((pad, cy), f"{label}: {val}", font=self._font(fs_det), fill=dim)
            cy += fs_det + 4

        rw = W - split - pad
        rx = split
        ios_t = {**t, "text": white, "secondary": dim, "accent": (120, 220, 255)}

        if cfg.show_hourly and hourly:
            hourly_h = H // 4
            self._frosted_rect(canvas, rx, pad, rw, hourly_h)
            draw = ImageDraw.Draw(canvas)
            self._draw_hourly(canvas, draw, hourly, cfg, rx + pad // 2, pad + 4, rw - pad, hourly_h - 8, ios_t)
            draw = ImageDraw.Draw(canvas)
            fc_y = pad + hourly_h + pad // 2
        else:
            fc_y = pad

        if cfg.show_forecast and forecast:
            days = forecast[:cfg.forecast_days]
            fc_h = H - fc_y - pad
            self._frosted_rect(canvas, rx, fc_y, rw, fc_h)
            draw = ImageDraw.Draw(canvas)
            col_w = rw // len(days)
            icon_sm = min(col_w - 8, fc_h // 4)
            for i, day in enumerate(days):
                cx2 = rx + i * col_w + col_w // 2
                fy = fc_y + pad // 3
                self._draw_center(draw, self._day_abbr(day["date"]), cx2, fy, self._font(fs_fday), dim)
                fy += fs_fday + 3
                self._paste_icon(canvas, day["icon"], cx2 - icon_sm // 2, fy, icon_sm, "light")
                fy += icon_sm + 3
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx2, fy, self._font(fs_fday), white)
                fy += fs_fday + 2
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx2, fy, self._font(fs_fday), dim)

        ts = f"Updated {self._now_str(cfg.timezone)}"
        draw.text((W - pad - self._text_w(draw, ts, self._font(fs_det)), H - pad - fs_det),
                  ts, font=self._font(fs_det), fill=dim)

    def _ios_portrait(self, canvas, draw, current, forecast, cfg, W, H, t, hourly=None, extras=None):
        extras = extras or {}
        icon_code = current["weather"][0]["icon"]
        self._sky_gradient(canvas, icon_code, W, H)
        draw = ImageDraw.Draw(canvas)

        pad   = max(14, W // 28)
        white = (255, 255, 255)
        dim   = (200, 220, 255)

        fs_city = max(13, W // 24)
        fs_temp = max(64, W // 4)
        fs_cond = max(13, W // 28)
        fs_det  = max(11, W // 34)
        fs_fday = max(10, W // 38)
        ios_t = {**t, "text": white, "secondary": dim, "accent": (120, 220, 255)}

        cy = pad * 2
        city = f"{current.get('name', cfg.city_name)}, {current.get('sys', {}).get('country', cfg.country)}"
        self._draw_center(draw, city, W // 2, cy, self._font(fs_city), dim)
        cy += fs_city + pad // 3

        icon_size = min(W // 3, 120)
        self._paste_icon(canvas, icon_code, W // 2 - icon_size // 2, cy, icon_size, "light")
        cy += icon_size + pad // 4

        self._draw_center(draw, self._temp(current["main"]["temp"], cfg.units), W // 2, cy, self._font(fs_temp), white)
        cy += fs_temp + pad // 4

        self._draw_center(draw, current["weather"][0]["description"].title(), W // 2, cy, self._font(fs_cond), dim)
        cy += fs_cond + pad // 3

        if cfg.show_high_low:
            hl = f"H:{self._temp(current['main']['temp_max'], cfg.units)}  L:{self._temp(current['main']['temp_min'], cfg.units)}"
            self._draw_center(draw, hl, W // 2, cy, self._font(fs_det), dim)
            cy += fs_det + pad // 3

        if cfg.show_hourly and hourly:
            h_card = H // 6
            self._frosted_rect(canvas, pad, cy, W - pad * 2, h_card)
            draw = ImageDraw.Draw(canvas)
            self._draw_hourly(canvas, draw, hourly, cfg, pad + 4, cy + 4, W - pad * 2 - 8, h_card - 8, ios_t)
            draw = ImageDraw.Draw(canvas)
            cy += h_card + pad // 2

        detail_lines = []
        for flag, fn in [
            (cfg.show_feels_like, lambda: ("Feels Like", self._temp(current["main"]["feels_like"], cfg.units))),
            (cfg.show_humidity,   lambda: ("Humidity",   f"{current['main']['humidity']}%")),
            (cfg.show_wind,       lambda: ("Wind",       self._speed(current["wind"]["speed"], cfg.units))),
        ]:
            if flag: detail_lines.append(fn())
        detail_lines += self._extras_lines(current, cfg, extras)

        if detail_lines:
            card_h = ((len(detail_lines) + 1) // 2) * (fs_det * 2 + 10) + pad
            self._frosted_rect(canvas, pad, cy, W - pad * 2, card_h)
            draw = ImageDraw.Draw(canvas)
            cw = (W - pad * 2) // 2
            ky = cy + pad // 2
            for i, (label, val) in enumerate(detail_lines):
                col_x = pad + (i % 2) * cw + pad // 2
                if i % 2 == 0 and i > 0:
                    ky += fs_det * 2 + 10
                draw.text((col_x, ky), label.upper(), font=self._font(max(9, fs_det - 2)), fill=dim)
                draw.text((col_x, ky + fs_det), val, font=self._font(fs_det), fill=white)
            cy += card_h + pad // 2

        if cfg.show_forecast and forecast:
            days = forecast[:cfg.forecast_days]
            icon_sm = min((W - pad * 2) // len(days) - 8, 40)
            fc_h = fs_fday * 3 + icon_sm + pad * 2
            self._frosted_rect(canvas, pad, cy, W - pad * 2, fc_h)
            draw = ImageDraw.Draw(canvas)
            col_w = (W - pad * 2) // len(days)
            for i, day in enumerate(days):
                cx2 = pad + i * col_w + col_w // 2
                fy = cy + pad // 2
                self._draw_center(draw, self._day_abbr(day["date"]), cx2, fy, self._font(fs_fday), dim)
                fy += fs_fday + 3
                self._paste_icon(canvas, day["icon"], cx2 - icon_sm // 2, fy, icon_sm, "light")
                fy += icon_sm + 3
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx2, fy, self._font(fs_fday), white)
                fy += fs_fday + 2
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx2, fy, self._font(fs_fday), dim)

        self._draw_center(draw, f"Updated {self._now_str(cfg.timezone)}",
                          W // 2, H - pad - fs_det, self._font(fs_det), dim)

    def _ios_square(self, canvas, draw, current, forecast, cfg, W, H, t, hourly=None, extras=None):
        extras = extras or {}
        icon_code = current["weather"][0]["icon"]
        self._sky_gradient(canvas, icon_code, W, H)
        draw = ImageDraw.Draw(canvas)

        pad   = max(12, W // 38)
        white = (255, 255, 255)
        dim   = (200, 220, 255)
        ios_t = {**t, "text": white, "secondary": dim, "accent": (120, 220, 255)}

        fs_city = max(10, W // 34)
        fs_temp = max(42, W // 7)
        fs_cond = max(10, W // 36)
        fs_det  = max(9,  W // 42)
        fs_fday = max(9,  W // 46)
        cy = pad

        city = f"{current.get('name', cfg.city_name)}, {current.get('sys', {}).get('country', cfg.country)}"
        self._draw_center(draw, city, W // 2, cy, self._font(fs_city), dim)
        cy += fs_city + pad // 3

        icon_size = min(W // 5, H // 7)
        self._paste_icon(canvas, icon_code, W // 4 - icon_size // 2, cy, icon_size, "light")
        temp_str = self._temp(current["main"]["temp"], cfg.units)
        tf = self._font(fs_temp)
        bb = draw.textbbox((0, 0), temp_str, font=tf)
        draw.text((W * 3 // 4 - (bb[2] - bb[0]) // 2, cy + (icon_size - (bb[3] - bb[1])) // 2),
                  temp_str, font=tf, fill=white)
        cy += icon_size + pad // 3

        self._draw_center(draw, current["weather"][0]["description"].title(),
                          W // 2, cy, self._font(fs_cond), dim)
        cy += fs_cond + pad // 4

        df = self._font(fs_det)
        rh = fs_det + 3
        if cfg.show_high_low:
            self._draw_center(draw,
                f"H:{self._temp(current['main']['temp_max'], cfg.units)}  L:{self._temp(current['main']['temp_min'], cfg.units)}",
                W // 2, cy, df, dim)
            cy += rh
        sub = []
        if cfg.show_feels_like: sub.append(f"Feels {self._temp(current['main']['feels_like'], cfg.units)}")
        if cfg.show_humidity:   sub.append(f"Hum {current['main']['humidity']}%")
        if cfg.show_wind:       sub.append(f"Wind {self._speed(current['wind']['speed'], cfg.units)}")
        if sub:
            self._draw_center(draw, "  ·  ".join(sub), W // 2, cy, df, dim)
            cy += rh
        for label, val in self._extras_lines(current, cfg, extras):
            self._draw_center(draw, f"{label}: {val}", W // 2, cy, df, dim)
            cy += rh
        cy += pad // 4

        if cfg.show_hourly and hourly and cy + H // 7 < H - pad * 3:
            hourly_h = H // 7
            self._frosted_rect(canvas, pad, cy, W - pad * 2, hourly_h)
            draw = ImageDraw.Draw(canvas)
            self._draw_hourly(canvas, draw, hourly, cfg, pad + 4, cy + 4, W - pad * 2 - 8, hourly_h - 8, ios_t)
            draw = ImageDraw.Draw(canvas)
            cy += hourly_h + pad // 3

        if cfg.show_forecast and forecast:
            days = forecast[:min(cfg.forecast_days, 5)]
            col_w = (W - pad * 2) // len(days)
            icon_sm = min(col_w - 6, W // 12)
            fc_h = fs_fday * 4 + icon_sm + pad
            self._frosted_rect(canvas, pad, cy, W - pad * 2, fc_h)
            draw = ImageDraw.Draw(canvas)
            for i, day in enumerate(days):
                cx2 = pad + i * col_w + col_w // 2
                fy = cy + pad // 3
                self._draw_center(draw, self._day_abbr(day["date"]), cx2, fy, self._font(fs_fday), dim)
                fy += fs_fday + 2
                self._paste_icon(canvas, day["icon"], cx2 - icon_sm // 2, fy, icon_sm, "light")
                fy += icon_sm + 2
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx2, fy, self._font(fs_fday), white)
                fy += fs_fday + 1
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx2, fy, self._font(fs_fday), dim)

        self._draw_center(draw, f"Updated {self._now_str(cfg.timezone)}",
                          W // 2, H - pad - fs_det, self._font(fs_det), dim)
