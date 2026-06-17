# Mimir Weather Display

A Mimir source plugin that renders live weather conditions and forecasts as full-resolution images. Each configured city is an independent sub-channel that can be assigned to any Mimir display.

## Features

- Current conditions: temperature, feels like, humidity, wind speed, weather description
- Multi-day forecast (1–5 days, configurable)
- Three layout families to match your display: **landscape**, **portrait**, **square**
- **Auto layout** — Mimir picks the best layout based on the display's aspect ratio
- Dark and light themes
- Live preview in the management UI before saving
- Weather data cached (default 30 min) to stay well within the free API tier

## Requirements

- Python 3.9+
- `Pillow` for image rendering
- A free OpenWeatherMap API key (see below)

## Installation

```bash
git clone https://github.com/ryanlane/mimir-source-weather.git
cd mimir-source-weather
pip install -r channels/weather/requirements.txt
```

## Getting an OpenWeatherMap API Key

1. Create a free account at https://openweathermap.org — no credit card required.
2. After signing up, visit https://home.openweathermap.org/api_keys to find your default key.
3. Keys activate within a few minutes of account creation.
4. The **free tier** allows 1,000 API calls/day. With a 30-minute cache, a single display uses ~48 calls/day.

Paste the key into the Mimir channel manager UI when prompted, or set `WEATHER_OWM_KEY` as an environment variable before startup.

## Font

Weather images are rendered server-side with Pillow. For best results, provide a TrueType font:

```
channels/weather/assets/font.ttf
```

Any TTF works — Lato, Inter, Ubuntu, etc. On Debian/Ubuntu systems you can also install:

```bash
apt install fonts-dejavu-core
```

Mimir will find it automatically. Without any font, Pillow's built-in bitmap font is used as a fallback.

## Layouts

| Layout | Dimensions | Description |
|--------|-----------|-------------|
| `landscape` | 800×480 | Current conditions left, forecast columns right |
| `portrait`  | 480×800 | Current conditions centered, forecast row below |
| `square`    | 600×600 | Icon + temp side-by-side, two-column details, forecast row |
| `auto`      | varies  | Mimir selects based on display aspect ratio |

The management UI shows a live rendered preview for all three orientations when "Auto" is selected.

## Multiple Displays / Cities

Each weather display you create in the channel manager is a separate sub-channel. You can:

- Show different cities on different screens
- Show the same city in different layouts (e.g. landscape in the living room, portrait in a hallway)
- Mix units — imperial for some displays, metric for others

## Configuration

All settings are managed through the Mimir UI. Available per-display options:

| Setting | Default | Description |
|---------|---------|-------------|
| City | — | Search by name, state, or country |
| Units | Imperial | °F / mph or °C / m/s |
| Layout | Auto | landscape / portrait / square / auto |
| Theme | Dark | Dark or light background |
| Show Forecast | Yes | Toggle the forecast row/columns |
| Forecast Days | 3 | 1–5 days |
| Show Humidity | Yes | Humidity percentage |
| Show Wind | Yes | Wind speed and direction |
| Show Feels Like | Yes | Apparent temperature |
| Show High/Low | Yes | Daily temperature range |

Global settings:

| Setting | Default | Description |
|---------|---------|-------------|
| Cache Duration | 30 min | How long to reuse OWM responses before fetching fresh data |

## Plugin Protocol

This plugin implements the Mimir channel protocol:

- `GET  /subchannels` — list configured displays
- `POST /subchannels` — create a display
- `PUT  /subchannels/{id}` — update a display
- `DELETE /subchannels/{id}` — remove a display
- `GET  /subchannels/{id}/preview?w=&h=` — render saved display at given size
- `POST /preview` — render unsaved config (used by the edit UI live preview)
- `GET  /search-city?q=` — geocoding (proxied through OWM)
- `POST /validate-key` — test and persist an API key
- `POST /request-image` — primary image endpoint; returns raw JPEG bytes with `X-Content-Fingerprint`

## Attribution

Weather data provided by [OpenWeatherMap](https://openweathermap.org/).
