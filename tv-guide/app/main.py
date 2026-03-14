import os, json, asyncio, re, httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ── Config ────────────────────────────────────────────────────────────────
DATA_FILE   = Path("/data/tvguide.json")
SONARR_URL  = os.environ.get("SONARR_URL", "").rstrip("/")
# Support both SONARR_KEY and SONARR_API_KEY (run.sh exports SONARR_API_KEY)
SONARR_KEY  = os.environ.get("SONARR_API_KEY", "") or os.environ.get("SONARR_KEY", "")
# Support both TMDB_KEY and TMDB_API_KEY
TMDB_KEY    = os.environ.get("TMDB_API_KEY", "") or os.environ.get("TMDB_KEY", "")
HA_URL      = os.environ.get("HA_URL", "http://homeassistant:8123").rstrip("/")
HA_TOKEN    = os.environ.get("HA_TOKEN", "")
FIRETV_ENT  = os.environ.get("FIRETV_ENTITY", "media_player.fire_tv_192_168_7_211")
SONOS_ENT   = os.environ.get("SONOS_ENTITY", "media_player.living_room")
INGRESS_PATH = os.environ.get("INGRESS_PATH", "").rstrip("/")
TMDB_BASE   = "https://api.themoviedb.org/3"

# Profile definitions
APP_PROFILES = {
    "netflix":   ["Justin", "justinuras", "Vicki", "Tony", "Kristen"],
    "disney":    ["Justin", "Vicki", "Tony", "Kristen"],
    "peacock":   ["Justin", "Tony", "Kids Profile"],
    "discovery": ["Justin", "Kristen"],
    "max":       ["Justin", "Shane", "Steph", "Emma"],
}

APP_LAUNCH = {
    "netflix":    ("com.netflix.ninja",               "com.netflix.ninja/com.netflix.ninja.MainActivity"),
    "hulu":       ("com.hulu.plus",                   "com.hulu.plus/com.hulu.plus.SplashActivity"),
    "disney":     ("com.disney.disneyplus",            "com.disney.disneyplus/com.bamtechmedia.dominguez.main.MainActivity"),
    "max":        ("com.hbo.hbonow",                  "com.hbo.hbonow/com.wbd.beam.BeamActivity"),
    "peacock":    ("com.peacock.peacockfiretv",        "com.peacock.peacockfiretv/com.peacock.peacocktv.AmazonMainActivity"),
    "discovery":  ("com.discovery.discoveryplus.firetv","com.discovery.discoveryplus.firetv/com.wbd.beam.BeamActivity"),
    "tubi":       ("com.tubitv.ott",                  "com.tubitv.ott/com.tubitv.activities.FireTVMainActivity"),
    "pluto":      ("tv.pluto.android",                "tv.pluto.android/tv.pluto.android.EntryPoint"),
    "youtube":    ("com.amazon.firetv.youtube",        "com.amazon.firetv.youtube/dev.cobalt.app.MainActivity"),
    "plex":       ("com.plexapp.android",             "com.plexapp.android/com.plexapp.plex.activities.SplashActivity"),
    "paramount":  ("com.cbs.ott",                     "com.cbs.ott/com.paramount.android.pplus.features.splash.tv.SplashMediatorActivity"),
    "prime":      ("com.amazon.firebat",              "com.amazon.firebat/com.amazon.firebatcore.deeplink.DeepLinkRoutingActivity"),
    "apple":      ("com.apple.atve.amazon.appletv",   None),
    "amc":        ("com.amcplus.firetv",              None),
    "shudder":    ("com.amc.shudder",                 None),
    "crunchyroll":("com.crunchyroll.crunchyroid",     None),
    "starz":      ("com.bydeluxe.d3.android.program.starz", None),
}

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

LAUNCH_TIMING = {
    "default":   {"pre_profile": 7,  "post_profile": 15},
    "discovery": {"pre_profile": 7,  "post_profile": 15},
    "max":       {"pre_profile": 6,  "post_profile": 15},
    "netflix":   {"pre_profile": 5,  "post_profile": 10},
    "hulu":      {"pre_profile": 5,  "post_profile": 10},
    "disney":    {"pre_profile": 7,  "post_profile": 18},
    "peacock":   {"pre_profile": 6,  "post_profile": 12},
}

