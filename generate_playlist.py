#!/usr/bin/env python3
"""
SoccerSurge -> IPTV playlist generator (v2: capture real request headers).

Thay đổi chính so với v1:
- Dùng page.route() để chặn request .m3u8 và lấy TOÀN BỘ headers thật
  (Referer, Origin, Cookie, User-Agent...) mà browser gửi.
- Ghi các headers đó vào m3u qua #EXTVLCOPT + #KODIPROP.
- Mở page MỚI cho mỗi site để tránh handler chồng chéo.
"""

import asyncio
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from camoufox.async_api import AsyncCamoufox

# ------------------------- Cấu hình -------------------------
BASE_URL    = "https://soccersurge.io/"
OUTPUT      = Path(os.environ.get("OUTPUT", "playlist.m3u"))
MAX_GAMES   = int(os.environ.get("MAX_GAMES", "0")) or None
MAX_SITES   = int(os.environ.get("MAX_SITES", "8"))
MAX_STREAMS = int(os.environ.get("MAX_STREAMS", "3"))
CF_TIMEOUT  = int(os.environ.get("CF_TIMEOUT", "90"))
WAIT_PLAYER = int(os.environ.get("WAIT_PLAYER", "9"))
IFRAME_DEPTH= int(os.environ.get("IFRAME_DEPTH", "2"))

_CAMOUFOX_OS = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"} \
    .get(platform.system(), "linux")
HEADLESS = not bool(os.environ.get("DISPLAY"))

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ------------------------- Bộ lọc -------------------------
STREAM_RE = re.compile(
    r"(\.m3u8(\?|$)|/hls/|manifest\.mpd|/chunklist|/index\.m3u|application/x-mpegurl)",
    re.IGNORECASE,
)
TS_SEGMENT = re.compile(r"\.ts(\?|$)", re.IGNORECASE)

# Regex để page.route chỉ intercept những request cần thiết (nhanh hơn "**/*")
ROUTE_RE = re.compile(r"\.m3u8|/hls/|manifest\.mpd|/chunklist|/index\.m3u", re.IGNORECASE)

JUNK_IFRAME_RE = re.compile(
    r"(youtube|youtu\.be|facebook|twitter|google|doubleclick|googlesyndication"
    r"|analytics|histats|discord|telegram|whatsapp|recaptcha|cloudflare"
    r"|fonts\.googleapis|gstatic|jquery|bootstrap|banner|ad[-_]?tag|/ads?/)",
    re.IGNORECASE,
)


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


# ---------- Tầng 1: games từ homepage ----------
async def get_games(page):
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
    if not await cf_pass(page):
        log("[warn] Cloudflare không clear — tiếp tục")
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
        if g["href"] in seen:
            continue
        seen.add(g["href"])
        out.append(g)
    out.sort(key=lambda g: (not g["live"], g["time"] or ""))
    return out


