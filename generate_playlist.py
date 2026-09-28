#!/usr/bin/env python3
"""
SoccerSurge -> IPTV playlist generator (v4.1 — anti-ads, fixed route handler)
"""

import asyncio
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from camoufox.async_api import AsyncCamoufox

# ------------------------- Cấu hình -------------------------
BASE_URL    = "https://soccersurge.io/"
OUTPUT      = Path(os.environ.get("OUTPUT", "playlist.m3u"))
MAX_GAMES   = int(os.environ.get("MAX_GAMES", "0")) or None
MAX_SITES   = int(os.environ.get("MAX_SITES", "8"))
MAX_STREAMS = int(os.environ.get("MAX_STREAMS", "3"))
CF_TIMEOUT  = int(os.environ.get("CF_TIMEOUT", "90"))
WAIT_MASTER = int(os.environ.get("WAIT_MASTER", "30"))

_CAMOUFOX_OS = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"} \
    .get(platform.system(), "linux")
HEADLESS = not bool(os.environ.get("DISPLAY"))

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# ============================================================
# BLOCK ad/tracker
# ============================================================
AD_BLOCK_RE = re.compile(
    r"("
    r"doubleclick\.net|googlesyndication|googleadservices|googletagmanager|"
    r"google-analytics|adservice\.google|adnxs\.com|adsrvr\.org|"
    r"taboola|outbrain|criteo|pubmatic|rubiconproject|openx\.net|"
    r"smartadserver|adform\.net|casalemedia|sharethrough|yieldmo|"
    r"highperformanceformat\.com|effectivecpmnetwork\.com|"
    r"violentlinedexploit\.com|recollectsideway\.com|"
    r"nudgebelonged\.com|reliedhounder\.com|lauansaltire\.com|"
    r"driverhugoverblown\.com|pschenttidier\.com|acscdn\.com|"
    r"jnbhi\.com|jads\.co|exoclick|exosrv|trafficjunky|"
    r"popcash|popads|propellerads|onclickads|mgid\.com|"
    r"histats\.com|amung\.us|waust\.at|livelog\.site|"
    r"cloudflareinsights\.com|beacon\.min\.js|steast\.io|"
    r"static\.cloudflareinsights|"
    r"/(ads?|adserver|adframe|popunder|preroll|vast|vpaid)/|"
    r"invoke\.js|/tag\.min\.js|/s\.js|/d\.js|/classic\.js|"
    r"ads\.htm|/ads\.|/ad\.html"
    r")",
    re.IGNORECASE,
)

STREAM_RE  = re.compile(r"(\.m3u8(\?|$)|/playlist\.m3u8|/master\.m3u8|manifest\.mpd)", re.IGNORECASE)
VARIANT_RE = re.compile(r"(chunklist|_x\.m3u8|_[0-9]+\.m3u8|/sub/|/level|/stream_\d+\.m3u8)", re.IGNORECASE)
TS_SEGMENT = re.compile(r"\.ts(\?|$)", re.IGNORECASE)

AD_STREAM_RE = re.compile(
    r"(/ads?/|/adserver|/preroll|/vast|/vpaid|doubleclick|imasdk|"
    r"pubads|securepubads|/ad[-_]?break|midroll|postroll)",
    re.IGNORECASE,
)


def score_stream(url):
    s = 50
    ul = url.lower()
    try:
        host = urlparse(url).netloc.lower()
        path = urlparse(url).path.lower()
    except Exception:
        return 0

    if any(h in host for h in ("strmd.st", "hockey.do", "tvply.me",
                                "akamaized", "cloudfront", "fastly",
                                "cdnstream", "streamcdn", "edge.", "live.")):
        s += 30
    if re.search(r"/secure/|/ingest/|/stream/\w{20,}|/live/", path):
        s += 15
    if re.search(r"(playlist|master|index)\.m3u8", path):
        s += 10
    if AD_STREAM_RE.search(ul):
        s -= 80
    if AD_BLOCK_RE.search(ul):
        s -= 100
    if len(path) < 10:
        s -= 20
    return s


def log(msg=""):
    print(msg, file=sys.stderr, flush=True)


# ============================================================
# ROUTE HANDLER — đã fix
# ============================================================
async def block_ads_route(route):
    try:
        req = route.request
        url = req.url

        # Cho phép top-level navigation
        try:
            frame = req.frame
            if req.resource_type == "document" and frame is not None:
                if frame == frame.page.main_frame:
                    await route.continue_()
                    return
        except Exception:
            await route.continue_()
            return

        # Block ad/tracker
        if AD_BLOCK_RE.search(url):
            try:
                await route.abort()
            except Exception:
                pass
            return

        try:
            await route.continue_()
        except Exception:
            pass

    except Exception:
        try:
            await route.continue_()
        except Exception:
            pass


