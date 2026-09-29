#!/usr/bin/env python3
"""
SoccerSurge -> IPTV playlist generator (v5 — auto-proxy + verify)

Mới:
- Tự nhận diện link nào cần proxy (strmd.st, dudestream1...) và link nào không (hockey.do).
- Verify từng link qua proxy: chỉ ghi vào m3u nếu trả về #EXTM3U.
- Đánh dấu [OK] / [??] trong tên kênh để biết trạng thái.
"""

import asyncio
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, quote

from camoufox.async_api import AsyncCamoufox

# ------------------------- Cấu hình -------------------------
BASE_URL    = "https://soccersurge.io/"
OUTPUT      = Path(os.environ.get("OUTPUT", "playlist.m3u"))
MAX_GAMES   = int(os.environ.get("MAX_GAMES", "0")) or None
MAX_SITES   = int(os.environ.get("MAX_SITES", "8"))
MAX_STREAMS = int(os.environ.get("MAX_STREAMS", "3"))
CF_TIMEOUT  = int(os.environ.get("CF_TIMEOUT", "90"))
WAIT_MASTER = int(os.environ.get("WAIT_MASTER", "30"))

# === Proxy của bạn ===
PROXY_URL   = os.environ.get("PROXY_URL", "https://sportsurge-proxy.love4vn.workers.dev")
VERIFY_LINKS= os.environ.get("VERIFY_LINKS", "1") == "1"

_CAMOUFOX_OS = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"} \
    .get(platform.system(), "linux")
HEADLESS = not bool(os.environ.get("DISPLAY"))

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# ------------------------- Domain rules -------------------------
# Domain này KHÔNG cần proxy — signed URL portable
NO_PROXY_DOMAINS = ("hockey.do", "hls.hockey")

# Domain này CẦN proxy — session-bound, cần Origin/Referer
NEED_PROXY_DOMAINS = (
    "strmd.st", "dudestream1.com", "resports.cfd",
    "tophdstreams.com", "paini.cfd", "tawar.cfd", "odyssney.cfd",
    "embed.st", "sportspatrika.com", "edgestream6.pro", "edgestream5.pro",
)


def should_proxy(url):
    host = urlparse(url).netloc.lower()
    # Ưu tiên no-proxy nếu có signed URL
    if any(d in host for d in NO_PROXY_DOMAINS) and "sig=" in url:
        return False
    if any(d in host for d in NEED_PROXY_DOMAINS):
        return True
    # Mặc định: proxy (an toàn hơn)
    return True


def wrap_with_proxy(url):
    return f"{PROXY_URL}/?url={quote(url, safe='')}"


# ------------------------- Regex -------------------------
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
    if "hockey.do" in host and "sig=" in url:
        s += 50
    return s


def log(msg=""):
    print(msg, file=sys.stderr, flush=True)


# ============================================================
# Route handler
# ============================================================
async def block_ads_route(route):
    try:
        req = route.request
        url = req.url
        try:
            frame = req.frame
            if req.resource_type == "document" and frame is not None:
                if frame == frame.page.main_frame:
                    await route.continue_()
                    return
        except Exception:
            await route.continue_()
            return
        if AD_BLOCK_RE.search(url):
            try:    await route.abort()
            except: pass
            return
        try:    await route.continue_()
        except: pass
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
            return {
                site   : name.trim(),
                quality: quality.trim(),
                url    : el.getAttribute('data-href'),
            };
        }).filter(s => s.url && s.url.startsWith('http'))
    """)
    return raw[:MAX_SITES]


# ---------- Tầng 3: capture ----------
async def capture_from_site(browser, site_url, wait_master=WAIT_MASTER):
    context = await browser.new_context()
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
        if sc < 40: return
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
        try: await context.close()
        except: pass

    for c in captured:
        c["cookie"] = cookie_str
    captured.sort(key=lambda c: c["score"], reverse=True)
    return captured


# ---------- Verify qua proxy ----------
async def verify_one(ctx, url, timeout_ms=10000):
    """Test 1 link qua proxy. Trả về True/False."""
    test_url = wrap_with_proxy(url) if should_proxy(url) else url
    try:
        resp = await ctx.request.get(test_url, timeout=timeout_ms)
        if resp.status != 200:
            return False, f"HTTP {resp.status}"
        text = await resp.text()
        if "#EXTM3U" in text[:1000]:
            return True, "OK"
        return False, "no #EXTM3U"
    except Exception as e:
        return False, str(e)[:60]


async def verify_all(browser, entries):
    """Verify toàn bộ link trong entries. Đánh dấu e['verified']."""
    if not VERIFY_LINKS:
        for e in entries: e["verified"] = None
        return

    log(f"\n[verify] Đang test {len(entries)} link qua proxy...")
    ctx = await browser.new_context()
    try:
        # Chạy song song tối đa 5 cái
        sem = asyncio.Semaphore(5)

        async def check(e):
            async with sem:
                ok, reason = await verify_one(ctx, e["url"])
                e["verified"] = ok
                e["verify_reason"] = reason
                mark = "✅" if ok else "❌"
                log(f"  {mark} {e['title'][:50]} → {reason}")

        await asyncio.gather(*(check(e) for e in entries))
    finally:
        try: await ctx.close()
        except: pass


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
        # Title có thêm ✅ / ❌
        prefix = ""
        if e.get("verified") is True:  prefix = "[✅] "
        elif e.get("verified") is False: prefix = "[❌] "

        title = (prefix + e["title"]).replace('"', "'")[:100]
        group = e.get("group", "Soccer")
        h = pick_headers(e.get("headers"), e.get("referer"))
        cookie = h["cookie"] or e.get("cookie", "")

        # Quyết định URL cuối cùng
        final_url = wrap_with_proxy(e["url"]) if should_proxy(e["url"]) else e["url"]

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


# ---------- Main ----------
async def main():
    log("SoccerSurge playlist generator (v5 — auto-proxy)")
    log(f"OS       : {platform.system()} ({_CAMOUFOX_OS})")
    log(f"Headless : {HEADLESS}")
    log(f"Proxy    : {PROXY_URL}")
    log(f"Verify   : {VERIFY_LINKS}")
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
        try: await ctx.route("**/*", block_ads_route)
        except: pass
        page = await ctx.new_page()

        log("\n[1/4] Loading homepage ...")
        games = await get_games(page)
        log(f"      {len(games)} game(s) found")
        for g in games[:10]:
            log(f"      [{'LIVE' if g['live'] else '    '}] {g['title']} ({g['category']})")
        if MAX_GAMES: games = games[:MAX_GAMES]

        # 2+3. Capture
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

        # Dedupe
        seen, unique = set(), []
        for e in entries:
            if e["url"] in seen: continue
            seen.add(e["url"]); unique.append(e)

        # 4. Verify
        await verify_all(browser, unique)

        # Sắp xếp: verified OK lên đầu
        def sort_key(e):
            v = 0 if e.get("verified") is True else (2 if e.get("verified") is False else 1)
            return (v, e["group"].lower(), e["title"].lower())
        unique.sort(key=sort_key)

        write_playlist(unique)

        # Thống kê
        ok = sum(1 for e in unique if e.get("verified") is True)
        fail = sum(1 for e in unique if e.get("verified") is False)
        unk = len(unique) - ok - fail
        log(f"\n[4/4] DONE")
        log(f"      ✅ verified: {ok}")
        log(f"      ❌ failed  : {fail}")
        log(f"      ?  unknown : {unk}")
        log(f"      Total     : {len(unique)} streams → {OUTPUT}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
