#!/usr/bin/env python3
"""
SoccerSurge -> IPTV playlist generator (v9)

Chiến lược quay lại v2/v3:
- Bóc iframe URL từ DOM, navigate MAIN PAGE vào iframe URL.
  (Bypass bug Camoufox: cross-origin iframe kẹt about:blank)
- Ad-block dùng context.route(REGEX, handler) — chỉ URL ad mới intercept.
  KHÔNG dùng "**/*" (gây treo request).
- Đệ quy iframe depth 2.
- Verify dùng APIRequestContext.
"""

import asyncio
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, quote
from zoneinfo import ZoneInfo

from camoufox.async_api import AsyncCamoufox

# ============================================================
# CẤU HÌNH
# ============================================================
BASE_URL    = "https://soccersurge.io/"
OUTPUT      = Path(os.environ.get("OUTPUT", "playlist.m3u"))
MAX_GAMES   = int(os.environ.get("MAX_GAMES", "0")) or None
MAX_SITES   = int(os.environ.get("MAX_SITES", "8"))
MAX_STREAMS = int(os.environ.get("MAX_STREAMS", "3"))
CF_TIMEOUT  = int(os.environ.get("CF_TIMEOUT", "90"))

# Thời gian chờ mỗi page/iframe
WAIT_PAGE   = int(os.environ.get("WAIT_PAGE", "10"))    # sau khi goto
WAIT_PLAYER = int(os.environ.get("WAIT_PLAYER", "15"))  # đợi player init
IFRAME_DEPTH= int(os.environ.get("IFRAME_DEPTH", "2"))
VERIFY_TIME = int(os.environ.get("VERIFY_TIME", "15"))

PROXY_URL    = os.environ.get("PROXY_URL", "https://sportsurge-proxy.love4vn.workers.dev")
VERIFY_LINKS = os.environ.get("VERIFY_LINKS", "1") == "1"
DEBUG_FRAMES = os.environ.get("DEBUG_FRAMES", "0") == "1"
DEBUG_ALLREQ = os.environ.get("DEBUG_ALLREQ", "0") == "1"

SKIP_SITES = {"tvsportslive.fr", "shd247.world"}

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

_CAMOUFOX_OS = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"} \
    .get(platform.system(), "linux")
HEADLESS = not bool(os.environ.get("DISPLAY"))

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def log(msg=""):
    print(msg, file=sys.stderr, flush=True)


# ============================================================
# DOMAIN RULES
# ============================================================
NO_PROXY_DOMAINS   = ("hockey.do",)
NEED_PROXY_DOMAINS = (
    "strmd.st", "dudestream1.com", "resports.cfd",
    "tophdstreams.com", "paini.cfd", "tawar.cfd", "odyssney.cfd",
    "embed.st", "sportspatrika.com", "edgestream",
)


def should_proxy(url):
    host = urlparse(url).netloc.lower()
    if any(d in host for d in NO_PROXY_DOMAINS):   return False
    if any(d in host for d in NEED_PROXY_DOMAINS): return True
    return True


def wrap_with_proxy(url, headers=None, cookie=""):
    headers = headers or {}
    parts = [f"url={quote(url, safe='')}"]
    if headers.get("referer"):
        parts.append(f"ref={quote(headers['referer'], safe='')}")
    if headers.get("origin"):
        parts.append(f"origin={quote(headers['origin'], safe='')}")
    ck = cookie or headers.get("cookie") or ""
    if ck:
        parts.append(f"cookie={quote(ck, safe='')}")
    if headers.get("user-agent"):
        parts.append(f"ua={quote(headers['user-agent'], safe='')}")
    return f"{PROXY_URL}/?{'&'.join(parts)}"


# ============================================================
# AD PATTERN — dùng cho route (chỉ intercept URL này)
# ============================================================
AD_URL_PATTERN = re.compile(
    r"^https?://([^/]*\.)?("
    r"doubleclick\.net|googlesyndication\.com|googleadservices\.com|"
    r"googletagmanager\.com|google-analytics\.com|adservice\.google\.com|"
    r"adnxs\.com|adsrvr\.org|taboola\.com|outbrain\.com|criteo\.com|"
    r"pubmatic\.com|rubiconproject\.com|openx\.net|smartadserver\.com|"
    r"adform\.net|casalemedia\.com|sharethrough\.com|yieldmo\.com|"
    r"highperformanceformat\.com|effectivecpmnetwork\.com|"
    r"violentlinedexploit\.com|recollectsideway\.com|"
    r"nudgebelonged\.com|reliedhounder\.com|lauansaltire\.com|"
    r"driverhugoverblown\.com|pschenttidier\.com|acscdn\.com|"
    r"jnbhi\.com|jads\.co|exoclick\.com|exosrv\.com|trafficjunky\.com|"
    r"popcash\.net|popads\.net|propellerads\.com|onclickads\.net|"
    r"mgid\.com|histats\.com|amung\.us|waust\.at|livelog\.site|"
    r"cloudflareinsights\.com|steast\.io"
    r")",
    re.IGNORECASE,
)

