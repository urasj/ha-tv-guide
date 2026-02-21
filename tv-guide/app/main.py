import os, json, asyncio, httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ── Config ──────────────────────────────────────────────
DATA_FILE = Path("/data/tvguide.json")

SONARR_URL   = os.environ.get("SONARR_URL", "").rstrip("/")
SONARR_KEY   = os.environ.get("SONARR_KEY", "")
TMDB_KEY     = os.environ.get("TMDB_KEY", "")
HA_URL       = os.environ.get("HA_URL", "http://homeassistant:8123")
HA_TOKEN     = os.environ.get("HA_TOKEN", "")
FIRETV_ENT   = os.environ.get("FIRETV_ENTITY", "media_player.fire_tv_192_168_7_211")
SONOS_ENT    = os.environ.get("SONOS_ENTITY", "media_player.living_room")
INGRESS_PATH = os.environ.get("INGRESS_PATH", "").rstrip("/")

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG  = "https://image.tmdb.org/t/p/w500"

# Profile definitions
APP_PROFILES = {
    "netflix":   ["Justin", "justinuras", "Vicki", "Tony", "Kristen"],
    "disney":    ["Justin", "Vicki", "Tony", "Kristen"],
    "peacock":   ["Justin", "Tony", "Kids Profile"],
    "discovery": ["Justin", "Kristen"],
}

# Maps service -> (package, component) - component verified via dumpsys on device
APP_LAUNCH = {
    "netflix":    ("com.netflix.ninja",                   "com.netflix.ninja/.MainActivity"),
    "hulu":       ("com.hulu.plus",                       "com.hulu.plus/.SplashActivity"),
    "disney":     ("com.disney.disneyplus",               "com.disney.disneyplus/com.bamtechmedia.dominguez.main.MainActivity"),
    "max":        ("com.hbo.hbonow",                      "com.hbo.hbonow/com.wbd.beam.BeamActivity"),
    "peacock":    ("com.peacock.peacockfiretv",            "com.peacock.peacockfiretv/com.peacock.peacocktv.AmazonMainActivity"),
    "discovery":  ("com.discovery.discoveryplus.firetv",  "com.discovery.discoveryplus.firetv/com.wbd.beam.BeamActivity"),
    "tubi":       ("com.tubitv.ott",                      None),
    "pluto":      ("tv.pluto.android",                    None),
    "youtube":    ("com.amazon.firetv.youtube",           None),
    "prime":      ("com.amazon.avod.thirdpartyclient",    None),
    "plex":       ("com.plexapp.android",                 None),
    "paramount":  ("com.cbs.ott",                         None),
    "apple":      ("com.apple.atve.amazon.appletv",       None),
    "amc":        ("com.amcplus.firetv",                  None),
    "shudder":    ("com.amc.shudder",                     None),
    "crunchyroll":("com.crunchyroll.crunchyroid",         None),
    "starz":      ("com.bydeluxe.d3.android.program.starz", None),
}
APP_PACKAGES = {k: v[0] for k, v in APP_LAUNCH.items()}

SVCS = {
    "netflix":"Netflix","hulu":"Hulu","disney":"Disney+","max":"Max",
    "peacock":"Peacock","discovery":"Discovery+","tubi":"Tubi","pluto":"Pluto TV",
    "youtube":"YouTube","prime":"Prime Video","plex":"Plex","paramount":"Paramount+",
    "apple":"Apple TV+","amc":"AMC+","shudder":"Shudder","crunchyroll":"Crunchyroll","starz":"Starz",
}

TMDB_SVC_MAP = {
    "netflix":"netflix","hulu":"hulu","disney plus":"disney","max":"max",
    "hbo max":"max","peacock":"peacock","discovery+":"discovery","discovery plus":"discovery",
    "tubi tv":"tubi","pluto tv":"pluto","amazon prime video":"prime","prime video":"prime",
    "apple tv plus":"apple","apple tv+":"apple","paramount+":"paramount",
    "amc+":"amc","shudder":"shudder","crunchyroll":"crunchyroll","starz":"starz",
}

# ── Persistence ──────────────────────────────────────────
def load_data():
    if DATA_FILE.exists():
        try: return json.loads(DATA_FILE.read_text())
        except: pass
    return {"watched": {}, "services": {}, "deep_links": {}, "progress": {}}

