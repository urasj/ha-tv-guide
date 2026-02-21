# ha-tv-guide

A Home Assistant add-on providing a personal TV Guide with:
- 📺 Full show browser powered by Sonarr
- 🔥 Fire TV launcher with profile selection
- 🔊 Sonos volume, mute, speech enhancement, and night mode controls
- 🎬 Automatic streaming service detection via TMDB
- ✅ Episode watched tracking (stored server-side, never lost)
- 📊 HA sensors for automations
- 🃏 Lovelace card for quick-glance dashboard control

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click the **⋮ menu** (top right) → **Repositories**
3. Add: `https://github.com/urasj/ha-tv-guide`
4. Find **TV Guide** in the store and click **Install**

## Configuration

After installing, configure via the add-on's **Configuration** tab:

| Field | Description |
|-------|-------------|
| `sonarr_url` | Your Sonarr URL, e.g. `http://192.168.7.24:8989` |
| `sonarr_key` | Sonarr API key (Settings → General → API Key) |
| `tmdb_key` | TMDB API key from themoviedb.org/settings/api |
| `ha_url` | Home Assistant URL, e.g. `http://homeassistant:8123` |
| `ha_token` | Long-lived access token from your HA profile |
| `firetv_entity` | Your Fire TV entity ID |
| `sonos_entity` | Your Sonos entity ID |

## Lovelace Card

After installing, add the card resource and use it in your dashboard:

```yaml
type: custom:tv-guide-card
addon_url: /api/hassio_ingress/tv_guide
```

See the wiki for full setup instructions.
