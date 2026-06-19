# TV Guide Helper (Android TV / Fire TV)

A tiny companion app for the TV Guide add-on. It runs a local command server
(port 8472) on the Fire Stick and uses an AccessibilityService to do things ADB
can't do reliably:

- Launch apps the correct way (leanback launch intent) — no more crashes from
  guessed activity names.
- Fire deep links straight into a title.
- Read the on-screen elements (`/screen`) so Home Assistant can see what's happening.
- Tap a profile by name (`/selectprofile {name}`) instead of blind D-pad navigation.

## Endpoints (POST JSON unless noted)
- `GET  /ping` → status, accessibility-enabled, current foreground app
- `GET  /foreground`
- `POST /launch` `{package, deep_link?}`
- `POST /deeplink` `{package, url}`
- `GET  /screen` → visible text/desc nodes + which is focused
- `POST /selectprofile` `{name}` (alias `/click {text}`)
- `POST /global` `{action: home|back|recents}`

## Install
1. Download the APK from the **helper-latest** release of this repo (use the
   Downloader app on the Fire Stick).
2. Allow install from unknown sources if prompted.
3. Open **TV Guide Helper** once, tap **Open accessibility settings**, and enable
   the service so it can read/tap the screen.

Built automatically by GitHub Actions (`.github/workflows/build-helper.yml`).