# ── Persistence ───────────────────────────────────────────────────────────
def load_data():
    if DATA_FILE.exists():
        try: return json.loads(DATA_FILE.read_text())
        except: pass
    return {"watched": {}, "services": {}, "deep_links": {}, "progress": {}, "manual_services": {}}

def save_data(d):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(d, indent=2))

# ── App ───────────────────────────────────────────────────────────────────
app = FastAPI(title="TV Guide")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="/app/static"), name="static")

# ── HA helpers ────────────────────────────────────────────────────────────
async def ha_call(client, domain, service, data):
    r = await client.post(
        f"{HA_URL}/api/services/{domain}/{service}",
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
        json=data, timeout=10
    )
    return r

async def ha_adb(client, command):
    return await ha_call(client, "androidtv", "adb_command", {"entity_id": FIRETV_ENT, "command": command})

# ── Routes ────────────────────────────────────────────────────────────────
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
        # Debug: show which env vars are set (not values)
        "env_debug": {
            "SONARR_URL": bool(SONARR_URL),
            "SONARR_KEY": bool(SONARR_KEY),
            "TMDB_KEY": bool(TMDB_KEY),
            "HA_TOKEN": bool(HA_TOKEN),
        }
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

# ── Sonarr ────────────────────────────────────────────────────────────────
@app.get("/api/shows")
async def get_shows():
    if not SONARR_URL or not SONARR_KEY:
        raise HTTPException(503, "Sonarr not configured — check add-on settings (sonarr_url and sonarr_api_key)")
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{SONARR_URL}/api/v3/series",
                headers={"X-Api-Key": SONARR_KEY},
                timeout=15
            )
            if r.status_code != 200:
                raise HTTPException(502, f"Sonarr returned {r.status_code}")
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
                    "overview": s.get("overview", ""),
                    "nextAiring": s.get("nextAiring"),
                    "images": s.get("images", []),
                    "poster": f"{SONARR_URL}/api/v3/mediacover/{s['id']}/poster.jpg?apikey={SONARR_KEY}",
                    "fanart": f"{SONARR_URL}/api/v3/mediacover/{s['id']}/fanart.jpg?apikey={SONARR_KEY}",
                    "seasonCount": s.get("seasonCount", 0),
                    "episodeCount": s.get("episodeCount", 0),
                    "tvdbId": s.get("tvdbId"),
                    "genres": s.get("genres", []),
                    "service": d["services"].get(sid),
                    "deep_link": d.get("deep_links", {}).get(sid),
                })
            result.sort(key=lambda x: x["title"])
            return result
    except httpx.ConnectError as e:
        raise HTTPException(503, f"Cannot reach Sonarr at {SONARR_URL} — {e}")
    except Exception as e:
        raise HTTPException(500, f"Sonarr error: {e}")

@app.get("/api/shows/{show_id}/episodes")
async def get_episodes(show_id: int):
    if not SONARR_URL or not SONARR_KEY:
        raise HTTPException(503, "Sonarr not configured")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SONARR_URL}/api/v3/episode",
            headers={"X-Api-Key": SONARR_KEY},
            params={"seriesId": show_id},
            timeout=15
        )
        if r.status_code != 200:
            raise HTTPException(502, "Sonarr error")
        eps = r.json()
        d = load_data()
        sid = str(show_id)
        watched_eps = d["watched"].get(sid, [])
        result = []
        for e in eps:
            if e.get("seasonNumber", 0) == 0:
                continue
            result.append({
                "id": e["id"],
                "title": e.get("title"),
                "seasonNumber": e.get("seasonNumber"),
                "episodeNumber": e.get("episodeNumber"),
                "airDateUtc": e.get("airDateUtc"),
                "overview": e.get("overview"),
                "hasFile": e.get("hasFile", False),
                "watched": e["id"] in watched_eps,
            })
        result.sort(key=lambda x: (x["seasonNumber"], x["episodeNumber"]))
        return result

# ── Watched ───────────────────────────────────────────────────────────────
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

