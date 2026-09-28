#!/usr/bin/env python3
"""
Sportsurge -> IPTV playlist generator.

- Chạy headless (hoặc dưới xvfb) để vượt Cloudflare.
- Scrape các trận đang có trên sportsurge.
- Bắt URL HLS thực sự (.m3u8) từ network traffic.
- Xuất file playlist.m3u tương thích VLC / Kodi / TiviMate / IINA.

Usage:
    python generate_playlist.py
    MAX_GAMES=20 OUTPUT=playlist.m3u python generate_playlist.py
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
BASE_URL     = "https://v2.sportsurge.net/"
OUTPUT       = Path(os.environ.get("OUTPUT", "playlist.m3u"))
MAX_GAMES    = int(os.environ.get("MAX_GAMES", "0")) or None
CF_TIMEOUT   = int(os.environ.get("CF_TIMEOUT", "90"))
MAX_SITES    = int(os.environ.get("MAX_SITES", "5"))    # mỗi trận tối đa 5 site
MAX_STREAMS  = int(os.environ.get("MAX_STREAMS", "5"))  # mỗi trận tối đa 5 link
WAIT_PLAYER  = int(os.environ.get("WAIT_PLAYER", "9"))  # giây chờ player load

_CAMOUFOX_OS = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"} \
    .get(platform.system(), "linux")

# Nếu có DISPLAY (xvfb / desktop) thì chạy dạng headful -> khó bị detect hơn.
HEADLESS = not bool(os.environ.get("DISPLAY"))

# ------------------------- Bộ lọc -------------------------
SKIP_DOMAINS = re.compile(
    r"(sportsurge\.net|cloudflare|cdnjs|cdn-cgi|jquery|bootstrap|google|gstatic"
    r"|adexchange|aclib|login|register|favicon|\.css$|\.js$|\.png$|\.jpg$"
    r"|\.svg$|\.woff)",
    re.IGNORECASE,
)
AD_PATTERNS = re.compile(
    r"(ad/visit|visit\.php|adex|adbid|popunder|popcash|zoneid|zoneId"
    r"|/ads?/|googlesyndication|doubleclick)",
    re.IGNORECASE,
)
# Chỉ những URL này được coi là stream thật:
STREAM_URL_PATTERNS = re.compile(
    r"(\.m3u8(\?|$)|/hls/|manifest\.mpd|/chunklist|/index\.m3u|application/x-mpegurl)",
    re.IGNORECASE,
)
TS_SEGMENT = re.compile(r"\.ts(\?|$)", re.IGNORECASE)


def log(msg=""):
    print(msg, file=sys.stderr, flush=True)


# ------------------------- Helpers -------------------------
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


async def scrape_games(page):
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
    if not await cf_pass(page):
        log("[warn] Cloudflare challenge không clear — thử tiếp tục")
    await asyncio.sleep(2)

    links = await page.evaluate("""
        Array.from(document.querySelectorAll('a[href]'))
            .map(a => ({ text: a.innerText.trim(), href: a.href }))
            .filter(a => a.href && a.text.length > 0)
    """)

    games, seen = [], set()
    for l in links:
        href, text = l["href"], l["text"]
        if href in seen or "/watch-" not in href:
            continue
        seen.add(href)
        clean = " | ".join(x.strip() for x in text.split("\n") if x.strip())
        games.append({"title": clean, "url": href})
    return games


async def scrape_stream_sites(page, game_url):
    try:
        await page.goto(game_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
    except Exception as e:
        log(f"    [err game page] {e}")
        return []

    html = await page.content()
    raw = re.findall(r'https?://[^\s"\'<>\)]+', html)
    sites, seen = [], set()
    for u in raw:
        u = u.rstrip("&;,")
        if u in seen or SKIP_DOMAINS.search(u) or AD_PATTERNS.search(u):
            continue
        seen.add(u)
        sites.append(u)
    return sites[:MAX_SITES]


async def deep_scrape(page, site_url, wait_seconds=WAIT_PLAYER):
    """Vào site stream, hứng request m3u8/manifest từ network."""
    captured = []

    def on_request(req):
        u = req.url
        if STREAM_URL_PATTERNS.search(u) and not TS_SEGMENT.search(u):
            captured.append(u)

    page.on("request", on_request)
    try:
        await page.goto(site_url, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(wait_seconds)
    except Exception as e:
        log(f"      [err site] {e}")
    finally:
        try:
            page.remove_listener("request", on_request)
        except Exception:
            pass

    # dedupe, giữ thứ tự
    return list(dict.fromkeys(captured))


def write_playlist(entries, path=OUTPUT):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "#EXTM3U",
        f"# playlist : sportsurge live streams",
        f"# generated: {ts}",
        f"# streams  : {len(entries)}",
        "",
    ]
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    for e in entries:
        title = e["title"].replace('"', "'")[:90]
        group = e.get("group", "Live Sports")
        referer = e.get("referer", BASE_URL)
        lines.append(
            f'#EXTINF:-1 tvg-name="{title}" tvg-logo="" '
            f'group-title="{group}",{title}'
        )
        # VLC + hầu hết IPTV client hiểu các directive dưới:
        lines.append(f"#EXTVLCOPT:http-referrer={referer}")
        lines.append(f"#EXTVLCOPT:http-user-agent={UA}")
        # Kodi PVR IPTV Simple cũng có thể cần KODIPROP:
        lines.append(f"#KODIPROP:inputstream.adaptive.stream_headers=Referer={referer}")
        lines.append(f"#KODIPROP:inputstream.adaptive.stream_headers=User-Agent={UA}")
        lines.append(e["url"])
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ------------------------- Main -------------------------
async def main():
    log(f"Sportsurge playlist generator")
    log(f"OS      : {platform.system()} ({_CAMOUFOX_OS})")
    log(f"Headless: {HEADLESS}")
    log(f"Output  : {OUTPUT.resolve()}")
    log(f"Max games: {MAX_GAMES or 'all'}")

    async with AsyncCamoufox(headless=HEADLESS, os=_CAMOUFOX_OS) as browser:
        page = await browser.new_page()

        log("\n[1/3] Loading homepage ...")
        games = await scrape_games(page)
        log(f"      {len(games)} game(s) found")

        if MAX_GAMES:
            games = games[:MAX_GAMES]

        entries = []
        for i, game in enumerate(games, 1):
            title = game["title"].split(" | ")[0].strip() or "Game"
            log(f"\n[{i}/{len(games)}] {title[:80]}")

            sites = await scrape_stream_sites(page, game["url"])
            log(f"    {len(sites)} stream site(s)")

            found_for_game = []
            for site in sites:
                log(f"      -> {site[:70]}")
                urls = await deep_scrape(page, site)
                if urls:
                    log(f"         captured {len(urls)} stream(s)")
                    found_for_game.extend(urls)
                if len(found_for_game) >= MAX_STREAMS:
                    break

            # dedupe per-game
            seen_g, picked = set(), []
            for u in found_for_game:
                if u not in seen_g:
                    seen_g.add(u); picked.append(u)

            for idx, u in enumerate(picked[:MAX_STREAMS]):
                suffix = "" if idx == 0 else f" (s{idx+1})"
                entries.append({
                    "title": f"{title}{suffix}",
                    "url": u,
                    "group": "Sportsurge Live",
                    "referer": BASE_URL,
                })

        # dedupe toàn cục + sắp xếp ổn định để diff git ít nhiễu
        seen_all, unique = set(), []
        for e in entries:
            if e["url"] not in seen_all:
                seen_all.add(e["url"]); unique.append(e)
        unique.sort(key=lambda e: e["title"].lower())

        write_playlist(unique)
        log(f"\n[3/3] DONE — wrote {len(unique)} stream(s) to {OUTPUT}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