async def cf_pass(page, timeout=CF_TIMEOUT):
    for _ in range(timeout):
        try:
            title = await page.title()
        except Exception:
            title = ""
        if title and title not in ("Just a moment...", ""):
            return True
        await asyncio.sleep(1)
    return False


# ---------- Tầng 1 ----------
async def get_games(page):
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
    if not await cf_pass(page):
        log("[warn] Cloudflare không clear")
    await asyncio.sleep(3)

    games = await page.evaluate("""
        Array.from(document.querySelectorAll('a.match-row[href]')).map(a => {
            const teams = Array.from(a.querySelectorAll('.match-row-team-name'))
                              .map(n => n.textContent.trim()).filter(Boolean);
            const cat   = (a.querySelector('.match-row-category') || {}).textContent || '';
            const time  = (a.querySelector('.match-time')          || {}).textContent || '';
            const live  = !!a.querySelector('.live-badge');
            return {
                title  : teams.length ? teams.join(' vs ') : (a.getAttribute('title') || ''),
                href   : a.href,
                category: cat.trim(),
                time   : time.trim(),
                live   : live,
            };
        }).filter(g => g.href && g.title && g.href.includes('/watch-'))
    """)
    seen, out = set(), []
    for g in games:
        if g["href"] in seen: continue
        seen.add(g["href"]); out.append(g)
    out.sort(key=lambda g: (not g["live"], g["time"] or ""))
    return out