def save_data(d):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(d, indent=2))

# ── App ──────────────────────────────────────────────────
app = FastAPI(title="TV Guide")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="/app/static"), name="static")

# ── HA helper ────────────────────────────────────────────
async def ha_call(client: httpx.AsyncClient, domain: str, service: str, data: dict):
    r = await client.post(
        f"{HA_URL}/api/services/{domain}/{service}",
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
        json=data, timeout=10
    )
    return r

async def ha_adb(client: httpx.AsyncClient, command: str):
    return await ha_call(client, "androidtv", "adb_command", {"entity_id": FIRETV_ENT, "command": command})

# ── Routes ───────────────────────────────────────────────

@app.get("/")
@app.get("/ingress")
async def index():
    return HTMLResponse(Path("/app/static/index.html").read_text())

@app.get("/api/status")
async def status():
    return {
        "sonarr": bool(SONARR_URL and SONARR_KEY),
        "tmdb": bool(TMDB_KEY),
        "ha_token": bool(HA_TOKEN),
        "firetv_entity": FIRETV_ENT,
        "sonos_entity": SONOS_ENT,
        "profiles": APP_PROFILES,
        "services": SVCS,
        "ingress_path": INGRESS_PATH,
    }

@app.get("/api/data")
async def get_data():
    return load_data()

@app.post("/api/data")
async def set_data(request: Request):
    body = await request.json()
    d = load_data()
    d.update(body)
    save_data(d)
    return {"ok": True}

# ── Sonarr ───────────────────────────────────────────────

@app.get("/api/shows")
async def get_shows():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SONARR_URL}/api/v3/series", headers={"X-Api-Key": SONARR_KEY}, timeout=15)
        if r.status_code != 200:
            raise HTTPException(502, "Sonarr error")
        shows = r.json()
        d = load_data()
        result = []
        for s in shows:
            sid = str(s["id"])
            result.append({
                "id": s["id"],
                "title": s["title"],
                "status": s.get("status"),
                "year": s.get("year"),
                "network": s.get("network"),
                "poster": f"{SONARR_URL}/api/v3/mediacover/{s['id']}/poster.jpg?apikey={SONARR_KEY}",
                "banner": f"{SONARR_URL}/api/v3/mediacover/{s['id']}/banner.jpg?apikey={SONARR_KEY}",
                "seasonCount": s.get("seasonCount", 0),
                "episodeCount": s.get("episodeCount", 0),
                "episodeFileCount": s.get("episodeFileCount", 0),
                "tvdbId": s.get("tvdbId"),
                "service": d["services"].get(sid),
                "progress": d["progress"].get(sid, {}),
            })
        result.sort(key=lambda x: x["title"])
        return result

@app.get("/api/shows/{show_id}/episodes")
async def get_episodes(show_id: int):
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SONARR_URL}/api/v3/episode",
            headers={"X-Api-Key": SONARR_KEY},
            params={"seriesId": show_id}, timeout=15
        )
        if r.status_code != 200:
            raise HTTPException(502, "Sonarr error")
        eps = r.json()
        d = load_data()
        sid = str(show_id)
        watched_eps = d["watched"].get(sid, [])
        result = []
        for e in eps:
            result.append({
                "id": e["id"],
                "title": e.get("title"),
                "seasonNumber": e.get("seasonNumber"),
                "episodeNumber": e.get("episodeNumber"),
                "airDate": e.get("airDateUtc"),
                "overview": e.get("overview"),
                "hasFile": e.get("hasFile", False),
                "watched": e["id"] in watched_eps,
            })
        result.sort(key=lambda x: (x["seasonNumber"], x["episodeNumber"]))
        return result

# ── Watched ──────────────────────────────────────────────

@app.post("/api/shows/{show_id}/watched/{ep_id}")
async def mark_watched(show_id: int, ep_id: int):
    d = load_data()
    sid = str(show_id)
    if sid not in d["watched"]: d["watched"][sid] = []
    if ep_id not in d["watched"][sid]: d["watched"][sid].append(ep_id)
    save_data(d)
    return {"ok": True}

@app.delete("/api/shows/{show_id}/watched/{ep_id}")
async def mark_unwatched(show_id: int, ep_id: int):
    d = load_data()
    sid = str(show_id)
    if sid in d["watched"]:
        d["watched"][sid] = [e for e in d["watched"][sid] if e != ep_id]
    save_data(d)
    return {"ok": True}