# ── Service assignment ────────────────────────────────────────────────────
@app.post("/api/shows/{show_id}/service")
async def set_service(show_id: int, request: Request):
    body = await request.json()
    d = load_data()
    new_svc = body.get("service")
    old_svc = d["services"].get(str(show_id))
    d["services"][str(show_id)] = new_svc
    if new_svc != old_svc:
        d.get("deep_links", {}).pop(str(show_id), None)
    # Track manual overrides so scan-all never overwrites them
    if new_svc:
        d.setdefault("manual_services", {})[str(show_id)] = new_svc
    else:
        d.get("manual_services", {}).pop(str(show_id), None)
    save_data(d)
    return {"ok": True}

# ── Deep link helpers ─────────────────────────────────────────────────────
def slugify(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")

def build_deep_link(svc: str, title: str, ext_ids: dict) -> str:
    from urllib.parse import quote
    q = quote(title)
    slug = slugify(title)
    if svc == "netflix" and ext_ids.get("netflix"):
        return f"https://www.netflix.com/title/{ext_ids['netflix']}"
    if svc == "discovery" and ext_ids.get("discovery_uuid"):
        return f"https://play.discoveryplus.com/show/{ext_ids['discovery_uuid']}"
    urls = {
        "netflix":   f"https://www.netflix.com/search?q={q}",
        "hulu":      f"https://www.hulu.com/search?q={q}",
        "disney":    f"https://www.disneyplus.com/search/{q}",
        "max":       f"https://play.max.com/search/result?q={q}",
        "peacock":   f"https://www.peacocktv.com/search?q={q}",
        "discovery": f"https://play.discoveryplus.com/show/{slug}",
        "prime":     f"https://www.amazon.com/s?k={q}&i=prime-instant-video",
        "apple":     f"https://tv.apple.com/search?term={q}",
        "paramount": f"https://www.paramountplus.com/shows/{slug}/",
        "plex":      f"https://app.plex.tv/desktop/#!/search?query={q}",
    }
    return urls.get(svc, "")

async def fetch_discovery_uuid(client, title: str):
    try:
        r = await client.get(
            "https://us1-prod-direct.discoveryplus.com/cms/api/us/content/search",
            params={"query": title, "decorators": "contentAction"},
            headers={"x-disco-client": "firetv:3:2.12.0", "accept": "application/json"},
            timeout=10
        )
        if r.status_code != 200: return None
        for item in r.json().get("data", []):
            if item.get("type") == "show":
                uid = item.get("id")
                if uid and "-" in str(uid): return str(uid)
    except: pass
    return None

# ── TMDB scan ─────────────────────────────────────────────────────────────
@app.get("/api/shows/{show_id}/scan-service")
async def scan_service(show_id: int, tvdb_id: int, title: str = ""):
    if not TMDB_KEY:
        raise HTTPException(503, "TMDB not configured")
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{TMDB_BASE}/find/{tvdb_id}",
            params={"api_key": TMDB_KEY, "external_source": "tvdb_id"}, timeout=10)
        if r.status_code != 200: raise HTTPException(502, "TMDB find error")
        results = r.json().get("tv_results", [])
        if not results: return {"service": None}
        tmdb_id = results[0]["id"]
        show_title = title or results[0].get("name", "")
        ext_r = await client.get(f"{TMDB_BASE}/tv/{tmdb_id}/external_ids",
            params={"api_key": TMDB_KEY}, timeout=10)
        ext_ids = ext_r.json() if ext_r.status_code == 200 else {}
        r2 = await client.get(f"{TMDB_BASE}/tv/{tmdb_id}/watch/providers",
            params={"api_key": TMDB_KEY}, timeout=10)
        if r2.status_code != 200: return {"service": None}
        us = r2.json().get("results", {}).get("US", {})
        providers = us.get("flatrate", []) + us.get("free", []) + us.get("ads", [])
        for p in providers:
            name = p.get("provider_name", "").lower()
            for key, svc in TMDB_SVC_MAP.items():
                if key in name:
                    if svc == "discovery":
                        uuid = await fetch_discovery_uuid(client, show_title)
                        if uuid: ext_ids["discovery_uuid"] = uuid
                    deep_link = build_deep_link(svc, show_title, ext_ids)
                    d = load_data()
                    d["services"][str(show_id)] = svc
                    if deep_link: d.setdefault("deep_links", {})[str(show_id)] = deep_link
                    save_data(d)
                    return {"service": svc, "provider": p.get("provider_name"), "deep_link": deep_link}
        return {"service": None}

