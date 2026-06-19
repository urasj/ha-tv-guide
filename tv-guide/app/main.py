import os, json, asyncio, re, httpx
from datetime import datetime, timezone
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
LG_ENT      = os.environ.get("LG_ENTITY", "media_player.lg_webos_tv_oled65c3aua_2")
HELPER_URL  = os.environ.get("HELPER_URL", "http://192.168.7.211:8472").rstrip("/")
INGRESS_PATH = os.environ.get("INGRESS_PATH", "").rstrip("/")
TMDB_BASE   = "https://api.themoviedb.org/3"

# Profile definitions
APP_PROFILES = {
    "netflix":   ["justinuras", "Vicki uras", "Tony", "Justin", "Kristen"],
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

# Per-app profile navigation. "blind" = can't read the screen (Netflix), so
# slam the cursor to a known edge then step a fixed number. Apps not listed here
# default to accessibility tap-by-name via the helper.
PROFILE_NAV = {
    "netflix": {"method": "blind", "slam_key": 19, "slam_count": 8, "step_key": 20,
                "select_key": 23, "gap": 0.5, "settle": 3.0, "pre": 12, "post": 8},
}

# ── Persistence ───────────────────────────────────────────────────────────
def load_data():
    if DATA_FILE.exists():
        try: return json.loads(DATA_FILE.read_text())
        except: pass
    return {"watched": {}, "services": {}, "deep_links": {}, "progress": {}, "manual_services": {}, "archived": [], "removed": []}

def save_data(d):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(d, indent=2))

# ── App ───────────────────────────────────────────────────────────────────
app = FastAPI(title="TV Guide")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="/app/static"), name="static")

# ── HA helpers ────────────────────────────────────────────────────────────
async def ha_call(client, domain, service, data, timeout=10):
    r = await client.post(
        f"{HA_URL}/api/services/{domain}/{service}",
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
        json=data, timeout=timeout
    )
    return r