# ---------- Tầng 2 ----------
async def get_stream_sites(page, game_url):
    try:
        await page.goto(game_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
    except Exception as e:
        log(f"    [err game page] {e}")
        return []

    raw = await page.evaluate("""
        Array.from(document.querySelectorAll('.stream-item[data-href]')).map(el => {
            const name    = (el.querySelector('.stream-row-site-name')     || {}).textContent || '';
            const quality = (el.querySelector('.stream-row-spec')          || {}).textContent || '';
            const tier    = (el.querySelector('.stream-tier-badge')        || {}).textContent || '';
            return {
                site   : name.trim(),
                quality: quality.trim(),
                tier   : tier.trim(),
                url    : el.getAttribute('data-href'),
            };
        }).filter(s => s.url && s.url.startsWith('http'))
    """)
    return raw[:MAX_SITES]


# ---------- Tầng 3 ----------
async def capture_from_site(browser, site_url, wait_master=WAIT_MASTER):
    context = await browser.new_context()
    # Context-level ad block
    try:
        await context.route("**/*", block_ads_route)
    except Exception as e:
        log(f"        [warn] route attach: {e}")

    captured = []
    got_master = asyncio.Event()

    async def on_response(response):
        try:
            u = response.url
        except Exception:
            return
        if not STREAM_RE.search(u):  return
        if TS_SEGMENT.search(u):     return
        if VARIANT_RE.search(u):     return
        if AD_STREAM_RE.search(u):   return
        if any(c["url"] == u for c in captured): return

        sc = score_stream(u)
        if sc < 40:
            return

        try:
            headers = await response.request.all_headers()
        except Exception:
            headers = {}

        captured.append({"url": u, "headers": headers, "score": sc})
        log(f"        ✓ [{sc}] {u[:100]}")
        got_master.set()

    page = await context.new_page()
    page.on("response", on_response)

    cookie_str = ""
    try:
        try:
            await page.goto(site_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log(f"        [nav err] {e}")

        try:
            await asyncio.wait_for(got_master.wait(), timeout=wait_master)
        except asyncio.TimeoutError:
            log(f"        [timeout] không thấy m3u8 sau {wait_master}s")

        await asyncio.sleep(2)
        try:
            cookies = await context.cookies()
        except Exception:
            cookies = []
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    finally:
        try:
            await context.close()
        except Exception:
            pass

    for c in captured:
        c["cookie"] = cookie_str

    captured.sort(key=lambda c: c["score"], reverse=True)
    return captured


# ---------- M3U ----------
def pick_headers(headers, fallback_referer):
    h = {k.lower(): v for k, v in (headers or {}).items()}
    return {
        "referer":   h.get("referer") or fallback_referer or BASE_URL,
        "origin":    h.get("origin", ""),
        "cookie":    h.get("cookie", ""),
        "user_agent": h.get("user-agent") or DEFAULT_UA,
    }


def write_playlist(entries, path=OUTPUT):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "#EXTM3U",
        "# playlist : soccersurge live soccer",
        f"# generated: {ts}",
        f"# streams  : {len(entries)}",
        "",
    ]
    for e in entries:
        title = e["title"].replace('"', "'")[:100]
        group = e.get("group", "Soccer")
        h = pick_headers(e.get("headers"), e.get("referer"))
        cookie = h["cookie"] or e.get("cookie", "")

        lines.append(f'#EXTINF:-1 tvg-name="{title}" tvg-logo="" group-title="{group}",{title}')
        lines.append(f"#EXTVLCOPT:http-referrer={h['referer']}")
        lines.append(f"#EXTVLCOPT:http-user-agent={h['user_agent']}")
        if h["origin"]: lines.append(f"#EXTVLCOPT:http-origin={h['origin']}")
        if cookie:      lines.append(f"#EXTVLCOPT:http-cookie={cookie}")

        kodi = [f"Referer={h['referer']}", f"User-Agent={h['user_agent']}"]
        if h["origin"]: kodi.append(f"Origin={h['origin']}")
        if cookie:      kodi.append(f"Cookie={cookie}")
        lines.append("#KODIPROP:inputstream.adaptive.stream_headers=" + "&".join(kodi))

        exth = [f"Referer: {h['referer']}"]
        if h["origin"]: exth.append(f"Origin: {h['origin']}")
        if cookie:      exth.append(f"Cookie: {cookie}")
        lines.append("#EXTHTTP:" + "|".join(exth))

        lines.append(e["url"])
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------- Main ----------
async def main():
    log("SoccerSurge playlist generator (v4.1)")
    log(f"OS       : {platform.system()} ({_CAMOUFOX_OS})")
    log(f"Headless : {HEADLESS}")
    log(f"Output   : {OUTPUT.resolve()}")

    prefs = {
        "network.http.referer.XOriginPolicy": 0,
        "network.http.referer.XOriginTrimmingPolicy": 0,
        "network.http.referer.trimmingPolicy": 0,
        "network.http.sendRefererHeader": 2,
        "privacy.trackingprotection.enabled": False,
        "browser.cache.disk.enable": False,
    }

    async with AsyncCamoufox(headless=HEADLESS, os=_CAMOUFOX_OS,
                             firefox_user_prefs=prefs) as browser:
        ctx = await browser.new_context()
        try:
            await ctx.route("**/*", block_ads_route)
        except Exception as e:
            log(f"[warn] ctx route attach: {e}")

        page = await ctx.new_page()

        log("\n[1/3] Loading homepage ...")
        games = await get_games(page)
        log(f"      {len(games)} game(s) found")
        for g in games[:10]:
            log(f"      [{'LIVE' if g['live'] else '    '}] {g['title']} ({g['category']})")
        if MAX_GAMES:
            games = games[:MAX_GAMES]

        entries = []
        for i, game in enumerate(games, 1):
            log(f"\n[{i}/{len(games)}] {game['title']} — {game['category']}")
            sites = await get_stream_sites(page, game["href"])
            log(f"    {len(sites)} stream site(s)")

            for j, site in enumerate(sites, 1):
                label = site["site"] or urlparse(site["url"]).netloc
                log(f"    [{j}/{len(sites)}] {label} ({site['quality']}) -> {site['url'][:80]}")
                try:
                    results = await capture_from_site(browser, site["url"])
                except Exception as e:
                    log(f"        [err] {e}")
                    results = []
                if not results:
                    log(f"        ✗ no stream")

                for k, item in enumerate(results[:MAX_STREAMS]):
                    suffix = "" if k == 0 else f" #{k+1}"
                    entries.append({
                        "title": f"{game['title']} [{label}]{suffix}",
                        "url": item["url"],
                        "headers": item["headers"],
                        "cookie": item.get("cookie", ""),
                        "referer": site["url"],
                        "group": game["category"] or "Soccer",
                    })

        seen, unique = set(), []
        for e in entries:
            if e["url"] in seen: continue
            seen.add(e["url"]); unique.append(e)
        unique.sort(key=lambda e: (e["group"].lower(), e["title"].lower()))

        write_playlist(unique)
        log(f"\n[3/3] DONE — wrote {len(unique)} stream(s) to {OUTPUT}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