@app.post("/api/scan-all")
async def scan_all(request: Request):
    if not TMDB_KEY:
        raise HTTPException(503, "TMDB not configured")
    body = await request.json()
    shows = body.get("shows", [])
    results = {}
    deep_links = {}
    async with httpx.AsyncClient() as client:
        for show in shows:
            sid = str(show["id"])
            tvdb = show.get("tvdbId")
            if not tvdb: continue
            try:
                r = await client.get(f"{TMDB_BASE}/find/{tvdb}",
                    params={"api_key": TMDB_KEY, "external_source": "tvdb_id"}, timeout=10)
                tv = r.json().get("tv_results", [])
                if not tv: continue
                tmdb_id = tv[0]["id"]
                show_title = show.get("title", tv[0].get("name", ""))
                ext_r = await client.get(f"{TMDB_BASE}/tv/{tmdb_id}/external_ids",
                    params={"api_key": TMDB_KEY}, timeout=10)
                ext_ids = ext_r.json() if ext_r.status_code == 200 else {}
                r2 = await client.get(f"{TMDB_BASE}/tv/{tmdb_id}/watch/providers",
                    params={"api_key": TMDB_KEY}, timeout=10)
                us = r2.json().get("results", {}).get("US", {})
                providers = us.get("flatrate", []) + us.get("free", []) + us.get("ads", [])
                for p in providers:
                    name = p.get("provider_name", "").lower()
                    for key, svc in TMDB_SVC_MAP.items():
                        if key in name:
                            if svc == "discovery":
                                uuid = await fetch_discovery_uuid(client, show_title)
                                if uuid: ext_ids["discovery_uuid"] = uuid
                            results[sid] = svc
                            deep_links[sid] = build_deep_link(svc, show_title, ext_ids)
                            break
                    if sid in results: break
            except: pass
            await asyncio.sleep(0.15)
    d = load_data()
    manual = d.get("manual_services", {})
    # Never overwrite manually set services
    auto_results = {k: v for k, v in results.items() if k not in manual}
    auto_links = {k: v for k, v in deep_links.items() if v and k not in manual}
    d["services"].update(auto_results)
    d.setdefault("deep_links", {}).update(auto_links)
    save_data(d)
    return {"results": results, "auto_updated": len(auto_results), "scanned": len(shows), "found": len(results)}

# ── Fire TV launch ────────────────────────────────────────────────────────
async def get_resumed_activity(client) -> str:
    try:
        r = await ha_adb(client, "dumpsys activity activities | grep mResumedActivity")
        data = r.json()
        if isinstance(data, list) and data:
            return data[0].get("attributes", {}).get("adb_response", "")
        elif isinstance(data, dict):
            return data.get("attributes", {}).get("adb_response", "")
    except: pass
    return ""