async def ha_adb(client, command, timeout=45):
    return await ha_call(client, "androidtv", "adb_command",
                         {"entity_id": FIRETV_ENT, "command": command}, timeout=timeout)

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
            archived_set = {str(x) for x in d.get("archived", [])}
            result = []
            for s in shows:
                sid = str(s["id"])
                # Sonarr v3 nests counts under "statistics", not top-level.
                stats = s.get("statistics", {}) or {}
                season_count = stats.get("seasonCount")
                if season_count is None:
                    season_count = len([se for se in s.get("seasons", []) if se.get("seasonNumber", 0) > 0])
                result.append({
                    "id": s["id"],
                    "title": s["title"],
                    "status": s.get("status"),
                    "year": s.get("year"),
                    "network": s.get("network"),
                    "overview": s.get("overview", ""),
                    "monitored": s.get("monitored", False),
                    "nextAiring": s.get("nextAiring"),
                    "previousAiring": s.get("previousAiring"),
                    "images": s.get("images", []),
                    "poster": f"{SONARR_URL}/api/v3/mediacover/{s['id']}/poster.jpg?apikey={SONARR_KEY}",
                    "fanart": f"{SONARR_URL}/api/v3/mediacover/{s['id']}/fanart.jpg?apikey={SONARR_KEY}",
                    "seasonCount": season_count,
                    "episodeCount": stats.get("episodeCount", 0),
                    "totalEpisodeCount": stats.get("totalEpisodeCount", 0),
                    "episodeFileCount": stats.get("episodeFileCount", 0),
                    "tvdbId": s.get("tvdbId"),
                    "genres": s.get("genres", []),
                    "service": d["services"].get(sid),
                    "deep_link": d.get("deep_links", {}).get(sid),
                    "archived": sid in archived_set,
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

# ── Next up / Continue Watching ─────────────────────────────────────────────
def _parse_air(ad):
    if not ad:
        return None
    try:
        return datetime.fromisoformat(str(ad).replace("Z", "+00:00"))
    except Exception:
        return None

@app.get("/api/nextup")
async def next_up():
    """For every series, compute the next unwatched AIRED episode (where you left off),
    plus aired/watched/unwatched counts. Powers the real Continue Watching row."""
    if not SONARR_URL or not SONARR_KEY:
        raise HTTPException(503, "Sonarr not configured")
    d = load_data()
    watched_store = d.get("watched", {})
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient() as client:
        sr = await client.get(f"{SONARR_URL}/api/v3/series",
                              headers={"X-Api-Key": SONARR_KEY}, timeout=20)
        if sr.status_code != 200:
            raise HTTPException(502, f"Sonarr returned {sr.status_code}")
        series = sr.json()

        async def for_show(s):
            sid = str(s["id"])
            try:
                er = await client.get(f"{SONARR_URL}/api/v3/episode",
                                      headers={"X-Api-Key": SONARR_KEY},
                                      params={"seriesId": s["id"]}, timeout=20)
                eps = er.json() if er.status_code == 200 else []
            except Exception:
                eps = []
            watched_ids = set(watched_store.get(sid, []))
            aired = []
            for e in eps:
                if e.get("seasonNumber", 0) == 0:
                    continue
                when = _parse_air(e.get("airDateUtc"))
                if when and when <= now:
                    aired.append((e.get("seasonNumber", 0), e.get("episodeNumber", 0), e))
            aired.sort(key=lambda x: (x[0], x[1]))
            watched_count = sum(1 for _, _, e in aired if e["id"] in watched_ids)
            next_ep = None
            for sn, en, e in aired:
                if e["id"] not in watched_ids:
                    next_ep = {
                        "id": e["id"], "season": sn, "episode": en,
                        "title": e.get("title"), "airDateUtc": e.get("airDateUtc"),
                        "hasFile": e.get("hasFile", False),
                    }
                    break
            return sid, {
                "next": next_ep,
                "aired": len(aired),
                "watched": watched_count,
                "unwatched": len(aired) - watched_count,
                "started": watched_count > 0,
            }

        results = await asyncio.gather(*[for_show(s) for s in series])
    return {sid: info for sid, info in results}

# ── Watched ───────────────────────────────────────────────────────────────
@app.post("/api/shows/{show_id}/watched/{ep_id}")
async def mark_watched(show_id: int, ep_id: int):
    d = load_data()
    sid = str(show_id)
    if sid not in d["watched"]: d["watched"][sid] = []
    if ep_id not in d["watched"][sid]: d["watched"][sid].append(ep_id)
    save_data(d)
    return {"ok": True}

@app.post("/api/shows/{show_id}/watched-bulk")
async def mark_watched_bulk(show_id: int, request: Request):
    """Mark/unmark many episodes at once. Body: {"ep_ids": [...], "watched": true|false}."""
    body = await request.json()
    ep_ids = [int(x) for x in body.get("ep_ids", [])]
    mark = body.get("watched", True)
    d = load_data()
    sid = str(show_id)
    cur = set(d["watched"].get(sid, []))
    if mark:
        cur.update(ep_ids)
    else:
        cur.difference_update(ep_ids)
    d["watched"][sid] = sorted(cur)
    save_data(d)
    return {"ok": True, "count": len(d["watched"][sid])}

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
    # Accept optional deep_link override (used when manually assigning a service)
    forced_link = body.get("deep_link")
    if forced_link:
        d.setdefault("deep_links", {})[str(show_id)] = forced_link
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

async def fetch_disney_entity_id(client: httpx.AsyncClient, tmdb_id: int) -> str | None:
    """Fetch Disney+ entity ID from TMDB external IDs to build direct show URL."""
    try:
        # TMDB doesn't expose Disney+ IDs directly, but we can try their content search
        r = await client.get(
            f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids",
            params={"api_key": TMDB_KEY}, timeout=10
        )
        if r.status_code == 200:
            ids = r.json()
            # Disney+ sometimes exposes IDs via TVDB/IMDB which we can use
            return None  # No direct Disney entity ID from TMDB
    except Exception:
        pass
    return None

def build_deep_link(svc: str, title: str, ext_ids: dict) -> str:
    from urllib.parse import quote
    q = quote(title)
    slug = slugify(title)
    if svc == "netflix" and ext_ids.get("netflix"):
        return f"https://www.netflix.com/title/{ext_ids['netflix']}"
    if svc == "discovery" and ext_ids.get("discovery_uuid"):
        return f"https://play.discoveryplus.com/show/{ext_ids['discovery_uuid']}"
    urls = {
        # URL formats matched to each app's registered intent filter paths
        "netflix":   f"https://www.netflix.com/search?q={q}",           # netflix uses /search
        "hulu":      f"https://www.hulu.com/series/{slug}",              # hulu: /series/slug
        "disney":    f"https://www.disneyplus.com/browse/entity-{ext_ids['disney_entity_id']}" if ext_ids.get('disney_entity_id') else f"https://www.disneyplus.com/series/{slug}",
        "max":       f"https://play.max.com/show/{slug}",                # max: /show/slug
        "peacock":   f"https://www.peacocktv.com/watch/series/{slug}",   # peacock: /watch/series/
        "discovery": f"https://play.discoveryplus.com/show/{slug}",      # confirmed working
        "prime":     f"https://www.amazon.com/gp/video/detail/{slug}",  # prime: /gp/video/detail/
        "apple":     f"https://tv.apple.com/show/{slug}",               # apple: /show/
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

# ── Add to library (Sonarr) ──────────────────────────────────────────────────
@app.get("/api/search")
async def search_series(term: str):
    if not SONARR_URL or not SONARR_KEY:
        raise HTTPException(503, "Sonarr not configured")
    if not term.strip():
        return []
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SONARR_URL}/api/v3/series/lookup",
                             headers={"X-Api-Key": SONARR_KEY}, params={"term": term}, timeout=20)
        if r.status_code != 200:
            raise HTTPException(502, f"Sonarr lookup returned {r.status_code}")
        out = []
        for s in r.json()[:20]:
            imgs = s.get("images", [])
            poster = next((i.get("remoteUrl") or i.get("url") for i in imgs if i.get("coverType") == "poster"), None)
            out.append({
                "tvdbId": s.get("tvdbId"),
                "title": s.get("title"),
                "year": s.get("year"),
                "overview": s.get("overview", ""),
                "network": s.get("network"),
                "status": s.get("status"),
                "poster": poster,
                "added": bool(s.get("id")),
            })
        return out

async def _sonarr_defaults(client):
    qp = await client.get(f"{SONARR_URL}/api/v3/qualityprofile", headers={"X-Api-Key": SONARR_KEY}, timeout=15)
    rf = await client.get(f"{SONARR_URL}/api/v3/rootfolder", headers={"X-Api-Key": SONARR_KEY}, timeout=15)
    profiles = qp.json() if qp.status_code == 200 else []
    folders = rf.json() if rf.status_code == 200 else []
    lang = []
    try:
        lr = await client.get(f"{SONARR_URL}/api/v3/languageprofile", headers={"X-Api-Key": SONARR_KEY}, timeout=15)
        if lr.status_code == 200:
            lang = lr.json()
    except Exception:
        pass
    return profiles, folders, lang

@app.get("/api/sonarr/meta")
async def sonarr_meta():
    if not SONARR_URL or not SONARR_KEY:
        raise HTTPException(503, "Sonarr not configured")
    async with httpx.AsyncClient() as client:
        profiles, folders, lang = await _sonarr_defaults(client)
    return {
        "qualityProfiles": [{"id": p["id"], "name": p["name"]} for p in profiles],
        "rootFolders": [{"path": f["path"], "freeSpace": f.get("freeSpace")} for f in folders],
        "hasLanguageProfile": bool(lang),
    }

@app.post("/api/add")
async def add_series(request: Request):
    if not SONARR_URL or not SONARR_KEY:
        raise HTTPException(503, "Sonarr not configured")
    body = await request.json()
    tvdb = body.get("tvdbId")
    if not tvdb:
        raise HTTPException(400, "tvdbId required")
    monitor = body.get("monitor", "all")
    do_search = bool(body.get("search", False))
    async with httpx.AsyncClient() as client:
        lr = await client.get(f"{SONARR_URL}/api/v3/series/lookup",
                              headers={"X-Api-Key": SONARR_KEY}, params={"term": f"tvdb:{tvdb}"}, timeout=20)
        if lr.status_code != 200 or not lr.json():
            raise HTTPException(502, "Sonarr lookup failed")
        series = lr.json()[0]
        if series.get("id"):
            raise HTTPException(409, "Already in library")
        profiles, folders, lang = await _sonarr_defaults(client)
        if not profiles or not folders:
            raise HTTPException(500, "Sonarr has no quality profile or root folder configured")
        series.update({
            "qualityProfileId": body.get("qualityProfileId") or profiles[0]["id"],
            "rootFolderPath": body.get("rootFolderPath") or folders[0]["path"],
            "monitored": monitor != "none",
            "seasonFolder": True,
            "addOptions": {"monitor": monitor, "searchForMissingEpisodes": do_search, "searchForCutoffUnmetEpisodes": False},
        })
        if lang:
            series["languageProfileId"] = lang[0]["id"]
        ar = await client.post(f"{SONARR_URL}/api/v3/series",
                               headers={"X-Api-Key": SONARR_KEY, "Content-Type": "application/json"},
                               json=series, timeout=30)
        if ar.status_code not in (200, 201):
            raise HTTPException(502, f"Sonarr add failed ({ar.status_code}): {ar.text[:300]}")
        added = ar.json()
        new_id = added.get("id")
        # Auto-detect streaming service + deep link via TMDB (same logic as Scan).
        service = None
        deep_link = None
        if TMDB_KEY and new_id:
            try:
                fr = await client.get(f"{TMDB_BASE}/find/{tvdb}",
                                      params={"api_key": TMDB_KEY, "external_source": "tvdb_id"}, timeout=10)
                tv = fr.json().get("tv_results", []) if fr.status_code == 200 else []
                if tv:
                    tmdb_id = tv[0]["id"]
                    show_title = series.get("title") or tv[0].get("name", "")
                    er = await client.get(f"{TMDB_BASE}/tv/{tmdb_id}/external_ids",
                                          params={"api_key": TMDB_KEY}, timeout=10)
                    ext_ids = er.json() if er.status_code == 200 else {}
                    pr = await client.get(f"{TMDB_BASE}/tv/{tmdb_id}/watch/providers",
                                          params={"api_key": TMDB_KEY}, timeout=10)
                    us = pr.json().get("results", {}).get("US", {}) if pr.status_code == 200 else {}
                    providers = us.get("flatrate", []) + us.get("free", []) + us.get("ads", [])
                    for p in providers:
                        nm = p.get("provider_name", "").lower()
                        for key, svc in TMDB_SVC_MAP.items():
                            if key in nm:
                                if svc == "discovery":
                                    uuid = await fetch_discovery_uuid(client, show_title)
                                    if uuid:
                                        ext_ids["discovery_uuid"] = uuid
                                service = svc
                                deep_link = build_deep_link(svc, show_title, ext_ids)
                                break
                        if service:
                            break
                    if service:
                        d = load_data()
                        d["services"][str(new_id)] = service
                        if deep_link:
                            d.setdefault("deep_links", {})[str(new_id)] = deep_link
                        save_data(d)
            except Exception:
                pass
    return {"ok": True, "id": new_id, "title": added.get("title"), "service": service, "deep_link": deep_link}

# ── Helper app proxy (Fire Stick companion) ──────────────────────────────────
@app.api_route("/api/helper/{path:path}", methods=["GET", "POST"])
async def helper_proxy(path: str, request: Request):
    body = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
    async with httpx.AsyncClient() as client:
        try:
            if request.method == "POST":
                r = await client.post(f"{HELPER_URL}/{path}", json=body, timeout=20)
            else:
                r = await client.get(f"{HELPER_URL}/{path}", timeout=20)
        except Exception as e:
            raise HTTPException(502, f"Helper not reachable at {HELPER_URL}: {e}")
    try:
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception:
        return JSONResponse({"raw": r.text[:2000]}, status_code=r.status_code)

# ── Play: reliable launch + profile select + deep-link (via helper) ──────────
async def _do_play(svc, pkg, profiles, profile_index, nav, deep_link):
    """Runs in the background so the HTTP request returns instantly."""
    async with httpx.AsyncClient() as client:
        # Cold-start the app when we need its profile screen (so presses aren't lost).
        if profile_index is not None and profile_index >= 0 and len(profiles) > 1:
            try:
                await ha_adb(client, f"am force-stop {pkg}")
                await asyncio.sleep(1.0)
            except Exception:
                pass
        # 1) Reliable native launch via the helper (fall back to ADB).
        used_helper = True
        try:
            r = await client.post(f"{HELPER_URL}/launch", json={"package": pkg}, timeout=15)
            used_helper = (r.status_code == 200)
        except Exception:
            used_helper = False
        if not used_helper:
            try:
                await ha_call(client, "media_player", "turn_on", {"entity_id": FIRETV_ENT})
                await asyncio.sleep(2)
                await ha_adb(client, f"monkey -p {pkg} 1")
            except Exception:
                pass

        # 2) Profile selection.
        if profile_index is not None and profile_index >= 0 and len(profiles) > 1:
            if nav and nav.get("method") == "blind":
                await asyncio.sleep(nav.get("pre", 6))
                gap = nav.get("gap", 0.45)
                # Navigation only (one short command).
                seq = ("input keyevent %d; sleep %s; " % (nav["slam_key"], gap)) * nav["slam_count"]
                seq += ("input keyevent %d; sleep %s; " % (nav["step_key"], gap)) * int(profile_index)
                seq = seq.strip().rstrip(";").strip()
                try:
                    await ha_adb(client, seq)
                except Exception:
                    pass
                # Settle in Python, then fire the SELECT as its own clean press
                # (a long sleep inside one ADB command gets cut off before the press lands).
                await asyncio.sleep(nav.get("settle", 2.0))
                try:
                    await ha_adb(client, "input keyevent %d" % nav["select_key"])
                except Exception:
                    pass
                await asyncio.sleep(nav.get("post", 8))
            else:
                name = profiles[profile_index] if profile_index < len(profiles) else ""
                await asyncio.sleep(5)
                try:
                    await client.post(f"{HELPER_URL}/selectprofile", json={"name": name}, timeout=15)
                except Exception:
                    pass
                await asyncio.sleep(4)

        # 3) Deep-link into the title.
        if deep_link:
            try:
                await client.post(f"{HELPER_URL}/deeplink", json={"package": pkg, "url": deep_link}, timeout=15)
            except Exception:
                try:
                    await ha_adb(client, f'am start -a android.intent.action.VIEW -d "{deep_link}" {pkg}')
                except Exception:
                    pass

@app.post("/api/firetv/play")
async def firetv_play(request: Request):
    body = await request.json()
    svc = body.get("service")
    show_id = body.get("showId")
    profile_index = body.get("profileIndex")
    profile_name = body.get("profile")
    launch = APP_LAUNCH.get(svc)
    if not launch:
        raise HTTPException(400, f"Unknown service: {svc}")
    pkg = launch[0]
    profiles = APP_PROFILES.get(svc, [])
    if (profile_index is None) and profile_name and profile_name in profiles:
        profile_index = profiles.index(profile_name)
    deep_link = load_data().get("deep_links", {}).get(str(show_id)) if show_id else None
    nav = PROFILE_NAV.get(svc)
    asyncio.create_task(_do_play(svc, pkg, profiles, profile_index, nav, deep_link))
    return {"ok": True, "started": True, "service": svc, "profile_index": profile_index, "deep_link": deep_link}

# ── Capture deep-link (read what the Fire TV's Play button fired) ─────────────
@app.get("/api/firetv/capture")
async def firetv_capture():
    """Best-effort: pull the most recent streaming deep-link the Fire TV launched
    (e.g. the URL behind the universal-search Play button). Call right after pressing
    Play on the Fire TV; returns any netflix/disney/max/etc play URLs seen in logcat."""
    async with httpx.AsyncClient() as client:
        try:
            r = await ha_adb(
                client,
                "logcat -d -t 600 2>/dev/null | grep -oE 'https?://[^ \"]+' | "
                "grep -iE 'netflix|disneyplus|play.max|primevideo|peacocktv|hulu|paramountplus|discoveryplus' | tail -8",
                timeout=30,
            )
        except Exception as e:
            raise HTTPException(502, f"capture failed: {e}")
    resp = ""
    try:
        data = r.json()
        if isinstance(data, list) and data:
            resp = data[0].get("attributes", {}).get("adb_response", "") or ""
        elif isinstance(data, dict):
            resp = data.get("attributes", {}).get("adb_response", "") or ""
    except Exception:
        pass
    links = []
    for line in resp.splitlines():
        line = line.strip()
        if line and line.startswith("http") and line not in links:
            links.append(line)
    return {"ok": True, "links": links, "latest": links[-1] if links else None}

# ── Archive / remove / restore ───────────────────────────────────────────────
async def _sonarr_add(client, tvdb, monitor="all", search=False):
    lr = await client.get(f"{SONARR_URL}/api/v3/series/lookup",
                          headers={"X-Api-Key": SONARR_KEY}, params={"term": f"tvdb:{tvdb}"}, timeout=20)
    if lr.status_code != 200 or not lr.json():
        raise HTTPException(502, "Sonarr lookup failed")
    series = lr.json()[0]
    if series.get("id"):
        return series
    profiles, folders, lang = await _sonarr_defaults(client)
    if not profiles or not folders:
        raise HTTPException(500, "Sonarr has no quality profile or root folder configured")
    series.update({
        "qualityProfileId": profiles[0]["id"],
        "rootFolderPath": folders[0]["path"],
        "monitored": monitor != "none",
        "seasonFolder": True,
        "addOptions": {"monitor": monitor, "searchForMissingEpisodes": search, "searchForCutoffUnmetEpisodes": False},
    })
    if lang:
        series["languageProfileId"] = lang[0]["id"]
    ar = await client.post(f"{SONARR_URL}/api/v3/series",
                           headers={"X-Api-Key": SONARR_KEY, "Content-Type": "application/json"},
                           json=series, timeout=30)
    if ar.status_code not in (200, 201):
        raise HTTPException(502, f"Sonarr add failed ({ar.status_code})")
    return ar.json()

@app.post("/api/shows/{show_id}/archive")
async def archive_show(show_id: int):
    d = load_data()
    d.setdefault("archived", [])
    if str(show_id) not in [str(x) for x in d["archived"]]:
        d["archived"].append(show_id)
    save_data(d)
    return {"ok": True}

@app.post("/api/shows/{show_id}/unarchive")
async def unarchive_show(show_id: int):
    d = load_data()
    d["archived"] = [x for x in d.get("archived", []) if str(x) != str(show_id)]
    save_data(d)
    return {"ok": True}

@app.delete("/api/shows/{show_id}")
async def remove_series(show_id: int):
    if not SONARR_URL or not SONARR_KEY:
        raise HTTPException(503, "Sonarr not configured")
    d = load_data()
    sid = str(show_id)
    meta = {}
    async with httpx.AsyncClient() as client:
        try:
            gr = await client.get(f"{SONARR_URL}/api/v3/series/{show_id}",
                                  headers={"X-Api-Key": SONARR_KEY}, timeout=15)
            if gr.status_code == 200:
                s = gr.json()
                imgs = s.get("images", [])
                poster = next((i.get("remoteUrl") or i.get("url") for i in imgs if i.get("coverType") == "poster"), None)
                meta = {"tvdbId": s.get("tvdbId"), "title": s.get("title"),
                        "year": s.get("year"), "network": s.get("network"), "poster": poster}
        except Exception:
            pass
        dr = await client.delete(f"{SONARR_URL}/api/v3/series/{show_id}",
                                 headers={"X-Api-Key": SONARR_KEY},
                                 params={"deleteFiles": "false", "addImportListExclusion": "false"}, timeout=30)
        if dr.status_code not in (200, 202, 204):
            raise HTTPException(502, f"Sonarr delete failed ({dr.status_code})")
    entry = {**meta, "id": show_id,
             "service": d.get("services", {}).get(sid),
             "deep_link": d.get("deep_links", {}).get(sid),
             "removedAt": datetime.now(timezone.utc).isoformat()}
    d.setdefault("removed", [])
    d["removed"] = [r for r in d["removed"] if str(r.get("tvdbId")) != str(meta.get("tvdbId"))]
    d["removed"].insert(0, entry)
    d["removed"] = d["removed"][:100]
    d["archived"] = [x for x in d.get("archived", []) if str(x) != sid]
    for k in ("services", "deep_links", "watched", "manual_services"):
        if isinstance(d.get(k), dict):
            d[k].pop(sid, None)
    save_data(d)
    return {"ok": True, "removed": entry.get("title")}

@app.get("/api/removed")
async def get_removed():
    return load_data().get("removed", [])

@app.delete("/api/removed/{tvdb}")
async def purge_removed(tvdb: int):
    d = load_data()
    d["removed"] = [r for r in d.get("removed", []) if str(r.get("tvdbId")) != str(tvdb)]
    save_data(d)
    return {"ok": True}

@app.post("/api/restore")
async def restore_series(request: Request):
    if not SONARR_URL or not SONARR_KEY:
        raise HTTPException(503, "Sonarr not configured")
    body = await request.json()
    tvdb = body.get("tvdbId")
    if not tvdb:
        raise HTTPException(400, "tvdbId required")
    d = load_data()
    entry = next((r for r in d.get("removed", []) if str(r.get("tvdbId")) == str(tvdb)), None)
    async with httpx.AsyncClient() as client:
        added = await _sonarr_add(client, tvdb, "all", False)
    new_id = added.get("id")
    nsid = str(new_id)
    if entry:
        if entry.get("service"):
            d.setdefault("services", {})[nsid] = entry["service"]
        if entry.get("deep_link"):
            d.setdefault("deep_links", {})[nsid] = entry["deep_link"]
    d["removed"] = [r for r in d.get("removed", []) if str(r.get("tvdbId")) != str(tvdb)]
    save_data(d)
    return {"ok": True, "id": new_id, "title": added.get("title")}

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
    profile_name = profiles[profile_index] if (profiles and 0 <= profile_index < len(profiles)) else ""
    deep_link = None
    if show_id:
        d = load_data()
        deep_link = d.get("deep_links", {}).get(str(show_id))
    needs_profile = profiles and len(profiles) > 1
    timing = LAUNCH_TIMING.get(svc, LAUNCH_TIMING["default"])

    async with httpx.AsyncClient() as client:
        # Smart launch: if the target app is already foreground, just deep-link — don't restart it.
        if deep_link and pkg:
            fg = await get_resumed_activity(client)
            if pkg in (fg or ""):
                await ha_adb(client, f'am start -a android.intent.action.VIEW -d "{deep_link}" {pkg}')
                return {"ok": True, "service": svc, "package": pkg, "already_running": True, "deep_linked": True, "deep_link": deep_link}
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
                await ha_adb(client, f'am start -a android.intent.action.VIEW -d "{deep_link}" {pkg}')
        elif profile_index >= 0 and deep_link:
            await asyncio.sleep(timing["pre_profile"])
            await ha_adb(client, f'am start -a android.intent.action.VIEW -d "{deep_link}" {pkg}')

    return {"ok": True, "service": svc, "package": pkg, "profile": profile_name, "deep_link": deep_link}


@app.post("/api/firetv/deeplink")
async def firetv_deeplink(request: Request):
    body = await request.json()
    svc = body.get("service")
    show_id = body.get("showId")
    launch = APP_LAUNCH.get(svc)
    if not launch:
        raise HTTPException(400, f"Unknown service: {svc}")
    pkg, component = launch
    deep_link = None
    if show_id:
        d = load_data()
        deep_link = d.get("deep_links", {}).get(str(show_id))
    if not deep_link:
        raise HTTPException(404, "No deep link stored — open the show and run Scan first")
    async with httpx.AsyncClient() as client:
        await ha_adb(client, f'am start -a android.intent.action.VIEW -d "{deep_link}" {pkg}')
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

# ── Power (Fire TV + LG TV) ──────────────────────────────────────────────────
async def _ha_state(client, ent):
    try:
        r = await client.get(f"{HA_URL}/api/states/{ent}",
                             headers={"Authorization": f"Bearer {HA_TOKEN}"}, timeout=10)
        return r.json().get("state") if r.status_code == 200 else None
    except Exception:
        return None

def _is_on(state):
    return state not in (None, "off", "unavailable", "standby", "idle")

@app.get("/api/power/state")
async def power_state():
    async with httpx.AsyncClient() as client:
        f = await _ha_state(client, FIRETV_ENT)
        l = await _ha_state(client, LG_ENT)
    return {"firetv": f, "lg": l, "on": _is_on(f) or _is_on(l)}

@app.post("/api/power")
async def power(request: Request):
    body = await request.json()
    action = body.get("action", "toggle")
    async with httpx.AsyncClient() as client:
        if action == "toggle":
            f = await _ha_state(client, FIRETV_ENT)
            l = await _ha_state(client, LG_ENT)
            action = "off" if (_is_on(f) or _is_on(l)) else "on"
        service = "turn_on" if action == "on" else "turn_off"
        await ha_call(client, "media_player", service, {"entity_id": [FIRETV_ENT, LG_ENT]})
    return {"ok": True, "action": action}

# ── Sonos ─────────────────────────────────────────────────────────────────
@app.get("/api/sonos/state")
async def sonos_state():
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {HA_TOKEN}"}
        r = await client.get(f"{HA_URL}/api/states/{SONOS_ENT}", headers=headers, timeout=10)
        s = r.json()
        attrs = s.get("attributes", {})
        # Fetch speech enhancement and night sound switch states
        se_r = await client.get(f"{HA_URL}/api/states/switch.living_room_speech_enhancement", headers=headers, timeout=10)
        ns_r = await client.get(f"{HA_URL}/api/states/switch.living_room_night_sound", headers=headers, timeout=10)
        return {
            "state": s.get("state"),
            "volume": attrs.get("volume_level", 0),
            "muted": attrs.get("is_volume_muted", False),
            "speech_enhancement": se_r.json().get("state") == "on" if se_r.status_code == 200 else False,
            "night_mode": ns_r.json().get("state") == "on" if ns_r.status_code == 200 else False,
        }

@app.post("/api/sonos/command")
async def sonos_command(request: Request):
    body = await request.json()
    cmd = body.get("command")
    async with httpx.AsyncClient() as client:
        if cmd == "volume_up":
            vol = round(min(1.0, float(body.get("current", 0.3)) + 0.05), 2)
            await ha_call(client, "media_player", "volume_set", {"entity_id": SONOS_ENT, "volume_level": vol})
        elif cmd == "volume_down":
            vol = round(max(0.0, float(body.get("current", 0.3)) - 0.05), 2)
            await ha_call(client, "media_player", "volume_set", {"entity_id": SONOS_ENT, "volume_level": vol})
        elif cmd == "mute":
            # body.muted is current state, we want to toggle so pass NOT current
            await ha_call(client, "media_player", "volume_mute", {"entity_id": SONOS_ENT, "is_volume_muted": not body.get("muted", False)})
        elif cmd == "speech_enhancement":
            # body.state is the NEW desired state
            svc = "turn_on" if body.get("state", False) else "turn_off"
            await ha_call(client, "switch", svc, {"entity_id": "switch.living_room_speech_enhancement"})
        elif cmd == "night_mode":
            svc = "turn_on" if body.get("state", False) else "turn_off"
            await ha_call(client, "switch", svc, {"entity_id": "switch.living_room_night_sound"})
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8099, log_level="info")
