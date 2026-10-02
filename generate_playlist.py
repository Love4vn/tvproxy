#!/usr/bin/env python3
"""
SoccerSurge -> IPTV playlist generator (v15 - unified)

- Giữ nguyên: SoccerSurge (Camoufox) + verify direct/proxy + signed URL + priority + M3U giàu header
- Bổ sung: tất cả scrapers từ bộ sưu tầm (scrapers_all.py) → soccer + tennis + nhiều môn
- Output: playlist.m3u hợp nhất
"""
import asyncio
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

from camoufox.async_api import AsyncCamoufox

from scrapers_all import (
    Network, Time, log, network, run_all_scrapers, filter_tennis,
)

# ============================================================
# CẤU HÌNH
# ============================================================
BASE_URL     = "https://soccersurge.io/"
OUTPUT       = Path(os.environ.get("OUTPUT", "playlist.m3u"))

# SoccerSurge (từ bản gốc)
MAX_GAMES    = int(os.environ.get("MAX_GAMES", "0")) or None
MAX_SITES    = int(os.environ.get("MAX_SITES", "15"))
MAX_STREAMS  = int(os.environ.get("MAX_STREAMS", "5"))
CF_TIMEOUT   = int(os.environ.get("CF_TIMEOUT", "90"))
WAIT_PLAYER  = int(os.environ.get("WAIT_PLAYER", "10"))
IFRAME_DEPTH = int(os.environ.get("IFRAME_DEPTH", "3"))
VERIFY_TIME  = int(os.environ.get("VERIFY_TIME", "12"))

PROXY_URL    = os.environ.get("PROXY_URL", "https://sportsurge-proxy.love4vn.workers.dev")
VERIFY_LINKS = os.environ.get("VERIFY_LINKS", "1") == "1"

# Orchestrator
USE_SOCCERSURGE = os.environ.get("USE_SOCCERSURGE", "1") == "1"
USE_SCRAPERS    = os.environ.get("USE_SCRAPERS", "1") == "1"
ONLY_TENNIS     = os.environ.get("ONLY_TENNIS", "0") == "1"

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_CAMOUFOX_OS = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(
    platform.system(), "linux")
HEADLESS = not bool(os.environ.get("DISPLAY"))

DEFAULT_UA = Network.UA

# ============================================================
# REGEX
# ============================================================
STREAM_RE = re.compile(
    r"(\.m3u8(\?|$)|/hls/|manifest\.mpd|/chunklist|/index\.m3u|application/x-mpegurl)",
    re.IGNORECASE,
)
TS_SEGMENT = re.compile(r"\.ts(\?|$)", re.IGNORECASE)
ROUTE_RE   = re.compile(r"\.m3u8|/hls/|manifest\.mpd|/chunklist|/index\.m3u", re.IGNORECASE)

SIGNED_URL_RE = re.compile(r"[?&](sig|st|e|token|signature|expires|hash)=", re.IGNORECASE)

JUNK_IFRAME_RE = re.compile(
    r"(youtube|youtu\.be|facebook|twitter|google|doubleclick|googlesyndication"
    r"|analytics|histats|discord|telegram|whatsapp|recaptcha|cloudflare"
    r"|fonts\.googleapis|gstatic|jquery|bootstrap|banner|ad[-_]?tag|/ads?/"
    r"|chatango|amung\.us|waust\.at|kofi|ads\.htm|/ad\.html|about:blank)",
    re.IGNORECASE,
)

# ============================================================
# SKIP DOMAINS
# ============================================================
SKIP_DOMAINS = {"strmd.st"}


def is_skipped(url):
    try:
        host = urlparse(url).netloc.lower()
        return any(d in host for d in SKIP_DOMAINS)
    except Exception:
        return False


# ============================================================
# PROXY LOGIC
# ============================================================
NO_PROXY_DOMAINS = ("hockey.do",)
NEED_PROXY_DOMAINS = ("dudestream1.com", "resports.cfd")


def is_signed(url):
    return bool(SIGNED_URL_RE.search(url))


def should_proxy(url):
    host = urlparse(url).netloc.lower()
    if any(d in host for d in NO_PROXY_DOMAINS):
        return False
    if is_signed(url):
        return False
    return True


def wrap_with_proxy(url, headers=None, cookie=""):
    headers = headers or {}
    parts = [f"url={quote(url, safe='')}"]
    if headers.get("referer"):    parts.append(f"ref={quote(headers['referer'], safe='')}")
    if headers.get("origin"):     parts.append(f"origin={quote(headers['origin'], safe='')}")
    ck = cookie or headers.get("cookie") or ""
    if ck:                        parts.append(f"cookie={quote(ck, safe='')}")
    if headers.get("user-agent"): parts.append(f"ua={quote(headers['user-agent'], safe='')}")
    return f"{PROXY_URL}/?{'&'.join(parts)}"