@app.post("/api/firetv/launch")
async def firetv_launch(request: Request):
    body = await request.json()
    svc = body.get("service")
    profile_index = body.get("profileIndex", 0)
    show_id = body.get("showId")
    launch = APP_LAUNCH.get(svc)
    if not launch: raise HTTPException(400, f"Unknown service: {svc}")
    pkg, component = launch
    profiles = APP_PROFILES.get(svc, [])
    profile_name = profiles[profile_index] if profile_index < len(profiles) else ""
    deep_link = None
    if show_id:
        d = load_data()
        deep_link = d.get("deep_links", {}).get(str(show_id))
    needs_profile = profiles and len(profiles) > 1
    timing = LAUNCH_TIMING.get(svc, LAUNCH_TIMING["default"])

    async with httpx.AsyncClient() as client:
        await ha_call(client, "media_player", "turn_on", {"entity_id": FIRETV_ENT})
        await asyncio.sleep(2.0)
        await ha_adb(client, f"am force-stop {pkg}")
        await asyncio.sleep(1.5)
        if component:
            await ha_adb(client, f"am start -n {component}")
        else:
            await ha_adb(client, f"monkey -p {pkg} 1")

        # profile_index=-1 = handoff mode: just launch app, user handles profile/PIN
        if profile_index >= 0 and needs_profile:
            await asyncio.sleep(timing["pre_profile"])
            for _ in range(profile_index):
                await ha_adb(client, "input keyevent KEYCODE_DPAD_RIGHT")
                await asyncio.sleep(0.3)
            await ha_adb(client, "input keyevent KEYCODE_DPAD_CENTER")
            if deep_link:
                await asyncio.sleep(timing["post_profile"])
                await ha_adb(client, f'am start -a android.intent.action.VIEW -d "{deep_link}" -n {component} --activity-clear-task' if component else f'am start -a android.intent.action.VIEW -d "{deep_link}" {pkg}')
        elif profile_index >= 0 and deep_link:
            await asyncio.sleep(timing["pre_profile"])
            await ha_adb(client, f'am start -a android.intent.action.VIEW -d "{deep_link}" -n {component} --activity-clear-task' if component else f'am start -a android.intent.action.VIEW -d "{deep_link}" {pkg}')

    return {"ok": True, "service": svc, "package": pkg, "profile": profile_name, "deep_link": deep_link}


@app.post("/api/firetv/deeplink")
async def firetv_deeplink(request: Request):
    body = await request.json()
    svc = body.get("service")
    show_id = body.get("showId")
    launch = APP_LAUNCH.get(svc)
    if not launch:
        raise HTTPException(400, f"Unknown service: {svc}")
    pkg = launch[0]
    deep_link = None
    if show_id:
        d = load_data()
        deep_link = d.get("deep_links", {}).get(str(show_id))
    if not deep_link:
        raise HTTPException(404, "No deep link for this show — run Scan first")
    async with httpx.AsyncClient() as client:
        await ha_adb(client, f'am start -a android.intent.action.VIEW -d "{deep_link}" -n {component} --activity-clear-task' if component else f'am start -a android.intent.action.VIEW -d "{deep_link}" {pkg}')
    return {"ok": True, "deep_link": deep_link}

@app.post("/api/firetv/command")
async def firetv_command(request: Request):
    body = await request.json()
    cmd = body.get("command")
    if not cmd: raise HTTPException(400, "command required")
    async with httpx.AsyncClient() as client:
        if cmd.startswith("KEYCODE_"):
            await ha_adb(client, f"input keyevent {cmd}")
        else:
            key_map = {
                "play_pause":"KEYCODE_MEDIA_PLAY_PAUSE","back":"KEYCODE_BACK","home":"KEYCODE_HOME",
                "up":"KEYCODE_DPAD_UP","down":"KEYCODE_DPAD_DOWN","left":"KEYCODE_DPAD_LEFT",
                "right":"KEYCODE_DPAD_RIGHT","select":"KEYCODE_DPAD_CENTER",
                "rewind":"KEYCODE_MEDIA_REWIND","forward":"KEYCODE_MEDIA_FAST_FORWARD",
                "vol_up":"KEYCODE_VOLUME_UP","vol_down":"KEYCODE_VOLUME_DOWN",
            }
            keycode = key_map.get(cmd, cmd)
            await ha_adb(client, f"input keyevent {keycode}")
    return {"ok": True}

# ── Sonos ─────────────────────────────────────────────────────────────────
@app.get("/api/sonos/state")
async def sonos_state():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{HA_URL}/api/states/{SONOS_ENT}",
            headers={"Authorization": f"Bearer {HA_TOKEN}"}, timeout=10)
        s = r.json()
        attrs = s.get("attributes", {})
        return {
            "state": s.get("state"),
            "volume": attrs.get("volume_level", 0),
            "muted": attrs.get("is_volume_muted", False),
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
            await ha_call(client, "media_player", "volume_mute", {"entity_id": SONOS_ENT, "is_volume_muted": not body.get("muted", False)})
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8099, log_level="info")
