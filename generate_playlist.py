#!/usr/bin/env python3
"""
SoccerSurge -> IPTV playlist generator.

Cấu trúc scrape (đi đủ 4 tầng):
  1. soccersurge.io         -> danh sách trận (a.match-row)
  2. /watch-{id}-.../       -> danh sách stream sites (div.stream-item[data-href])
  3. stream site            -> tìm iframe player
  4. iframe player          -> bắt request .m3u8 từ network

Usage:
    python generate_playlist.py
    MAX_GAMES=10 python generate_playlist.py
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
MAX_SITES   = int(os.environ.get("MAX_SITES", "8"))   # mỗi trận tối đa 8 site
MAX_STREAMS = int(os.environ.get("MAX_STREAMS", "3")) # mỗi site tối đa 3 link
CF_TIMEOUT  = int(os.environ.get("CF_TIMEOUT", "90"))
WAIT_PLAYER = int(os.environ.get("WAIT_PLAYER", "8")) # giây chờ player load
IFRAME_DEPTH= int(os.environ.get("IFRAME_DEPTH", "2"))

_CAMOUFOX_OS = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"} \
    .get(platform.system(), "linux")
HEADLESS = not bool(os.environ.get("DISPLAY"))

# ------------------------- Bộ lọc -------------------------
# URL thật sự là stream (m3u8 / HLS / manifest)
STREAM_RE = re.compile(
    r"(\.m3u8(\?|$)|/hls/|manifest\.mpd|/chunklist|/index\.m3u|application/x-mpegurl)",
    re.IGNORECASE,
)
TS_SEGMENT = re.compile(r"\.ts(\?|$)", re.IGNORECASE)

# Iframe cần bỏ qua (không phải player)
JUNK_IFRAME_RE = re.compile(
    r"(youtube|youtu\.be|facebook|twitter|google|doubleclick|googlesyndication"
    r"|analytics|histats|discord|telegram|whatsapp|recaptcha|cloudflare"
    r"|fonts\.googleapis|gstatic|jquery|bootstrap|banner|ad[-_]?tag)",
    re.IGNORECASE,
)


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


# ---------- Tầng 1: lấy danh sách trận từ homepage ----------
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

    # Ưu tiên trận LIVE trước, rồi theo giờ
    out.sort(key=lambda g: (not g["live"], g["time"] or ""))
    return out


# ---------- Tầng 2: lấy danh sách stream sites từ trang trận ----------
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


# ---------- Tầng 3+4: đệ quy vào iframe bắt m3u8 ----------
async def capture_streams(page, url, depth=IFRAME_DEPTH):
    """
    Vào `url`, hứng mọi request .m3u8/manifest. Nếu chưa thấy và còn depth,
    tìm iframe player và đệ quy vào đó.
    Trả về list URL m3u8 (đã dedupe).
    """
    captured = []

    def on_request(req):
        u = req.url
        if STREAM_RE.search(u) and not TS_SEGMENT.search(u):
            captured.append(u)

    page.on("request", on_request)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(WAIT_PLAYER)
    except Exception as e:
        log(f"        [nav err] {e}")
    finally:
        try:
            page.remove_listener("request", on_request)
        except Exception:
            pass

    # Nếu chưa bắt được và còn depth → đệ quy vào iframe
    if not captured and depth > 0:
        try:
            iframes = await page.evaluate("""
                Array.from(document.querySelectorAll('iframe[src]'))
                    .map(f => f.src)
                    .filter(s => s && s.startsWith('http'))
            """)
        except Exception:
            iframes = []

        for iframe_url in iframes:
            if captured:
                break
            if JUNK_IFRAME_RE.search(iframe_url):
                continue
            log(f"        iframe: {iframe_url[:80]}")
            sub = await capture_streams(page, iframe_url, depth - 1)
            captured.extend(sub)

    # dedupe giữ thứ tự
    return list(dict.fromkeys(captured))


# ------------------------- M3U output -------------------------
def write_playlist(entries, path=OUTPUT):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "#EXTM3U",
        "# playlist : soccersurge live soccer",
        f"# generated: {ts}",
        f"# streams  : {len(entries)}",
        "",
    ]
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

    for e in entries:
        title = e["title"].replace('"', "'")[:100]
        group = e.get("group", "Soccer")
        referer = e.get("referer", BASE_URL)

        lines.append(
            f'#EXTINF:-1 tvg-name="{title}" tvg-logo="" group-title="{group}",{title}'
        )
        lines.append(f"#EXTVLCOPT:http-referrer={referer}")
        lines.append(f"#EXTVLCOPT:http-user-agent={UA}")
        lines.append(f"#KODIPROP:inputstream.adaptive.stream_headers=Referer={referer}")
        lines.append(f"#KODIPROP:inputstream.adaptive.stream_headers=User-Agent={UA}")
        lines.append(e["url"])
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def host_of(u):
    try:
        return urlparse(u).netloc
    except Exception:
        return u


# ------------------------- Main -------------------------
async def main():
    log("SoccerSurge playlist generator")
    log(f"OS       : {platform.system()} ({_CAMOUFOX_OS})")
    log(f"Headless : {HEADLESS}")
    log(f"Output   : {OUTPUT.resolve()}")

    async with AsyncCamoufox(headless=HEADLESS, os=_CAMOUFOX_OS) as browser:
        page = await browser.new_page()

        # -------- 1. Games --------
        log("\n[1/3] Loading homepage ...")
        games = await get_games(page)
        log(f"      {len(games)} game(s) found")
        for g in games[:5]:
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
                label = site["site"] or host_of(site["url"])
                log(f"    [{j}/{len(sites)}] {label} ({site['quality']}) -> {site['url'][:70]}")

                streams = await capture_streams(page, site["url"])
                if streams:
                    log(f"        ✓ {len(streams)} m3u8")
                else:
                    log(f"        ✗ no stream")

                for k, s in enumerate(streams[:MAX_STREAMS]):
                    suffix = "" if k == 0 else f" #{k+1}"
                    entries.append({
                        "title": f"{game['title']} [{label}]{suffix}",
                        "url": s,
                        "group": game["category"] or "Soccer",
                        "referer": site["url"],
                    })

        # dedupe toàn cục, sắp xếp ổn định
        seen, unique = set(), []
        for e in entries:
            if e["url"] not in seen:
                seen.add(e["url"])
                unique.append(e)
        unique.sort(key=lambda e: (e["group"].lower(), e["title"].lower()))

        # -------- 4. Write --------
        write_playlist(unique)
        log(f"\n[3/3] DONE — wrote {len(unique)} stream(s) to {OUTPUT}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