# Regex cho stream URL & iframe junk
STREAM_RE = re.compile(
    r"(\.m3u8(\?|$)|/playlist\.m3u8|/master\.m3u8|manifest\.mpd)",
    re.IGNORECASE,
)
VARIANT_RE = re.compile(
    r"(chunklist|_x\.m3u8|_[0-9]+\.m3u8|/sub/|/level|/stream_\d+\.m3u8)",
    re.IGNORECASE,
)
TS_SEGMENT = re.compile(r"\.ts(\?|$)", re.IGNORECASE)
AD_STREAM_RE = re.compile(
    r"(/ads?/|/adserver|/preroll|/vast|/vpaid|doubleclick|imasdk|"
    r"pubads|securepubads|/ad[-_]?break|midroll|postroll)",
    re.IGNORECASE,
)

# Iframe quảng cáo — bỏ qua khi bóc iframe URL
JUNK_IFRAME_RE = re.compile(
    r"(youtube|youtu\.be|facebook|twitter|google|doubleclick|googlesyndication"
    r"|analytics|histats|discord|telegram|whatsapp|recaptcha|cloudflare"
    r"|fonts\.googleapis|gstatic|jquery|bootstrap|banner|ad[-_]?tag|/ads?/"
    r"|chatango|amung\.us|waust\.at|effectivecpmnetwork|highperformanceformat"
    r"|violentlinedexploit|jnbhi\.com|recollectsideway|kofi|"
    r"ads\.htm|/ad\.html|about:blank)",
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
    if any(h in host for h in ("strmd.st", "hockey.do", "edgestream",
                                "akamaized", "cloudfront", "fastly", "live.")):
        s += 30
    if re.search(r"/secure/|/ingest/|/stream/\w{20,}|/live/", path):
        s += 15
    if re.search(r"(playlist|master|index)\.m3u8", path):
        s += 10
    if AD_STREAM_RE.search(ul): s -= 80
    if AD_URL_PATTERN.search(ul): s -= 100
    if len(path) < 10: s -= 20
    if "hockey.do" in host and "sig=" in url: s += 50
    return s


def format_vn_time(ts_seconds, live=False):
    if live and not ts_seconds:
        now = datetime.now(VN_TZ)
        return f"LIVE | {now.strftime('%d/%m/%Y')}"
    if not ts_seconds:
        return ""
    try:
        dt = datetime.fromtimestamp(int(ts_seconds), tz=timezone.utc).astimezone(VN_TZ)
        return f"{dt.strftime('%H:%M')} | {dt.strftime('%d/%m/%Y')}"
    except Exception:
        return ""


# ============================================================
# AD ROUTE HANDLER (chỉ URL ad mới gọi)
# ============================================================
async def ad_route_handler(route):
    try:
        await route.abort()
    except Exception:
        try:    await route.continue_()
        except: pass


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


# ============================================================
# TẦNG 1 — HOMEPAGE
# ============================================================
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
            const timeEl = a.querySelector('.match-time');
            const ts     = timeEl ? timeEl.getAttribute('data-timestamp') : null;
            const live   = !!a.querySelector('.live-badge');
            return {
                title   : teams.length ? teams.join(' vs ') : (a.getAttribute('title') || ''),
                href    : a.href,
                category: cat.trim(),
                ts      : ts,
                live    : live,
            };
        }).filter(g => g.href && g.title && g.href.includes('/watch-'))
    """)
    seen, out = set(), []
    for g in games:
        if g["href"] in seen: continue
        seen.add(g["href"]); out.append(g)
    out.sort(key=lambda g: (not g["live"], g.get("ts") or ""))
    return out


# ============================================================
# TẦNG 2 — STREAM SITES
# ============================================================
async def get_stream_sites(page, game_url):
    try:
        await page.goto(game_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
    except Exception as e:
        log(f"    [err game page] {str(e)[:80]}")
        return []

    raw = await page.evaluate("""
        Array.from(document.querySelectorAll('.stream-item[data-href]')).map(el => {
            const name    = (el.querySelector('.stream-row-site-name') || {}).textContent || '';
            const quality = (el.querySelector('.stream-row-spec')      || {}).textContent || '';
            return {
                site   : name.trim(),
                quality: quality.trim(),
                url    : el.getAttribute('data-href'),
            };
        }).filter(s => s.url && s.url.startsWith('http'))
    """)
    return [s for s in raw if not any(sk in s["url"] for sk in SKIP_SITES)][:MAX_SITES]


# ============================================================
# TẦNG 3 — CAPTURE với IFRAME WALKING
# ============================================================
async def capture_from_site(browser, site_url):
    """
    Load site_url, bóc iframe URL, navigate main page vào từng iframe URL.
    Capture m3u8 bằng page.on("response"). Đệ quy depth 2.
    """
    context = await browser.new_context()

    # CHỈ intercept URL khớp AD_URL_PATTERN — không dùng "**/*"
    try:
        await context.route(AD_URL_PATTERN, ad_route_handler)
    except Exception as e:
        log(f"        [warn] route: {e}")

    captured = []

    page = await context.new_page()

    async def on_response(response):
        try:
            u = response.url
        except Exception:
            return
        if DEBUG_ALLREQ:
            log(f"        [req] {u[:110]}")
        if not STREAM_RE.search(u):  return
        if TS_SEGMENT.search(u):     return
        if VARIANT_RE.search(u):     return
        if AD_STREAM_RE.search(u):   return
        if any(c["url"] == u for c in captured): return
        sc = score_stream(u)
        if sc < 40: return
        try:
            headers = await response.request.all_headers()
        except Exception:
            headers = {}
        captured.append({"url": u, "headers": headers, "score": sc})
        log(f"        ✓ [{sc}] {u[:110]}")

    page.on("response", on_response)

    async def walk(url, depth):
        if depth > IFRAME_DEPTH: return
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            log(f"        [nav err depth={depth}] {str(e)[:80]}")
            # vẫn tiếp tục đợi, có thể trang đang load chậm
        await asyncio.sleep(WAIT_PAGE if depth == 0 else WAIT_PLAYER)

        if DEBUG_FRAMES:
            try:
                frames = page.frames
                log(f"        [debug] depth={depth} {len(frames)} frames")
                for f in frames:
                    try: log(f"        [frame] {f.url[:100]}")
                    except: pass
            except: pass

        if captured: return

        # Bóc iframe URL từ DOM
        try:
            iframes = await page.evaluate("""
                Array.from(document.querySelectorAll('iframe[src]'))
                    .map(f => f.src)
                    .filter(s => s && s.startsWith('http'))
            """)
        except Exception:
            iframes = []

        for iframe_url in iframes:
            if captured: break
            if JUNK_IFRAME_RE.search(iframe_url): continue
            log(f"        iframe -> {iframe_url[:90]}")
            await walk(iframe_url, depth + 1)

    try:
        await walk(site_url, 0)
    except Exception as e:
        log(f"        [err walk] {str(e)[:80]}")

    # Lấy cookie
    cookie_str = ""
    try:
        cookies = await context.cookies()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    except Exception:
        pass

    try:
        await context.close()
    except Exception:
        pass

    for c in captured:
        c["cookie"] = cookie_str
    captured.sort(key=lambda c: c["score"], reverse=True)
    return captured


# ============================================================
# VERIFY
# ============================================================
async def verify_one(api_ctx, url, headers, cookie):
    try:
        req_headers = {}
        if headers.get("user-agent"): req_headers["User-Agent"] = headers["user-agent"]
        if headers.get("referer"):    req_headers["Referer"]    = headers["referer"]
        if headers.get("origin"):     req_headers["Origin"]     = headers["origin"]
        ck = cookie or headers.get("cookie")
        if ck:                        req_headers["Cookie"]     = ck

        test_url = wrap_with_proxy(url, headers, cookie) if should_proxy(url) else url
        resp = await api_ctx.get(test_url, headers=req_headers, timeout=VERIFY_TIME * 1000)
        if resp.status != 200:
            return False, f"HTTP {resp.status}"
        text = await resp.text()
        if "#EXTM3U" in text[:2000]:
            return True, "OK"
        return False, "no #EXTM3U"
    except Exception as e:
        return False, str(e)[:80]


# ============================================================
# M3U
# ============================================================
def pick_headers(headers, fallback_referer):
    h = {k.lower(): v for k, v in (headers or {}).items()}
    return {
        "referer":    h.get("referer") or fallback_referer or BASE_URL,
        "origin":     h.get("origin", ""),
        "cookie":     h.get("cookie", ""),
        "user_agent": h.get("user-agent") or DEFAULT_UA,
    }


def write_playlist(entries, path=OUTPUT):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "#EXTM3U",
        "# playlist : soccersurge live soccer (verified)",
        f"# generated: {ts}",
        f"# streams  : {len(entries)}",
        "",
    ]
    for e in entries:
        title = e["title"].replace('"', "'")[:120]
        group = e.get("group", "Soccer")
        h = pick_headers(e.get("headers"), e.get("referer"))
        cookie = h["cookie"] or e.get("cookie", "")
        final_url = wrap_with_proxy(e["url"], h, cookie) if should_proxy(e["url"]) else e["url"]

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

        lines.append(final_url)
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# MAIN
# ============================================================
async def main():
    log("SoccerSurge playlist generator (v9)")
    log(f"OS       : {platform.system()} ({_CAMOUFOX_OS})")
    log(f"Headless : {HEADLESS}")
    log(f"Proxy    : {PROXY_URL}")
    log(f"Verify   : {VERIFY_LINKS}")
    log(f"Wait     : page={WAIT_PAGE}s player={WAIT_PLAYER}s depth={IFRAME_DEPTH}")
    log(f"Debug    : frames={DEBUG_FRAMES} allreq={DEBUG_ALLREQ}")
    log(f"Output   : {OUTPUT.resolve()}")

    # Prefs đơn giản — KHÔNG dùng fission.autostart (gây bug iframe)
    prefs = {
        "network.http.referer.XOriginPolicy": 0,
        "network.http.referer.XOriginTrimmingPolicy": 0,
        "network.http.referer.trimmingPolicy": 0,
        "network.http.sendRefererHeader": 2,
        "privacy.trackingprotection.enabled": False,
    }

    async with AsyncCamoufox(headless=HEADLESS, os=_CAMOUFOX_OS,
                             firefox_user_prefs=prefs) as browser:
        nav_ctx = await browser.new_context()
        try:
            await nav_ctx.route(AD_URL_PATTERN, ad_route_handler)
        except Exception as e:
            log(f"[warn] nav route: {e}")
        nav_page = await nav_ctx.new_page()

        api_ctx = nav_ctx.request

        log("\n[1/4] Loading homepage ...")
        games = await get_games(nav_page)
        log(f"      {len(games)} game(s) found")
        for g in games[:10]:
            tstr = format_vn_time(g.get("ts"), g["live"])
            log(f"      [{'LIVE' if g['live'] else '    '}] {g['title']} | {tstr}")
        if MAX_GAMES: games = games[:MAX_GAMES]

        entries = []
        ok_cnt = fail_cnt = 0

        for i, game in enumerate(games, 1):
            time_str = format_vn_time(game.get("ts"), game["live"])
            log(f"\n[{i}/{len(games)}] {game['title']} | {time_str}")

            sites = await get_stream_sites(nav_page, game["href"])
            log(f"    {len(sites)} stream site(s)")

            for j, site in enumerate(sites, 1):
                label = site["site"] or urlparse(site["url"]).netloc
                log(f"    [{j}/{len(sites)}] {label} ({site['quality']}) -> {site['url'][:80]}")

                try:
                    results = await capture_from_site(browser, site["url"])
                except Exception as e:
                    log(f"        [err] {str(e)[:80]}")
                    results = []

                if not results:
                    log(f"        ✗ no stream")

                for k, item in enumerate(results[:MAX_STREAMS]):
                    if VERIFY_LINKS:
                        ok, reason = await verify_one(
                            api_ctx, item["url"], item["headers"], item.get("cookie", "")
                        )
                        mark = "✅" if ok else "❌"
                        log(f"        {mark} verify: {reason}")
                        if not ok:
                            fail_cnt += 1
                            continue
                    ok_cnt += 1
                    suffix = "" if k == 0 else f" #{k+1}"
                    title = f"{game['title']} | {time_str} [{label}]{suffix}"
                    entries.append({
                        "title":   title,
                        "url":     item["url"],
                        "headers": item["headers"],
                        "cookie":  item.get("cookie", ""),
                        "referer": site["url"],
                        "group":   game["category"] or "Soccer",
                    })

        seen, unique = set(), []
        for e in entries:
            if e["url"] in seen: continue
            seen.add(e["url"]); unique.append(e)

        write_playlist(unique)
        log(f"\n[4/4] DONE")
        log(f"      ✅ verified OK : {ok_cnt}")
        log(f"      ❌ verify fail : {fail_cnt}")
        log(f"      Total in m3u   : {len(unique)}")
        log(f"      Output         : {OUTPUT}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
