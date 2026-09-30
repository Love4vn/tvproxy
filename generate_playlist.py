#!/usr/bin/env python3
"""
SoccerSurge -> IPTV playlist generator (v13+14)

Base: v12 (working — KHÔNG ad-block, KHÔNG config đặc biệt)
v13: Bỏ hoàn toàn strmd.st (IP-locked, không play từ ngoài được)
v14: Ưu tiên site có tỉ lệ thành công cao (Streameast, Tnt-usa, ...)
+ Verify thử cả direct lẫn proxy, log rõ
+ Signed URL (?sig/?st/?e) → KHÔNG proxy
+ Title format: Teams | HH:MM | DD/MM/YYYY [Site]
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
BASE_URL     = "https://soccersurge.io/"
OUTPUT       = Path(os.environ.get("OUTPUT", "playlist.m3u"))
MAX_GAMES    = int(os.environ.get("MAX_GAMES", "0")) or None
MAX_SITES    = int(os.environ.get("MAX_SITES", "10"))     # 5 site tốt nhất (priority)
MAX_STREAMS  = int(os.environ.get("MAX_STREAMS", "5"))
CF_TIMEOUT   = int(os.environ.get("CF_TIMEOUT", "90"))
WAIT_PLAYER  = int(os.environ.get("WAIT_PLAYER", "10"))
IFRAME_DEPTH = int(os.environ.get("IFRAME_DEPTH", "2"))
VERIFY_TIME  = int(os.environ.get("VERIFY_TIME", "12"))

PROXY_URL    = os.environ.get("PROXY_URL", "https://sportsurge-proxy.love4vn.workers.dev")
VERIFY_LINKS = os.environ.get("VERIFY_LINKS", "1") == "1"

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_CAMOUFOX_OS = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"} \
    .get(platform.system(), "linux")
HEADLESS = not bool(os.environ.get("DISPLAY"))

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ============================================================
# REGEX
# ============================================================
STREAM_RE = re.compile(
    r"(\.m3u8(\?|$)|/hls/|manifest\.mpd|/chunklist|/index\.m3u|application/x-mpegurl)",
    re.IGNORECASE,
)
TS_SEGMENT = re.compile(r"\.ts(\?|$)", re.IGNORECASE)
ROUTE_RE   = re.compile(r"\.m3u8|/hls/|manifest\.mpd|/chunklist|/index\.m3u", re.IGNORECASE)

# URL có chữ ký → portable, không cần proxy
SIGNED_URL_RE = re.compile(r"[?&](sig|st|e|token|signature|expires|hash)=", re.IGNORECASE)

JUNK_IFRAME_RE = re.compile(
    r"(youtube|youtu\.be|facebook|twitter|google|doubleclick|googlesyndication"
    r"|analytics|histats|discord|telegram|whatsapp|recaptcha|cloudflare"
    r"|fonts\.googleapis|gstatic|jquery|bootstrap|banner|ad[-_]?tag|/ads?/"
    r"|chatango|amung\.us|waust\.at|kofi|ads\.htm|/ad\.html|about:blank)",
    re.IGNORECASE,
)

# ============================================================
# v13: SKIP DOMAINS — không capture, không proxy
# ============================================================
SKIP_DOMAINS = {"strmd.st"}    # IP-locked, không play từ ngoài


def is_skipped(url):
    try:
        host = urlparse(url).netloc.lower()
        return any(d in host for d in SKIP_DOMAINS)
    except Exception:
        return False


# ============================================================
# v14: PRIORITY SITES
# ============================================================
# Site có tỉ lệ thành công cao → ưu tiên chạy trước
PRIORITY_SITES = {
    "streameast":   1,    # edgestream*.pro  → 100% OK
    "tnt-usa":      2,    # edgestream*.pro  → 100% OK
    "4ksportshd":   3,    # edgestream*.pro  → 100% OK
    "ihdstreams":   4,    # edgestream*.pro  → 100% OK
    "topsurge":     5,    # hls.hockey.do    → 100% OK
    "firetvstick":  6,    # có thể ra link OK
    "sportsupa":   10,    # thường ra strmd.st (đã skip)
    "tophdstreams":11,    # thường ra strmd.st (đã skip)
    "volokit2":    12,    # thường ra strmd.st (đã skip)
    "zkotaa":      13,    # thường ra strmd.st (đã skip)
    "tvsportslive": 99,   # luôn timeout
    "dudestream1":  20,   # hay timeout
}


def site_priority(label):
    ll = (label or "").lower()
    for k, p in PRIORITY_SITES.items():
        if k in ll:
            return p
    return 50    # unknown → trung bình


# ============================================================
# PROXY LOGIC
# ============================================================
NO_PROXY_DOMAINS = ("hockey.do",)    # signed URL, không cần proxy
# Các domain còn lại trong NEED_PROXY sẽ dùng proxy — nhưng v13 đã skip strmd.st
NEED_PROXY_DOMAINS = ("dudestream1.com", "resports.cfd")


def is_signed(url):
    return bool(SIGNED_URL_RE.search(url))


def should_proxy(url):
    """
    - Domain NO_PROXY (hockey.do)       → không proxy
    - Signed URL (?sig/?st/...)         → không proxy (portable)
    - Domain NEED_PROXY (dudestream1)   → proxy
    - Còn lại                            → proxy
    """
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
        s += 20    # signed → portable, ưu tiên cao
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


def log(msg=""):
    print(msg, file=sys.stderr, flush=True)


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
# TẦNG 1: HOMEPAGE
# ============================================================
async def get_games(page):
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
    if not await cf_pass(page):
        log("[warn] Cloudflare không clear — tiếp tục")
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
# TẦNG 2: STREAM SITES (có priority sort)
# ============================================================
async def get_stream_sites(page, game_url):
    try:
        await page.goto(game_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
    except Exception as e:
        log(f"    [err game page] {str(e)[:80]}")
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

    # v14: sort theo priority — site tốt lên đầu
    sites.sort(key=lambda s: site_priority(s.get("site", "")))
    return sites[:MAX_SITES]


# ============================================================
# TẦNG 3: CAPTURE (page.route chỉ observe, không block)
# ============================================================
async def capture_streams(browser, url, depth=IFRAME_DEPTH):
    page = await browser.new_page()
    captured = []

    async def route_handler(route):
        request = route.request
        u = request.url
        if not TS_SEGMENT.search(u):
            # v13: bỏ qua strmd.st
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
                    log(f"        ✓ [{sc}] {u[:100]}")
        await route.continue_()

    await page.route(ROUTE_RE, route_handler)

    try:
        # Tầng chính
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(WAIT_PLAYER)
        except Exception as e:
            log(f"        [nav err] {str(e)[:80]}")

        # Walk iframe
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
                log(f"        iframe -> {iframe_url[:80]}")
                try:
                    await page.goto(iframe_url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(WAIT_PLAYER)
                except Exception as e:
                    log(f"        [iframe nav err] {str(e)[:80]}")

                # Depth 2
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
                        log(f"        nested -> {n[:80]}")
                        try:
                            await page.goto(n, wait_until="domcontentloaded", timeout=20000)
                            await asyncio.sleep(WAIT_PLAYER)
                        except Exception as e:
                            log(f"        [nested nav err] {str(e)[:80]}")

        # Lấy cookie của page
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
# VERIFY: thử cả direct lẫn proxy, log rõ cả 2
# ============================================================
async def verify_one(api_ctx, url, headers, cookie):
    """
    Trả về (ok, reason, method) với method = 'direct' | 'proxy' | None.
    """
    req_headers = {}
    if headers.get("referer"):    req_headers["Referer"]    = headers["referer"]
    if headers.get("origin"):     req_headers["Origin"]     = headers["origin"]
    if headers.get("user-agent"): req_headers["User-Agent"] = headers["user-agent"]
    ck = cookie or headers.get("cookie")
    if ck:                        req_headers["Cookie"]     = ck

    # Thứ tự thử:
    #   - Signed URL       → direct trước (portable)
    #   - should_proxy     → proxy trước
    #   - Không proxy      → direct
    if is_signed(url):
        candidates = [("direct", url), ("proxy", wrap_with_proxy(url, headers, cookie))]
    elif should_proxy(url):
        candidates = [("proxy",  wrap_with_proxy(url, headers, cookie)), ("direct", url)]
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
def write_playlist(entries, path=OUTPUT):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "#EXTM3U",
        "# playlist : soccersurge live (verified, portable links only)",
        f"# generated: {ts}",
        f"# streams  : {len(entries)}",
        "",
    ]
    for e in entries:
        title = e["title"].replace('"', "'")[:120]
        group = e.get("group", "Soccer")
        h = {k.lower(): v for k, v in (e.get("headers") or {}).items()}
        referer = h.get("referer") or e.get("referer") or BASE_URL
        origin  = h.get("origin", "")
        cookie  = e.get("cookie") or h.get("cookie", "")
        ua      = h.get("user-agent") or DEFAULT_UA

        # URL cuối cùng dùng cách đã verify OK
        if e.get("method") == "proxy":
            final_url = wrap_with_proxy(
                e["url"],
                {"referer": referer, "origin": origin, "user-agent": ua},
                cookie,
            )
        else:
            final_url = e["url"]

        lines.append(f'#EXTINF:-1 tvg-name="{title}" tvg-logo="" group-title="{group}",{title}')
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

        lines.append(final_url)
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# MAIN
# ============================================================
async def main():
    log("SoccerSurge playlist generator (v13+14)")
    log(f"OS       : {platform.system()} ({_CAMOUFOX_OS})")
    log(f"Headless : {HEADLESS}")
    log(f"Proxy    : {PROXY_URL}")
    log(f"Verify   : {VERIFY_LINKS}")
    log(f"Wait     : {WAIT_PLAYER}s depth={IFRAME_DEPTH}")
    log(f"Max sites: {MAX_SITES} (priority sorted)")
    log(f"Skip     : {sorted(SKIP_DOMAINS)}")
    log(f"Output   : {OUTPUT.resolve()}")

    async with AsyncCamoufox(headless=HEADLESS, os=_CAMOUFOX_OS) as browser:
        page = await browser.new_page()
        api_ctx = page.context.request

        log("\n[1/4] Loading homepage ...")
        games = await get_games(page)
        log(f"      {len(games)} game(s) found")
        for g in games[:10]:
            tstr = format_vn_time(g.get("ts"), g["live"])
            log(f"      [{'LIVE' if g['live'] else '    '}] {g['title']} | {tstr}")
        if MAX_GAMES:
            games = games[:MAX_GAMES]

        entries = []
        ok_cnt = fail_cnt = 0
        skip_cnt = 0

        for i, game in enumerate(games, 1):
            time_str = format_vn_time(game.get("ts"), game["live"])
            log(f"\n[{i}/{len(games)}] {game['title']} | {time_str}")

            sites = await get_stream_sites(page, game["href"])
            log(f"    {len(sites)} stream site(s) (priority sorted)")

            if not sites:
                log(f"    [skip] no stream sites")
                skip_cnt += 1
                continue

            for j, site in enumerate(sites, 1):
                label = site["site"] or site["url"][:30]
                prio = site_priority(label)
                log(f"    [{j}/{len(sites)}] (p{prio}) {label} ({site['quality']}) -> {site['url'][:70]}")

                try:
                    results = await capture_streams(browser, site["url"])
                except Exception as e:
                    log(f"        [err] {str(e)[:80]}")
                    results = []

                if not results:
                    log(f"        ✗ no stream")

                for k, item in enumerate(results[:MAX_STREAMS]):
                    if VERIFY_LINKS:
                        ok, reason, method = await verify_one(
                            api_ctx, item["url"], item["headers"], item.get("cookie", "")
                        )
                        mark = "✅" if ok else "❌"
                        log(f"        {mark} verify: {reason}")
                        if not ok:
                            fail_cnt += 1
                            continue
                    else:
                        method = "proxy" if should_proxy(item["url"]) else "direct"

                    ok_cnt += 1
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

        # Dedupe theo URL
        seen, unique = set(), []
        for e in entries:
            if e["url"] in seen: continue
            seen.add(e["url"]); unique.append(e)

        write_playlist(unique)

        log(f"\n[4/4] DONE")
        log(f"      ✅ verified OK   : {ok_cnt}")
        log(f"      ❌ verify fail   : {fail_cnt}")
        log(f"      ⏭  games skipped : {skip_cnt}")
        log(f"      📄 Total in m3u  : {len(unique)}")
        log(f"      Output           : {OUTPUT}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
