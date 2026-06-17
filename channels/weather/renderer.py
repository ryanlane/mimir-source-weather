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

    def _load_icon(self, icon_code: str, size: int) -> Optional[Any]:
        key = f"{icon_code}_{size}"
        if key in self._icon_cache:
            return self._icon_cache[key]

        from . import fetcher as _f
        raw = _f.get_icon_bytes(icon_code, self.icons_dir)
        img = None
        if raw:
            try:
                img = Image.open(io.BytesIO(raw)).convert("RGBA").resize((size, size), Image.LANCZOS)
            except Exception as exc:
                logger.warning("[Weather] Icon resize failed: %s", exc)
        self._icon_cache[key] = img
        return img

    def _paste_icon(self, canvas: Any, icon_code: str, x: int, y: int, size: int) -> None:
        img = self._load_icon(icon_code, size)
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

    def render(self, current: Dict, forecast: List[Dict], display, width: int, height: int) -> bytes:
        if not _PIL:
            raise RuntimeError("Pillow not installed")

        aspect = width / height
        layout = display.layout
        if layout == "auto":
            layout = "landscape" if aspect >= 1.2 else ("portrait" if aspect <= 0.85 else "square")

        t = THEMES.get(display.theme, THEMES["dark"])
        canvas = Image.new("RGB", (width, height), t["bg"])
        draw = ImageDraw.Draw(canvas)

        if layout == "landscape":
            self._landscape(canvas, draw, current, forecast, display, width, height, t)
        elif layout == "portrait":
            self._portrait(canvas, draw, current, forecast, display, width, height, t)
        else:
            self._square(canvas, draw, current, forecast, display, width, height, t)

        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=92, optimize=True)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Helpers

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

    def _landscape(self, canvas, draw, current, forecast, cfg, W, H, t):
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
        self._paste_icon(canvas, current["weather"][0]["icon"], pad, icon_y, icon_size)

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
                self._paste_icon(canvas, day["icon"], cx - icon_sm // 2, fy, icon_sm)
                fy += icon_sm + 4
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx, fy, self._font(fs_ftemp), t["text"])
                fy += fs_ftemp + 2
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx, fy, self._font(fs_ftemp), t["secondary"])

        # Timestamp bottom-right
        ts = f"Updated {datetime.now().strftime('%-I:%M %p')}"
        tw = self._text_w(draw, ts, self._font(fs_detail))
        draw.text((W - pad - tw, H - pad - fs_detail), ts, font=self._font(fs_detail), fill=t["secondary"])

    # ------------------------------------------------------------------
    # Portrait layout

    def _portrait(self, canvas, draw, current, forecast, cfg, W, H, t):
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
        self._paste_icon(canvas, current["weather"][0]["icon"], W // 2 - icon_size // 2, cy, icon_size)
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
                self._paste_icon(canvas, day["icon"], cx - icon_sm // 2, fy, icon_sm)
                fy += icon_sm + 4
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx, fy, self._font(fs_fday), t["text"])
                fy += fs_fday + 2
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx, fy, self._font(fs_fday), t["secondary"])

        self._draw_center(draw, f"Updated {datetime.now().strftime('%-I:%M %p')}",
                          W // 2, H - pad - fs_detail, self._font(fs_detail), t["secondary"])

    # ------------------------------------------------------------------
    # Square layout

    def _square(self, canvas, draw, current, forecast, cfg, W, H, t):
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
        self._paste_icon(canvas, current["weather"][0]["icon"], icon_x, cy, icon_size)

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
                self._paste_icon(canvas, day["icon"], cx - icon_sm // 2, fy, icon_sm)
                fy += icon_sm + 3
                self._draw_center(draw, self._temp(day["temp_max"], cfg.units), cx, fy, self._font(fs_fday), t["text"])
                fy += fs_fday + 2
                self._draw_center(draw, self._temp(day["temp_min"], cfg.units), cx, fy, self._font(fs_fday), t["secondary"])

        self._draw_center(draw, f"Updated {datetime.now().strftime('%-I:%M %p')}",
                          W // 2, H - pad - fs_detail, self._font(fs_detail), t["secondary"])