# ---------- Tầng 2: stream sites từ trang trận ----------
async def get_stream_sites(page, game_url):
    try:
        await page.goto(game_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
    except Exception as e:
        log(f"    [err game page] {e}")
        return []

    sites = await page.evaluate("""
        Array.from(document.querySelectorAll('.stream-item[data-href]')).map(el => {
            const name    = (el.querySelector('.stream-row-site-name')     || {}).textContent || '';
            const channel = (el.querySelector('.stream-row-channel')       || {}).textContent || '';
            const quality = (el.querySelector('.stream-row-spec')          || {}).textContent || '';
            const tier    = (el.querySelector('.stream-tier-badge')        || {}).textContent || '';
            return {
                site   : name.trim(),
                channel: channel.trim(),
                quality: quality.trim(),
                tier   : tier.trim(),
                url    : el.getAttribute('data-href'),
            };
        }).filter(s => s.url && s.url.startsWith('http'))
    """)
    return sites[:MAX_SITES]


# ---------- Tầng 3+4: capture m3u8 + headers ----------
async def capture_streams(browser, url, depth=IFRAME_DEPTH):
    """
    Mở page mới, chặn mọi request m3u8/manifest và capture:
      - URL
      - Toàn bộ request headers browser gửi (referer, origin, cookie, UA...)
    Nếu chưa bắt được, đệ quy vào iframe (tối đa `depth` tầng).
    """
    page = await browser.new_page()
    captured = []   # list[{"url": str, "headers": dict}]

    async def route_handler(route):
        request = route.request
        u = request.url
        if not TS_SEGMENT.search(u):
            try:
                headers = await request.all_headers()
            except Exception:
                headers = {}
            if not any(c["url"] == u for c in captured):
                captured.append({"url": u, "headers": headers})
                log(f"        ✓ captured: {u[:80]}")
        await route.continue_()

    await page.route(ROUTE_RE, route_handler)

    try:
        # --- Tầng chính ---
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(WAIT_PLAYER)
        except Exception as e:
            log(f"        [nav err] {e}")

        # --- Đệ quy iframe ---
        if not captured and depth > 0:
            try:
                iframes = await page.evaluate("""
                    Array.from(document.querySelectorAll('iframe[src]'))
                        .map(f => f.src).filter(s => s && s.startsWith('http'))
                """)
            except Exception:
                iframes = []

            for iframe_url in iframes:
                if captured:
                    break
                if JUNK_IFRAME_RE.search(iframe_url):
                    continue
                log(f"        iframe -> {iframe_url[:80]}")
                try:
                    await page.goto(iframe_url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(WAIT_PLAYER)
                except Exception as e:
                    log(f"        [iframe nav err] {e}")

                # đệ quy sâu hơn nếu còn depth
                if not captured and depth > 1:
                    try:
                        nested = await page.evaluate("""
                            Array.from(document.querySelectorAll('iframe[src]'))
                                .map(f => f.src).filter(s => s && s.startsWith('http'))
                        """)
                    except Exception:
                        nested = []
                    for n in nested:
                        if captured:
                            break
                        if JUNK_IFRAME_RE.search(n):
                            continue
                        log(f"        nested -> {n[:80]}")
                        try:
                            await page.goto(n, wait_until="domcontentloaded", timeout=20000)
                            await asyncio.sleep(WAIT_PLAYER)
                        except Exception as e:
                            log(f"        [nested nav err] {e}")
    finally:
        try:
            await page.close()
        except Exception:
            pass

    return captured


# ------------------------- M3U output -------------------------
def pick_headers(headers, fallback_referer):
    """Chuẩn hoá headers (lowercase key) và trả về những cái cần cho m3u."""
    h = {k.lower(): v for k, v in (headers or {}).items()}

    referer  = h.get("referer") or fallback_referer or BASE_URL
    origin   = h.get("origin", "")
    cookie   = h.get("cookie", "")
    ua       = h.get("user-agent") or DEFAULT_UA
    accept   = h.get("accept", "")

    return {
        "referer": referer,
        "origin": origin,
        "cookie": cookie,
        "user_agent": ua,
        "accept": accept,
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

        lines.append(
            f'#EXTINF:-1 tvg-name="{title}" tvg-logo="" group-title="{group}",{title}'
        )

        # ---- VLC / IINA / mpv (native HTTP) ----
        lines.append(f"#EXTVLCOPT:http-referrer={h['referer']}")
        lines.append(f"#EXTVLCOPT:http-user-agent={h['user_agent']}")
        if h["origin"]:
            lines.append(f"#EXTVLCOPT:http-origin={h['origin']}")
        if h["cookie"]:
            lines.append(f"#EXTVLCOPT:http-cookie={h['cookie']}")

        # ---- Kodi PVR IPTV Simple (inputstream.adaptive) ----
        kodi_parts = [
            f"Referer={h['referer']}",
            f"User-Agent={h['user_agent']}",
        ]
        if h["origin"]:
            kodi_parts.append(f"Origin={h['origin']}")
        if h["cookie"]:
            kodi_parts.append(f"Cookie={h['cookie']}")
        lines.append("#KODIPROP:inputstream.adaptive.stream_headers=" + "&".join(kodi_parts))

        # ---- TiviMate / OTT Navigator (một số bản hiểu EXTHTTP) ----
        http_parts = [f"Referer: {h['referer']}"]
        if h["origin"]:
            http_parts.append(f"Origin: {h['origin']}")
        if h["cookie"]:
            http_parts.append(f"Cookie: {h['cookie']}")
        lines.append("#EXTHTTP:" + "|".join(http_parts))

        lines.append(e["url"])
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ------------------------- Main -------------------------
async def main():
    log("SoccerSurge playlist generator (v2)")
    log(f"OS       : {platform.system()} ({_CAMOUFOX_OS})")
    log(f"Headless : {HEADLESS}")
    log(f"Output   : {OUTPUT.resolve()}")

    async with AsyncCamoufox(headless=HEADLESS, os=_CAMOUFOX_OS) as browser:
        page = await browser.new_page()

        # -------- 1. Games --------
        log("\n[1/3] Loading homepage ...")
        games = await get_games(page)
        log(f"      {len(games)} game(s) found")
        for g in games[:10]:
            flag = "LIVE" if g["live"] else "    "
            log(f"      [{flag}] {g['title']} ({g['category']})")

        if MAX_GAMES:
            games = games[:MAX_GAMES]

        # -------- 2+3. Stream sites + deep scrape --------
        entries = []
        for i, game in enumerate(games, 1):
            log(f"\n[{i}/{len(games)}] {game['title']} — {game['category']}")
            sites = await get_stream_sites(page, game["href"])
            log(f"    {len(sites)} stream site(s)")

            for j, site in enumerate(sites, 1):
                label = site["site"] or site["url"][:30]
                log(f"    [{j}/{len(sites)}] {label} ({site['quality']}) -> {site['url'][:70]}")

                results = await capture_streams(browser, site["url"])

                for k, item in enumerate(results[:MAX_STREAMS]):
                    suffix = "" if k == 0 else f" #{k+1}"
                    entries.append({
                        "title": f"{game['title']} [{label}]{suffix}",
                        "url": item["url"],
                        "headers": item["headers"],
                        "referer": site["url"],   # fallback nếu capture fail
                        "group": game["category"] or "Soccer",
                    })

        # dedupe + sort
        seen, unique = set(), []
        for e in entries:
            if e["url"] not in seen:
                seen.add(e["url"])
                unique.append(e)
        unique.sort(key=lambda e: (e["group"].lower(), e["title"].lower()))

        write_playlist(unique)
        log(f"\n[3/3] DONE — wrote {len(unique)} stream(s) to {OUTPUT}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