@app.post("/api/shows/{show_id}/progress")
async def set_progress(show_id: int, request: Request):
    body = await request.json()
    d = load_data()
    d["progress"][str(show_id)] = body
    save_data(d)
    return {"ok": True}

# ── Service assignment ────────────────────────────────────

@app.post("/api/shows/{show_id}/service")
async def set_service(show_id: int, request: Request):
    body = await request.json()
    d = load_data()
    d["services"][str(show_id)] = body.get("service")
    save_data(d)
    return {"ok": True}

# ── TMDB service scan ─────────────────────────────────────

@app.get("/api/shows/{show_id}/scan-service")
async def scan_service(show_id: int, tvdb_id: int):
    async with httpx.AsyncClient() as client:
        # Find on TMDB via TVDB ID
        r = await client.get(
            f"{TMDB_BASE}/find/{tvdb_id}",
            params={"api_key": TMDB_KEY, "external_source": "tvdb_id"}, timeout=10
        )
        if r.status_code != 200:
            raise HTTPException(502, "TMDB find error")
        results = r.json().get("tv_results", [])
        if not results:
            return {"service": None}
        tmdb_id = results[0]["id"]

        # Get watch providers
        r2 = await client.get(
            f"{TMDB_BASE}/tv/{tmdb_id}/watch/providers",
            params={"api_key": TMDB_KEY}, timeout=10
        )
        if r2.status_code != 200:
            return {"service": None}
        us = r2.json().get("results", {}).get("US", {})
        providers = us.get("flatrate", []) + us.get("free", []) + us.get("ads", [])
        for p in providers:
            name = p.get("provider_name", "").lower()
            for key, svc in TMDB_SVC_MAP.items():
                if key in name:
                    # Save it
                    d = load_data()
                    d["services"][str(show_id)] = svc
                    save_data(d)
                    return {"service": svc, "provider": p.get("provider_name")}
        return {"service": None}

@app.post("/api/scan-all")
async def scan_all(request: Request):
    body = await request.json()
    shows = body.get("shows", [])
    results = {}
    async with httpx.AsyncClient() as client:
        for show in shows:
            sid = str(show["id"])
            tvdb = show.get("tvdbId")
            if not tvdb: continue
            try:
                r = await client.get(
                    f"{TMDB_BASE}/find/{tvdb}",
                    params={"api_key": TMDB_KEY, "external_source": "tvdb_id"}, timeout=10
                )
                tv = r.json().get("tv_results", [])
                if not tv: continue
                r2 = await client.get(
                    f"{TMDB_BASE}/tv/{tv[0]['id']}/watch/providers",
                    params={"api_key": TMDB_KEY}, timeout=10
                )
                us = r2.json().get("results", {}).get("US", {})
                providers = us.get("flatrate", []) + us.get("free", []) + us.get("ads", [])
                for p in providers:
                    name = p.get("provider_name", "").lower()
                    for key, svc in TMDB_SVC_MAP.items():
                        if key in name:
                            results[sid] = svc
                            break
                    if sid in results: break
            except: pass
            await asyncio.sleep(0.15)
    # Save all at once
    d = load_data()
    d["services"].update(results)
    save_data(d)
    return {"results": results, "scanned": len(shows), "found": len(results)}

# ── Fire TV ───────────────────────────────────────────────

@app.post("/api/firetv/launch")
async def firetv_launch(request: Request):
    body = await request.json()
    svc = body.get("service")
    profile_index = body.get("profileIndex", 0)
    launch = APP_LAUNCH.get(svc)
    if not launch:
        raise HTTPException(400, f"Unknown service: {svc}")
    pkg, component = launch
    profiles = APP_PROFILES.get(svc, [])
    profile_name = profiles[profile_index] if profile_index < len(profiles) else ""

    async with httpx.AsyncClient() as client:
        # Step 1: Wake the Fire TV
        await ha_call(client, "media_player", "turn_on", {"entity_id": FIRETV_ENT})
        await asyncio.sleep(2.0)
        # Step 2: Go home to stop current playback
        await ha_adb(client, "input keyevent KEYCODE_HOME")
        await asyncio.sleep(1.5)
        # Step 3: Launch - use specific component if known, else monkey
        if component:
            await ha_adb(client, f"am start -n {component}")
        else:
            await ha_adb(client, f"monkey -p {pkg} 1")
        # Step 4: Profile selection if needed
        if profiles and len(profiles) > 1:
            await asyncio.sleep(5.0)
            for _ in range(profile_index):
                await ha_adb(client, "input keyevent KEYCODE_DPAD_RIGHT")
                await asyncio.sleep(0.3)
            await ha_adb(client, "input keyevent KEYCODE_DPAD_CENTER")

    return {"ok": True, "service": svc, "package": pkg, "profile": profile_name}