def score_stream(url):
    ul = url.lower()
    s = 50
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
    if is_signed(url):
        s += 20
    if len(path) < 10:
        s -= 30
    return s


def format_vn_time(ts_seconds, live=False):
    if live and not ts_seconds:
        return f"LIVE | {datetime.now(VN_TZ).strftime('%d/%m/%Y')}"
    if not ts_seconds:
        return ""
    try:
        dt = datetime.fromtimestamp(int(ts_seconds), tz=timezone.utc).astimezone(VN_TZ)
        return f"{dt.strftime('%H:%M')} | {dt.strftime('%d/%m/%Y')}"
    except Exception:
        return ""


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
# TẦNG 1: HOMEPAGE (SoccerSurge)
# ============================================================
async def get_games(page):
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
    if not await cf_pass(page):
        log.warning("[warn] Cloudflare không clear — tiếp tục")
    await asyncio.sleep(3)

    games = await page.evaluate("""
        Array.from(document.querySelectorAll('a.match-row[href]')).map(a => {
            const teams = Array.from(a.querySelectorAll('.match-row-team-name'))
                              .map(n => n.textContent.trim()).filter(Boolean);
            const cat    = (a.querySelector('.match-row-category') || {}).textContent || '';
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
# TẦNG 2: STREAM SITES (SoccerSurge)
# ============================================================
async def get_stream_sites(page, game_url):
    try:
        await page.goto(game_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
    except Exception as e:
        log.warning(f"    [err game page] {str(e)[:80]}")
        return []

    sites = await page.evaluate("""
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
    # priority sort
    def prio(s):
        from scrapers_all import leagues as _  # noqa
        ll = (s.get("site") or "").lower()
        PRIORITY = {
            "streameast": 1, "tnt-usa": 2, "4ksportshd": 3, "ihdstreams": 4,
            "topsurge": 5, "firetvstick": 6, "sportsupa": 10, "tophdstreams": 11,
            "volokit2": 12, "zkotaa": 13, "tvsportslive": 99, "dudestream1": 20,
        }
        for k, p in PRIORITY.items():
            if k in ll:
                return p
        return 50
    sites.sort(key=prio)
    return sites[:MAX_SITES]


# ============================================================
# TẦNG 3: CAPTURE (SoccerSurge)
# ============================================================
async def capture_streams(browser, url, depth=IFRAME_DEPTH):
    page = await browser.new_page()
    captured = []

    async def route_handler(route):
        request = route.request
        u = request.url
        if not TS_SEGMENT.search(u):
            if is_skipped(u):
                await route.continue_()
                return
            try:
                headers = await request.all_headers()
            except Exception:
                headers = {}
            if not any(c["url"] == u for c in captured):
                sc = score_stream(u)
                if sc >= 40:
                    captured.append({"url": u, "headers": headers, "score": sc})
                    log.info(f"        ✓ [{sc}] {u[:100]}")
        await route.continue_()

    await page.route(ROUTE_RE, route_handler)

    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(WAIT_PLAYER)
        except Exception as e:
            log.warning(f"        [nav err] {str(e)[:80]}")

        if not captured and depth > 0:
            try:
                iframes = await page.evaluate("""
                    Array.from(document.querySelectorAll('iframe[src]'))
                        .map(f => f.src).filter(s => s && s.startsWith('http'))
                """)
            except Exception:
                iframes = []
            for iframe_url in iframes:
                if captured: break
                if JUNK_IFRAME_RE.search(iframe_url): continue
                log.info(f"        iframe -> {iframe_url[:80]}")
                try:
                    await page.goto(iframe_url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(WAIT_PLAYER)
                except Exception as e:
                    log.warning(f"        [iframe nav err] {str(e)[:80]}")
                if not captured and depth > 1:
                    try:
                        nested = await page.evaluate("""
                            Array.from(document.querySelectorAll('iframe[src]'))
                                .map(f => f.src).filter(s => s && s.startsWith('http'))
                        """)
                    except Exception:
                        nested = []
                    for n in nested:
                        if captured: break
                        if JUNK_IFRAME_RE.search(n): continue
                        log.info(f"        nested -> {n[:80]}")
                        try:
                            await page.goto(n, wait_until="domcontentloaded", timeout=20000)
                            await asyncio.sleep(WAIT_PLAYER)
                        except Exception as e:
                            log.warning(f"        [nested nav err] {str(e)[:80]}")

        try:
            cookies = await page.context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            for c in captured:
                c["cookie"] = cookie_str
        except Exception:
            pass
    finally:
        try: await page.close()
        except Exception: pass

    captured.sort(key=lambda c: c["score"], reverse=True)
    return captured


# ============================================================
# VERIFY
# ============================================================
async def verify_one(api_ctx, url, headers, cookie):
    req_headers = {}
    if headers.get("referer"):    req_headers["Referer"]    = headers["referer"]
    if headers.get("origin"):     req_headers["Origin"]     = headers["origin"]
    if headers.get("user-agent"): req_headers["User-Agent"] = headers["user-agent"]
    ck = cookie or headers.get("cookie")
    if ck:                        req_headers["Cookie"]     = ck

    if is_signed(url):
        candidates = [("direct", url), ("proxy", wrap_with_proxy(url, headers, cookie))]
    elif should_proxy(url):
        candidates = [("proxy", wrap_with_proxy(url, headers, cookie)), ("direct", url)]
    else:
        candidates = [("direct", url)]

    reasons = []
    for method, test_url in candidates:
        try:
            resp = await api_ctx.get(test_url, headers=req_headers, timeout=VERIFY_TIME * 1000)
            if resp.status == 200:
                text = await resp.text()
                if "#EXTM3U" in text[:2000]:
                    return True, f"OK via {method}", method
                reasons.append(f"[{method}] no #EXTM3U")
            else:
                reasons.append(f"[{method}] HTTP {resp.status}")
        except Exception as e:
            reasons.append(f"[{method}] {str(e)[:40]}")
    return False, " / ".join(reasons), None


# ============================================================
# M3U OUTPUT
# ============================================================
def _write_entries(lines, e, title, referer, ua, origin, cookie):
    lines.append(f'#EXTINF:-1 tvg-name="{title}" tvg-logo="{e.get("logo") or ""}" '
                 f'tvg-id="{e.get("tvg-id") or "Live.Event.us"}" '
                 f'group-title="{e.get("group", "Soccer")}",{title}')
    lines.append(f"#EXTVLCOPT:http-referrer={referer}")
    lines.append(f"#EXTVLCOPT:http-user-agent={ua}")
    if origin: lines.append(f"#EXTVLCOPT:http-origin={origin}")
    if cookie: lines.append(f"#EXTVLCOPT:http-cookie={cookie}")

    kodi = [f"Referer={referer}", f"User-Agent={ua}"]
    if origin: kodi.append(f"Origin={origin}")
    if cookie: kodi.append(f"Cookie={cookie}")
    lines.append("#KODIPROP:inputstream.adaptive.stream_headers=" + "&".join(kodi))

    exth = [f"Referer: {referer}"]
    if origin: exth.append(f"Origin: {origin}")
    if cookie: exth.append(f"Cookie: {cookie}")
    lines.append("#EXTHTTP:" + "|".join(exth))


def write_playlist(entries, path=OUTPUT):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "#EXTM3U",
        "# playlist : soccersurge + multi-source (verified, soccer + tennis)",
        f"# generated: {ts}",
        f"# streams  : {len(entries)}",
        "",
    ]
    for e in entries:
        title = (e["title"] or "").replace('"', "'")[:120]
        group = e.get("group", "Soccer")
        h = {k.lower(): v for k, v in (e.get("headers") or {}).items()}
        referer = h.get("referer") or e.get("referer") or BASE_URL
        origin  = h.get("origin", "")
        cookie  = e.get("cookie") or h.get("cookie", "")
        ua      = h.get("user-agent") or DEFAULT_UA

        if e.get("method") == "proxy":
            final_url = wrap_with_proxy(
                e["url"],
                {"referer": referer, "origin": origin, "user-agent": ua},
                cookie,
            )
        else:
            final_url = e["url"]

        _write_entries(lines, e, title, referer, ua, origin, cookie)
        lines.append(final_url)
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# SoccerSurge pipeline -> list entries
# ============================================================
async def soccersurge_pipeline(browser) -> list[dict]:
    page = await browser.new_page()
    api_ctx = page.context.request

    entries: list[dict] = []
    log.info(f"\n[SS] Loading homepage {BASE_URL}")
    games = await get_games(page)
    log.info(f"      {len(games)} game(s) found")
    for g in games[:10]:
        tstr = format_vn_time(g.get("ts"), g["live"])
        log.info(f"      [{'LIVE' if g['live'] else '    '}] {g['title']} | {tstr}")
    if MAX_GAMES:
        games = games[:MAX_GAMES]

    for i, game in enumerate(games, 1):
        if ONLY_TENNIS and not re.search(r"tennis|atp|wta", game["title"], re.I):
            continue
        time_str = format_vn_time(game.get("ts"), game["live"])
        log.info(f"\n[SS {i}/{len(games)}] {game['title']} | {time_str}")

        sites = await get_stream_sites(page, game["href"])
        log.info(f"    {len(sites)} stream site(s)")

        if not sites:
            continue

        for j, site in enumerate(sites, 1):
            label = site["site"] or site["url"][:30]
            log.info(f"    [{j}/{len(sites)}] {label} ({site['quality']}) -> {site['url'][:70]}")

            try:
                results = await capture_streams(browser, site["url"])
            except Exception as e:
                log.warning(f"        [err] {str(e)[:80]}")
                results = []

            if not results:
                log.info(f"        ✗ no stream")

            for k, item in enumerate(results[:MAX_STREAMS]):
                if VERIFY_LINKS:
                    ok, reason, method = await verify_one(
                        api_ctx, item["url"], item["headers"], item.get("cookie", "")
                    )
                    mark = "✅" if ok else "❌"
                    log.info(f"        {mark} verify: {reason}")
                    if not ok:
                        continue
                else:
                    method = "proxy" if should_proxy(item["url"]) else "direct"

                suffix = "" if k == 0 else f" #{k+1}"
                entries.append({
                    "title":   f"{game['title']} | {time_str} [{label}]{suffix}",
                    "url":     item["url"],
                    "headers": item["headers"],
                    "cookie":  item.get("cookie", ""),
                    "referer": site["url"],
                    "group":   game.get("category") or "Soccer",
                    "method":  method,
                })

    await page.close()
    return entries


# ============================================================
# MAIN
# ============================================================
async def main():
    log.info("=== SoccerSurge Playlist Generator v15 (unified) ===")
    log.info(f"OS           : {platform.system()} ({_CAMOUFOX_OS})")
    log.info(f"Headless     : {HEADLESS}")
    log.info(f"Proxy        : {PROXY_URL}")
    log.info(f"Verify       : {VERIFY_LINKS}")
    log.info(f"Use SS       : {USE_SOCCERSURGE}")
    log.info(f"Use scrapers : {USE_SCRAPERS}")
    log.info(f"Only tennis  : {ONLY_TENNIS}")
    log.info(f"Output       : {OUTPUT.resolve()}")

    entries: list[dict] = []

    async with AsyncCamoufox(headless=HEADLESS, os=_CAMOUFOX_OS) as browser:
        # 1) SoccerSurge
        if USE_SOCCERSURGE:
            try:
                ss = await soccersurge_pipeline(browser)
                entries.extend(ss)
            except Exception as e:
                log.error(f"[SS] failed: {e}")

        # 2) Scrapers (nhận browser cho playwright scrapers)
        if USE_SCRAPERS:
            log.info("\n[SCRAPERS] running all scrapers...")
            all_ev = await run_all_scrapers(browser=browser)
            log.info(f"[SCRAPERS] total {len(all_ev)} raw events")
            # ── Import SportFilter
            from scrapers_all import SportFilter

            # Parse key: "[SPORT] NAME (TAG)"
            KEY_RE = re.compile(r"^\[(.*?)\]\s+(.*?)\s+\((\w+)\)$")

            # Verify + normalize
            page = await browser.new_page()
            api_ctx = page.context.request
            filtered = 0
            for key, ev in all_ev.items():
                m = KEY_RE.match(key)
                if not m:
                    continue
                sport, name, tag = m.group(1).strip(), m.group(2).strip(), m.group(3)

                # Lọc môn
                if not SportFilter.is_allowed(sport, name):
                    filtered += 1
                    continue

                src = ev.get("source")
                if not src:
                    continue

                ref = ev.get("refer") or BASE_URL
                event_ts = ev.get("event_ts")
                time_str = format_vn_time(int(event_ts) if event_ts else 0)

                # Format title TRƯỚC khi verify để log và M3U luôn khớp
                if time_str:
                    title = f"{name} | {time_str} [{tag}]"
                else:
                    title = f"{name} [{tag}]"

                if VERIFY_LINKS:
                    ok, reason, method = await verify_one(
                        api_ctx, src, {"referer": ref, "user-agent": DEFAULT_UA}, ""
                    )
                    if not ok:
                        log.info(f"  ❌ {title[:70]} → {reason}")
                    continue
                        log.info(f"  ✅ {title[:70]}")
                else:
                    method = "proxy" if should_proxy(src) else "direct"

                entries.append({
                    "title":   title,
                    "url":     src,
                    "headers": {"referer": ref, "user-agent": DEFAULT_UA},
                    "cookie":  "",
                    "referer": ref,
                    "group":   sport,
                    "method":  method,
                    "logo":    ev.get("logo"),
                    "tvg-id":  ev.get("tvg-id"),
                })
            log.info(f"[SCRAPERS] filtered out {filtered} non-soccer/tennis events")
            await page.close()

    # Dedupe by URL
    seen, unique = set(), []
    for e in entries:
        u = e.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        unique.append(e)

    write_playlist(unique)
    log.info(f"\n[4/4] DONE")
    log.info(f"      📄 Total in m3u : {len(unique)}")
    log.info(f"      Output          : {OUTPUT}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