@app.post("/api/firetv/command")
async def firetv_command(request: Request):
    body = await request.json()
    cmd = body.get("command")
    if not cmd:
        raise HTTPException(400, "command required")
    key_map = {
        "play_pause": "KEYCODE_MEDIA_PLAY_PAUSE",
        "back":       "KEYCODE_BACK",
        "home":       "KEYCODE_HOME",
        "up":         "KEYCODE_DPAD_UP",
        "down":       "KEYCODE_DPAD_DOWN",
        "left":       "KEYCODE_DPAD_LEFT",
        "right":      "KEYCODE_DPAD_RIGHT",
        "select":     "KEYCODE_DPAD_CENTER",
        "rewind":     "KEYCODE_MEDIA_REWIND",
        "forward":    "KEYCODE_MEDIA_FAST_FORWARD",
        "vol_up":     "KEYCODE_VOLUME_UP",
        "vol_down":   "KEYCODE_VOLUME_DOWN",
    }
    keycode = key_map.get(cmd)
    async with httpx.AsyncClient() as client:
        if keycode:
            await ha_adb(client, f"input keyevent {keycode}")
        else:
            await ha_adb(client, cmd)
    return {"ok": True}

# ── Sonos ─────────────────────────────────────────────────

@app.get("/api/sonos/state")
async def sonos_state():
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{HA_URL}/api/states/{SONOS_ENT}",
            headers={"Authorization": f"Bearer {HA_TOKEN}"}, timeout=10
        )
        s = r.json()
        attrs = s.get("attributes", {})
        # Get speech enhancement and night mode
        se_r = await client.get(
            f"{HA_URL}/api/states/switch.living_room_speech_enhancement",
            headers={"Authorization": f"Bearer {HA_TOKEN}"}, timeout=10
        )
        nm_r = await client.get(
            f"{HA_URL}/api/states/switch.living_room_night_sound",
            headers={"Authorization": f"Bearer {HA_TOKEN}"}, timeout=10
        )
        return {
            "state": s.get("state"),
            "volume": attrs.get("volume_level", 0),
            "muted": attrs.get("is_volume_muted", False),
            "speech_enhancement": se_r.json().get("state") == "on",
            "night_mode": nm_r.json().get("state") == "on",
        }

@app.post("/api/sonos/command")
async def sonos_command(request: Request):
    body = await request.json()
    cmd = body.get("command")
    async with httpx.AsyncClient() as client:
        if cmd == "volume_up":
            vol = min(1.0, float(body.get("current", 0.3)) + 0.05)
            await ha_call(client, "media_player", "volume_set", {"entity_id": SONOS_ENT, "volume_level": round(vol, 2)})
        elif cmd == "volume_down":
            vol = max(0.0, float(body.get("current", 0.3)) - 0.05)
            await ha_call(client, "media_player", "volume_set", {"entity_id": SONOS_ENT, "volume_level": round(vol, 2)})
        elif cmd == "mute":
            muted = body.get("muted", False)
            await ha_call(client, "media_player", "volume_mute", {"entity_id": SONOS_ENT, "is_volume_muted": not muted})
        elif cmd == "speech_enhancement":
            state = body.get("state", False)
            svc = "turn_off" if state else "turn_on"
            await ha_call(client, "switch", svc, {"entity_id": "switch.living_room_speech_enhancement"})
        elif cmd == "night_mode":
            state = body.get("state", False)
            svc = "turn_off" if state else "turn_on"
            await ha_call(client, "switch", svc, {"entity_id": "switch.living_room_night_sound"})
    return {"ok": True}

# ── Serve ─────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8099, log_level="info")
