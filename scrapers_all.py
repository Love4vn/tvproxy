#!/usr/bin/env python3
"""
scrapers_all.py - Gom tất cả scraper (HTTP + Playwright) vào 1 module.
Mỗi scraper trả về dict: {key: {"source","logo","refer","tvg-id","link"?, "timestamp"}}
Hỗ trợ: Soccer (bóng đá) + Tennis + các môn khác từ sports.json.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import random
import re
from collections.abc import KeysView
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cache, partial
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from selectolax.lexbor import LexborHTMLParser as HTMLParser

log = logging.getLogger("scrapers")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s] %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)

# ============================================================
# TIME
# ============================================================
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class Time:
    @staticmethod
    def rn() -> datetime:
        return datetime.now(tz=timezone.utc)

    @staticmethod
    def fromisoformat(s: str) -> datetime:
        s = s.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    @staticmethod
    def from_str(s: str, tz_name: str | None = None) -> datetime:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        if tz_name:
            dt = dt.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def from_ts(ts: int | float) -> datetime:
        return datetime.fromtimestamp(ts, tz=timezone.utc)


# ============================================================
# CACHE
# ============================================================
CACHE_DIR = Path.home() / ".cache" / "soccersurge_playlist"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class Cache:
    def __init__(self, tag: str, exp: int = 10800):
        self.path = CACHE_DIR / f"{tag}.json"
        self.exp = exp

    def load(self, per_entry: bool = True, ts_index: int | None = None):
        if not self.path.exists():
            return {} if per_entry else None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {} if per_entry else None
        if per_entry:
            cutoff = Time.rn().timestamp() - self.exp
            return {k: v for k, v in data.items() if v.get("timestamp", 0) >= cutoff}
        if isinstance(data, list) and ts_index is not None:
            if not data:
                return None
            if data[ts_index].get("timestamp", 0) < Time.rn().timestamp() - self.exp:
                return None
            return data
        if isinstance(data, dict) and data.get("timestamp", 0) < Time.rn().timestamp() - self.exp:
            return None
        return data

    def write(self, data) -> None:
        try:
            self.path.write_text(json.dumps(data, default=str), encoding="utf-8")
        except Exception:
            pass


# ============================================================
# LEAGUES (mini, dùng cho tvg-id + logo)
# ============================================================
class Leagues:
    _cache: dict | None = None

    @classmethod
    def _load(cls) -> dict:
        if cls._cache is not None:
            return cls._cache
        try:
            p = Path(__file__).parent / "sports.json"
            cls._cache = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except Exception:
            cls._cache = {}
        return cls._cache

    @classmethod
    def get_tvg_info(cls, sport: str, name: str) -> tuple[str | None, str | None]:
        data = cls._load()
        sl = (sport or "").lower()
        nl = (name or "").lower()
        for lg_key, groups in data.get("leagues", {}).items():
            for grp in groups:
                for league, meta in grp.items():
                    if lg_key.lower() in sl or league.lower() in sl or lg_key.lower() in nl:
                        return lg_key, meta.get("logo")
                    for alias in meta.get("aliases", []):
                        if alias.lower() in sl or alias.lower() in nl:
                            return lg_key, meta.get("logo")
        return None, None


leagues = Leagues()

# ============================================================
# SPORT FILTER — blacklist mọi môn KHÔNG phải soccer/tennis
# ============================================================
BLOCKED_SPORTS_RE = re.compile(
    r"\b("
    # American Football / NFL / NCAA
    r"american\s*football|nfl|ncaa|ncaab|ncaaf|"
    r"afl|aussie\s*rules|"
    # Golf
    r"golf|lpga|pga|"
    # Snooker / Billiards
    r"snooker|billiards|"
    # Basketball
    r"basketball|nba|wnba|nbl|euroleague|fiba|big3|"
    # Baseball
    r"baseball|mlb|milb|"
    # Hockey
    r"hockey|nhl|"
    # Motorsports
    r"world\s*rally|formula\s*[123e]|\bf1\b|\bf2\b|\bf3\b|"
    r"motogp|nascar|motorsport|rally|"
    # Volleyball
    r"volleyball|"
    # Rugby
    r"rugby|nrl|"
    # Cricket
    r"cricket|"
    # Darts
    r"darts|"
    # Combat
    r"ufc|mma|boxing|wrestling|aew|wwe|"
    # Horse Racing
    r"horse\s*racing|"
    # Khác
    r"handball|badminton|esports?|"
    r"skiing|surfing|sailing|archery"
    r")\b",
    re.IGNORECASE,
)


class SportFilter:
    """
    Chỉ cho qua soccer + tennis.
    Dùng blacklist vì tên giải soccer rất đa dạng
    (CONCACAF Nations League, MLS League, Bolivia Copa…).
    """

    @classmethod
    def is_allowed(cls, sport_label: str, name: str = "") -> bool:
        text = f"{sport_label or ''} {name or ''}".strip()
        if not text:
            return False
        # Nếu khớp blacklist → chặn
        if BLOCKED_SPORTS_RE.search(text):
            return False
        return True
# ============================================================
# NETWORK
# ============================================================
class Network:
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            headers={"User-Agent": self.UA, "Accept-Language": "en-US,en;q=0.9"},
            http2=True,
        )
        self.HTTP_S = asyncio.Semaphore(15)
        self.PW_S = asyncio.Semaphore(4)

    async def request(self, url: str, url_num: int | None = None, log_: logging.Logger | None = None,
                      **kwargs) -> httpx.Response | None:
        log_ = log_ or log
        try:
            r = await self.client.get(url, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            pre = f"URL {url_num}) " if url_num else ""
            log_.warning(f"{pre}Failed to fetch {url}: {str(e)[:80]}")
            return None

    @staticmethod
    async def safe_process(fn, url_num: int, semaphore, timeout: int = 25,
                           timeout_return=None, log_: logging.Logger | None = None):
        log_ = log_ or log
        async with semaphore:
            task = asyncio.create_task(fn())
            try:
                return await asyncio.wait_for(task, timeout=timeout)
            except asyncio.TimeoutError:
                log_.warning(f"URL {url_num}) timeout {timeout}s")
                task.cancel()
                try:
                    await task
                except Exception:
                    pass
                return timeout_return
            except Exception as e:
                log_.error(f"URL {url_num}) {str(e)[:80]}")
                return timeout_return


network = Network()


def _mk_entry(source: str | None, refer: str, sport: str, name: str,
              logo: str | None = None, tvg_id: str | None = None,
              link: str | None = None,
              event_ts: float | None = None) -> dict:
    tid, lg_logo = leagues.get_tvg_info(sport, name)
    return {
        "source": source,
        "logo": logo or lg_logo,
        "refer": refer,
        "timestamp": Time.rn().timestamp(),
        "event_ts": event_ts,                       # ← THÊM
        "tvg-id": tvg_id or tid or "Live.Event.us",
        "link": link,
    }


# ============================================================
# SCRAPER: XyzStreams (AES decrypt)
# ============================================================
XYZS_TAG = "XYZ"
XYZS_CACHE = Cache(XYZS_TAG, exp=10800)
XYZS_HTML = Cache(f"{XYZS_TAG}-html", exp=19800)
XYZS_BASE = "https://xyzstreams.st"
XYZS_SERVERS = [
    "https://eu-hlss2.b-cdn.net/",
    "https://hlss2.b-cdn.net/",
    "https://us2-hlss2.b-cdn.net/",
]
XYZS_KEY = "TXlTdXBlclNlY3JldEtleTEyMyE="


def _xyz_decrypt(secret: str, token_h: str, iv_h: str) -> str:
    key = hashlib.sha256(secret.encode()).digest()
    iv = bytes.fromhex(iv_h)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    dec = unpad(cipher.decrypt(bytes.fromhex(token_h)), AES.block_size)
    raw = dec.decode("utf-8", errors="ignore")
    return re.sub(r"[^\x20-\x7E]", "", raw).strip()


async def _xyz_process(url: str, n: int) -> str | None:
    server = random.choice(XYZS_SERVERS)
    if not (html := await network.request(url, n, headers={"Referer": XYZS_BASE})):
        return
    if not (api := await network.request(urljoin(server, "api/token"), n, headers={"Referer": url})):
        return
    td = api.json()
    token, iv = td.get("token"), td.get("iv")
    if not (token and iv):
        return
    soup = HTMLParser(html.content)
    iframe = soup.css_first("iframe#stream-player")
    if not iframe or not (src := iframe.attributes.get("src")):
        return
    raw = _xyz_decrypt(base64.b64decode(XYZS_KEY).decode(), token, iv)
    log.info(f"XYZ URL {n}) captured")
    return urljoin(server, f"{urlsplit(src).query}/mono.ts.m3u8?token={raw}")


async def xyzstreams_scrape() -> dict:
    events: dict = {}
    cached = XYZS_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    now = Time.rn()
    html_data = XYZS_HTML.load(per_entry=False)
    if not html_data:
        r = await network.request(XYZS_BASE)
        if not r:
            return events
        m = re.search(r"(?:const|let|var)\s+EVENTS_DATA\s*=\s*(\[.*?\])\s*;", r.text, re.S | re.I)
        if not m:
            return events
        html_data = {"timestamp": now.timestamp(), "list": json.loads(m[1])}
        XYZS_HTML.write(html_data)

    start = now - timedelta(minutes=30)
    end = now + timedelta(minutes=30)
    for game in html_data.get("list", []):
        try:
            sport, name, etime, href = (game.get(x) for x in ("category", "title", "start", "href"))
            if not all([sport, name, etime, href]):
                continue
            ed = Time.fromisoformat(etime).astimezone(timezone.utc)
            if not (start <= ed <= end):
                continue
            key = f"[{sport}] {name} ({XYZS_TAG})"
            if key in events:
                continue
            src = await _xyz_process(urljoin(XYZS_BASE, href), 1)
            events[key] = _mk_entry(
                src, urljoin(XYZS_BASE, href), sport, name,
                logo=game.get("bg"),
                event_ts=ed.timestamp(),                    # ← THÊM
            )
        except Exception:
            continue
    XYZS_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: FAWA
# ============================================================
FAWA_TAG = "FAWA"
FAWA_BASE = "http://www.fawanews.sc/"
FAWA_CACHE = Cache(FAWA_TAG, exp=10800)


async def fawa_scrape() -> dict:
    events: dict = {}
    cached = FAWA_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    r = await network.request(FAWA_BASE)
    if not r:
        return events
    soup = HTMLParser(r.content)
    valid = re.compile(r"\d{1,2}:\d{1,2}")
    clean = re.compile(r"\s+-+\s+\w{1,4}")
    ptrn = re.compile(
        r'var\s+(\w+)\s*=\s*\[["\']?(https?:\/\/[^"\'\s>]+\.m3u8(?:\?[^"\'\s>]*)?)["\']\]?',
        re.I,
    )

    for item in soup.css(".user-item"):
        text_el = item.css_first(".user-item__name")
        sub_el = item.css_first(".user-item__playing")
        link_el = item.css_first("a[href]")
        if not (text_el and sub_el and link_el):
            continue
        href = link_el.attributes.get("href")
        if not href:
            continue
        name_raw = text_el.text(strip=True)
        details = sub_el.text(strip=True)
        if not valid.search(details):
            continue
        sport = valid.split(details)[0].strip()
        name = clean.sub("", name_raw)
        link = urljoin(FAWA_BASE, href)
        key = f"[{sport}] {name} ({FAWA_TAG})"
        if key in events:
            continue
        rr = await network.request(link, headers={"Referer": FAWA_BASE})
        if not rr:
            continue
        m = ptrn.search(rr.text)
        events[key] = _mk_entry(
            m[2] if m else None, FAWA_BASE, sport, name, link=link,
            event_ts=None,     # FAWA không cung cấp giờ chính xác
        )
    FAWA_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: PelotaLibre (Tennis included)
# ============================================================
PLIBRE_TAG = "PLIBRE"
PLIBRE_BASE = "https://la18hd.su"
PLIBRE_CACHE = Cache(PLIBRE_TAG, exp=19800)


async def pelotalibre_scrape() -> dict:
    events: dict = {}
    cached = PLIBRE_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    r = await network.request(urljoin(PLIBRE_BASE, "eventos/json/agenda123.json"))
    if not r:
        return events
    ptrn = re.compile(r'var\s+playbackURL\s+=\s+"([^"]*)"', re.I)
    from collections import defaultdict
    counter: dict[str, int] = defaultdict(int)

    for ev in r.json():
        try:
            title, sport0, link = ev.get("title"), ev.get("category"), ev.get("link")
            if not all([title, link]):
                continue
            try:
                sport, name = (i.strip() for i in re.split(r"[:–-]", title, maxsplit=1))
            except ValueError:
                sport, name = "Live Event", title
            if not urlsplit(link).query:
                continue
            if not dict(parse_qsl(urlsplit(link).query)).get("stream"):
                continue
            if not link.startswith(PLIBRE_BASE):
                link = urlunsplit(urlsplit(link)._replace(netloc=urlsplit(PLIBRE_BASE).netloc))
            lang = (ev.get("language") or "").capitalize()
            name = f"{name.split('|')[0].strip()} | {lang}" if lang else name.split('|')[0].strip()
            counter[name] += 1
            name = f"{name} {counter[name]}"
            key = f"[{sport}] {name} ({PLIBRE_TAG})"
            if key in events:
                continue
            rr = await network.request(link, headers={"Referer": PLIBRE_BASE})
            m = ptrn.search(rr.text) if rr else None
            ets = ev.get("date") or ev.get("start") or None
            try:
                ed = Time.from_iso(ets) if ets else None
            except Exception:
                ed = None
            events[key] = _mk_entry(
                m[1] if m else None, link, sport, name, link=link,
                event_ts=ed.timestamp() if ed else None,
            )
        except Exception:
            continue
    PLIBRE_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: StreamTP (Tennis + all sports)
# ============================================================
STP_TAG = "STP"
STP_BASE = "https://streamx305.sbs"
STP_CACHE = Cache(STP_TAG, exp=19800)


async def streamtp_scrape() -> dict:
    events: dict = {}
    cached = STP_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    r = await network.request(urljoin(STP_BASE, "json/agenda550.json"))
    if not r:
        return events
    from collections import defaultdict
    counter: dict[str, int] = defaultdict(int)
    now_str = Time.rn().strftime("%Y-%m-%d")

    digit_ptrn = re.compile(r"{return\s+(\d*);}", re.I)
    embed_ptrn = re.compile(r"(\w+)\s*=\s*(\[\[.*?\]\])\s*;(?=\s*\1\.sort\()", re.S)

    for ev in r.json():
        try:
            title, link, date = ev.get("title"), ev.get("link"), ev.get("date")
            if not all([title, link, date]) or date != now_str:
                continue
            try:
                sport, name = (i.strip() for i in re.split(r"[:–-]", title, maxsplit=1))
            except ValueError:
                sport, name = "Live Event", title

            rr = await network.request(
                link, headers={
                    "Referer": STP_BASE, "Sec-Fetch-Dest": "iframe",
                    "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin",
                })
            if not rr:
                continue
            digits = digit_ptrn.findall(rr.text)
            m = embed_ptrn.search(rr.text)
            src = None
            if digits and m:
                try:
                    import ast
                    emb = ast.literal_eval(m.group(0).split("=", 1)[-1].strip(";"))
                    base = sum(map(int, digits[:2]))
                    m3u = "".join(
                        chr(int("".join(c for c in base64.b64decode(v).decode("utf-8") if c.isdigit())) - base)
                        for _, v in sorted(emb, key=lambda i: i[0])
                    )
                    sp = urlsplit(m3u)
                    params = [(k, v) for k, v in parse_qsl(sp.query) if k.lower() != "ip"]
                    src = urlunsplit(sp._replace(query=urlencode(params)))
                except Exception:
                    src = None
            lang = (ev.get("language") or "").capitalize()
            name = f"{name.split('|')[0].strip()} | {lang}" if lang else name.split('|')[0].strip()
            counter[name] += 1
            name = f"{name} {counter[name]}"
            key = f"[{sport}] {name} ({STP_TAG})"
            events[key] = _mk_entry(
                src, link, sport, name, link=link,
                event_ts=Time.from_str(ev["time"], tz_name="EST").timestamp() if ev.get("time") else None,
            )
        except Exception:
            continue
    STP_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: StreamXHD
# ============================================================
SXHD_TAG = "STRMXHD"
SXHD_BASE = "https://streamxhd.com"
SXHD_CACHE = Cache(SXHD_TAG, exp=19800)


async def streamxhd_scrape() -> dict:
    events: dict = {}
    cached = SXHD_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    r = await network.request(urljoin(SXHD_BASE, "eventos.json"))
    if not r:
        return events
    now = Time.rn()
    for sport_block in r.json().get("sports", []):
        for lg in sport_block.get("leagues", []):
            sport = lg["name"]
            for ev in lg.get("events", []):
                try:
                    name = ev["title"]
                    ed = Time.from_str(ev["time"], tz_name="EST")
                    if ed.date() != now.date():
                        continue
                    for srv in ev.get("servers", []):
                        if ".php" not in srv["url"]:
                            continue
                        link = srv["url"]
                        lang = srv["name"]
                        key = f"[{sport}] {name} | {lang} ({SXHD_TAG})"
                        if key in events:
                            continue
                        rr = await network.request(link, headers={"Referer": SXHD_BASE})
                        src = None
                        if rr:
                            digits = re.findall(r"{return\s+(\d*);}", rr.text, re.I)
                            m = re.search(r"(\w+)\s*=\s*(\[\[.*?\]\])\s*;(?=\s*\1\.sort\()", rr.text, re.S)
                            if digits and m:
                                try:
                                    import ast
                                    emb = ast.literal_eval(m.group(0).split("=", 1)[-1].strip(";"))
                                    base = sum(map(int, digits[:2]))
                                    m3u = "".join(
                                        chr(int("".join(c for c in base64.b64decode(v).decode("utf-8") if c.isdigit())) - base)
                                        for _, v in sorted(emb, key=lambda i: i[0])
                                    )
                                    sp = urlsplit(m3u)
                                    params = [(k, v) for k, v in parse_qsl(sp.query) if k.lower() != "ip"]
                                    src = urlunsplit(sp._replace(query=urlencode(params)))
                                except Exception:
                                    pass
                        events[key] = _mk_entry(
                            src, link, sport, f"{name} | {lang}", link=link,
                            event_ts=ed.timestamp(),
                        )
                except Exception:
                    continue
    SXHD_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: StreamFree
# ============================================================
SFREE_TAG = "STRMFREE"
SFREE_BASE = "https://streamfree.top"
SFREE_CACHE = Cache(SFREE_TAG, exp=10800)
SFREE_API = Cache(f"{SFREE_TAG}-api", exp=19800)


async def streamfree_scrape() -> dict:
    events: dict = {}
    cached = SFREE_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    now = Time.rn()
    api_data = SFREE_API.load(per_entry=False)
    if not api_data:
        rr = await network.request(urljoin(SFREE_BASE, "api/v1/streams"))
        if not rr:
            return events
        api_data = rr.json()
        api_data["timestamp"] = now.timestamp()
        SFREE_API.write(api_data)

    start = (now - timedelta(hours=3)).timestamp()
    now_ts = now.timestamp()

    for s in api_data.get("streams", []):
        try:
            sport = s["league"]; category = s["category"]; name = s["name"]
            ets = s["match_timestamp"]; sk = quote(s["stream_key"])
            if not (start <= ets + 1800 <= now_ts):
                continue
            key = f"[{sport}] {name} ({SFREE_TAG})"
            if key in events:
                continue
            # Lấy chất lượng
            status = await network.request(urljoin(SFREE_BASE, f"api/stream-status/{sk}"))
            if not status:
                continue
            sd = status.json()
            if not sd.get("available"):
                continue
            sources = sd.get("sources", {})
            qual_sources = {
                f"{q}{n}": v for n, sdata in sources.items() for q, v in sdata["qualities"].items()
            }
            quals = sorted(
                [q.split("p") for q, flag in qual_sources.items() if flag],
                key=lambda x: int(x[-1]),
            )
            if not quals:
                continue
            q, n = f"{quals[0][0]}p", quals[0][-1]
            n = "" if n == "1" else n
            server_name = "cdn"
            si = await network.request(urljoin(SFREE_BASE, f"get-stream-key/{sk}"))
            if si:
                server_name = si.json().get("server_name", "cdn")
            embed = await network.request(
                urljoin(SFREE_BASE, f"embed/{category}/{sk}{n}"),
                params={"quality": q, "category": category},
                timeout=httpx.Timeout(25.0),
            )
            if not embed:
                continue
            m = re.search(r"_0x\s+=\s+(.*?);", embed.text, re.S)
            if not m:
                continue
            info = json.loads(m[1])[q]
            src = urljoin(SFREE_BASE, f"live-{server_name}/{sk}{q}{n}/index.m3u8?{urlencode(info)}")
            events[key] = _mk_entry(
                src, SFREE_BASE, sport, name,
                logo=s.get("thumbnail_url"), link=SFREE_BASE,
                event_ts=ets,
            )
        except Exception:
            continue
    SFREE_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: StreamGate (Soccer, MLB, NFL, NHL, UFC)
# ============================================================
SGT_TAG = "STRMGATE"
SGT_BASE = "https://embedme.st"
SGT_CACHE = Cache(SGT_TAG, exp=10800)
SGT_API = Cache(f"{SGT_TAG}-api", exp=28800)
# Mới — chỉ soccer (không có tennis ở API này)
SGT_SPORTS = ["soccer"]


async def streamgate_scrape() -> dict:
    events: dict = {}
    cached = SGT_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    now = Time.rn()
    api_data = SGT_API.load(per_entry=False, ts_index=-1)
    if not api_data:
        results = await asyncio.gather(*[
            network.request(urljoin(SGT_BASE, "api/v1/games.php"),
                            params={"sport": sp, "limit": 100}, timeout=httpx.Timeout(25.0))
            for sp in SGT_SPORTS
        ])
        from itertools import chain
        api_data = list(chain.from_iterable(r.json().get("data", []) for r in results if r))
        if api_data:
            api_data.append({"timestamp": now.timestamp()})
        SGT_API.write(api_data)

    start = now - timedelta(hours=3)
    end = now + timedelta(minutes=30)
    m3u_ptrn = re.compile(r"(file|source|streamurls?)\s*(:|=)\s+(\'|\")([^\"]*)(\'|\")", re.I)
    m3u_ptrn2 = re.compile(r"(streamurls|0x31c4)\s?=\s?\[\s*[\"']([^\"']+)[\"']", re.I)

    for g in api_data:
        if not isinstance(g, dict) or "league" not in g:
            continue
        try:
            sport = " ".join(i.strip() for i in g["league"].split("_"))
            ed = Time.fromisoformat(g["start_at"]).astimezone(timezone.utc)
            if not (start <= ed <= end):
                continue
            home = g.get("home", {}).get("name")
            away = g.get("away", {}).get("name")
            if not home:
                continue
            name = f"{away} vs {home}" if away and away != home else home
            for s in g.get("streams", []):
                lang = s.get("label") or "English"
                url = urljoin(SGT_BASE, s.get("url") or "")
                if not url:
                    continue
                key = f"[{sport}] {name} | {lang} ({SGT_TAG})"
                if key in events:
                    continue
                rr = await network.request(url, headers={"Referer": SGT_BASE}, timeout=httpx.Timeout(25.0))
                if not rr:
                    continue
                soup = HTMLParser(rr.content)
                ifr = soup.css_first("iframe")
                if not ifr or not (src := ifr.attributes.get("src")):
                    continue
                if src.startswith("//"): src = "https:" + src
                r2 = await network.request(src, headers={"Referer": url})
                if not r2:
                    continue
                m = m3u_ptrn.search(r2.text) or m3u_ptrn2.search(r2.text)
                if not m:
                    continue
                cap = m.group(4) if m.re is m3u_ptrn else m.group(2)
                m3u = json.loads(f'"{cap}"')
                if ".live" in m3u: m3u = re.sub(r"\.live\n", ".pro", m3u)
                events[key] = _mk_entry(
                    m3u, src, sport, f"{name} | {lang}", link=url,
                    event_ts=ed.timestamp(),
                )
        except Exception:
            continue
    SGT_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: TVF90 (Soccer + others)
# ============================================================
TVF_TAG = "TVF90"
TVF_BASE = "https://tvf90.com"
TVF_API_URL = "https://api.wqxag.com/diaries.json"
TVF_CACHE = Cache(TVF_TAG, exp=19800)
TVF_API = Cache(f"{TVF_TAG}-api", exp=28800)


async def tvf90_scrape() -> dict:
    events: dict = {}
    cached = TVF_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    now = Time.rn()
    api_data = TVF_API.load(per_entry=False)
    if not api_data:
        rr = await network.request(TVF_API_URL)
        if not rr:
            return events
        api_data = rr.json()
        api_data["timestamp"] = now.timestamp()
        TVF_API.write(api_data)

    ptrn = re.compile(r'var\s+playbackURL\s+=\s+"([^"]*)"', re.I)
    for ev in api_data.get("data", []):
        attrs = ev.get("attributes") or {}
        embeds = (attrs.get("embeds") or {}).get("data") or []
        en = attrs.get("diary_description", "")
        ed = attrs.get("date_diary")
        if ed != f"{now.date()}":
            continue
        try:
            sport, name = (i.strip() for i in re.split(r"[:–-]", en, maxsplit=1))
        except ValueError:
            sport, name = "Live Event", en
        for fr in embeds:
            fa = fr.get("attributes") or {}
            href = fa.get("embed_iframe")
            if not href:
                continue
            b64 = dict(parse_qsl(urlsplit(href).query)).get("r")
            if not b64:
                continue
            real = base64.b64decode(b64).decode().strip()
            label = fa.get("embed_name", "stream")
            key = f"[{sport}] {name} | {label} ({TVF_TAG})"
            if key in events:
                continue
            rr = await network.request(real, headers={"Referer": TVF_BASE})
            m = ptrn.search(rr.text) if rr else None
            src = None
            if m:
                sp = urlsplit(m[1])
                params = [(k, v) for k, v in parse_qsl(sp.query) if k.lower() != "ip"]
                src = urlunsplit(sp._replace(query=urlencode(params)))
            events[key] = _mk_entry(
                src, real, sport, f"{name} | {label}", link=real,
                event_ts=None,     # TVF90 không có giờ cụ thể, chỉ có ngày
            )
    TVF_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: MainPortal (MLB/NFL/NHL)
# ============================================================
MP_TAG = "MP66"
MP_CACHE = Cache(MP_TAG, exp=10800)
MP_API_URLS = {sp: f"https://api.{sp.lower()}24all.ir" for sp in ["MLB", "NFL", "NHL"]}
MP_BASE_URLS = {sp: u.replace("api.", "") for sp, u in MP_API_URLS.items()}


async def mainportal_scrape() -> dict:
    events: dict = {}
    cached = MP_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    now = Time.rn()
    start = now - timedelta(hours=1)
    end = now + timedelta(minutes=1)

    results = await asyncio.gather(*[network.request(u) for u in MP_BASE_URLS.values()])
    ptrn = re.compile(r"var\s+stateshot\s+=\s+(.*);", re.I)

    for r, sport in zip(results, MP_BASE_URLS.keys()):
        if not r:
            continue
        m = ptrn.search(r.text)
        if not m:
            continue
        data = json.loads(m[1])
        teams = {t.get("id"): t.get("name") for t in data.get("teams", {})}
        event_to_flavor = {eid: f["id"] for f in data.get("flavors", {}) for eid in f.get("media_event_ids", [])}
        media_ids = {x.get("game_id"): x.get("id") for x in data.get("media_events", {})}
        for game in data.get("games", {}):
            gid = game["id"]
            ed = Time.fromisoformat(game["datetime"]).astimezone(timezone.utc)
            if not (start <= ed <= end):
                continue
            away = teams.get(game["away_team_id"]); home = teams.get(game["home_team_id"])
            name = f"{away} vs {home}"
            key = f"[{sport}] {name} ({MP_TAG})"
            if key in events:
                continue
            mid = media_ids.get(gid, 0)
            fid = event_to_flavor.get(mid)
            if not (fid and fid.lower().startswith("free.live")):
                continue
            try:
                rr = await network.client.post(
                    urljoin(MP_API_URLS[sport], "api/v2/generate_stream_info"),
                    headers={"Referer": MP_BASE_URLS[sport]},
                    json={"flavor_id": fid, "media_event_id": mid},
                )
                m3u = rr.json().get("url") if rr.is_success else None
            except Exception:
                m3u = None
            events[key] = _mk_entry(m3u, MP_BASE_URLS[sport], sport, name, link=MP_BASE_URLS[sport])
    MP_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: ReedStreams (hockey + soccer + others)
# ============================================================
REED_TAG = "REED"
REED_DOMAIN = "reedstreams.link"
REED_CACHE = Cache(REED_TAG, exp=10800)
REED_API = Cache(f"{REED_TAG}-api", exp=28800)


async def reedstreams_scrape() -> dict:
    events: dict = {}
    cached = REED_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    now = Time.rn()
    api_data = REED_API.load(per_entry=False, ts_index=-1)
    if not api_data:
        rr = await network.request(urljoin(f"https://api.{REED_DOMAIN}", "api/matches/all"))
        if not rr:
            return events
        api_data = rr.json()
        api_data.append({"timestamp": now.timestamp()})
        REED_API.write(api_data)

    start = now - timedelta(hours=1)
    end = now + timedelta(minutes=30)
    for ev in api_data:
        if not isinstance(ev, dict):
            continue
        try:
            cat = ev["category"]
            # Mới — chỉ soccer (bóng đá) và tennis
            if cat not in {"soccer", "tennis"}:
                continue
            name = re.sub(r"(\r|\n|\t)", "", ev["title"]).strip()
            sport = re.sub(r"(\r|\n|\t)", "", ev["league_name"]).strip()
            ets = int(f"{ev['date']}"[:-3])
            ed = Time.from_ts(ets)
            if not (start <= ed <= end):
                continue
            key = f"[{sport}] {name} ({REED_TAG})"
            if key in events:
                continue
            link = urljoin(f"https://links.{REED_DOMAIN}", f"stream/{ev['id']}")
            rr = await network.request(link)
            src = None
            if rr:
                try:
                    streams = rr.json().get("streams", [])
                    urls = [s.get("embedUrl") for s in streams if s.get("source") == "tnasty"]
                    if urls:
                        q = dict(parse_qsl(urlsplit(urls[0]).query))
                        m3u = q.get("src") or q.get("url")
                        from urllib.parse import unquote
                        src = unquote(m3u) if m3u else None
                except Exception:
                    pass
            logo = None
            if ev.get("poster"):
                logo = urljoin(f"https://api.{REED_DOMAIN}", ev["poster"])
            events[key] = _mk_entry(src, f"https://{REED_DOMAIN}", sport, name, logo=logo, link=link)
        except Exception:
            continue
    REED_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: DamiTV
# ============================================================
DAMI_TAG = "DAMITV"
DAMI_BASE = "https://ondemand.st"
DAMI_CACHE = Cache(DAMI_TAG, exp=10800)
DAMI_API = Cache(f"{DAMI_TAG}-api", exp=28800)


async def dami_scrape() -> dict:
    events: dict = {}
    cached = DAMI_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    now = Time.rn()
    api_data = DAMI_API.load(per_entry=False, ts_index=-1)
    if not api_data:
        rr = await network.request(urljoin(DAMI_BASE, "papi/matches/all-today"))
        if not rr:
            return events
        api_data = rr.json()
        api_data.append({"timestamp": now.timestamp()})
        DAMI_API.write(api_data)

    start = now - timedelta(minutes=30)
    end = now + timedelta(minutes=30)
    for ev in api_data:
        if not isinstance(ev, dict):
            continue
        try:
            title = ev["title"]; league = ev["league"]
            ets = int(f"{ev['date']}"[:-3])
            sid = ev["id"]
            if sid.lower().startswith("dl-") or sid.startswith("247") or league.startswith("24/7"):
                continue
            sport = " ".join(i.capitalize().strip() for i in league.split("-")) if league.islower() else league
            ed = Time.from_ts(ets)
            if not (start <= ed <= end):
                continue
            key = f"[{sport}] {title} ({DAMI_TAG})"
            if key in events:
                continue
            rr = await network.request(
                urljoin(DAMI_BASE, f"papi/extract-url/{sid}"),
                headers={"Referer": DAMI_BASE})
            src = None
            if rr:
                try:
                    data = rr.json()
                    if data.get("success"):
                        src = data.get("hlsUrl") or data.get("sdUrl")
                except Exception:
                    pass
            events[key] = _mk_entry(
                src, urljoin(DAMI_BASE, f"embed/?id={sid}"), sport, title,
                logo=ev.get("poster"),
                event_ts=ed.timestamp(),
            )
        except Exception:
            continue
    DAMI_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: FlyEmbed
# ============================================================
FLY_TAG = "FLYEMBD"
FLY_BASE = "https://flyembed.click/"
FLY_API = "https://ovogoal.cyou/api/v2/flyembed2.json"
FLY_CACHE = Cache(FLY_TAG, exp=7200)
FLY_CACHE_API = Cache(f"{FLY_TAG}-api", exp=19800)


async def flyembed_scrape() -> dict:
    events: dict = {}
    cached = FLY_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    now = Time.rn()
    api_data = FLY_CACHE_API.load(per_entry=False, ts_index=-1)
    if not api_data:
        rr = await network.request(FLY_API)
        if not rr:
            return events
        api_data = rr.json()
        api_data.append({"timestamp": now.timestamp()})
        FLY_CACHE_API.write(api_data)

    start = now - timedelta(hours=3)
    end = now + timedelta(minutes=30)

    num_ptrn = re.compile(r"var\s+_(\w+)=\[([^\]]*)\],", re.S)
    idx_ptrn = re.compile(r"(_[a-z]+\d+)=(\d+)")
    m3u_ptrn = re.compile(r'(var\s?signed_)?url\s?=\s?"(.*)";', re.I)

    for ev in api_data:
        if not isinstance(ev, dict):
            continue
        try:
            sport = ev["League"]; away = ev["Team1"]; home = ev["Team2"]
            d = ev["MatchDate"]; t = ev["MatchStartTime"]; link = ev["IframeURL"]
            ed = Time.from_str(f"{d} {t}", tz_name="ALMT")
            if not (start <= ed <= end):
                continue
            name = f"{away.strip()} vs {home.strip()}"
            key = f"[{sport}] {name} ({FLY_TAG})"
            if key in events:
                continue
            rr = await network.request(link, headers={"Referer": FLY_BASE})
            src = None
            if rr:
                soup = HTMLParser(rr.content)
                iframe = soup.css_first("iframe")
                isrc = iframe.attributes.get("src") if iframe else None
                if isrc:
                    rr2 = await network.request(isrc, headers={"Referer": link})
                    if rr2:
                        nums = num_ptrn.findall(rr2.text)
                        idxs = idx_ptrn.findall(rr2.text)
                        if nums and idxs:
                            num_list = (int(n.strip()) for n in nums[-1][-1].split(","))
                            if len(idxs) > 2: del idxs[-1]
                            x, y = (int(i[-1].strip()) for i in idxs)
                            js = "".join(chr(((i ^ x) - y + 256) & 255) for i in num_list)
                            mm = m3u_ptrn.search(js)
                            if mm:
                                src = json.loads(f'"{mm[2]}"')
            events[key] = _mk_entry(
                src, link, sport, name, link=link,
                event_ts=ed.timestamp(),
            )
        except Exception:
            continue
    FLY_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: iStreamEast
# ============================================================
ISE_TAG = "iSTRMEAST"
ISE_BASE = "https://streameast.cool"
ISE_CACHE = Cache(ISE_TAG, exp=10800)


async def istreameast_scrape() -> dict:
    events: dict = {}
    cached = ISE_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    r = await network.request(ISE_BASE)
    if not r:
        return events
    soup = HTMLParser(r.content)
    ptrn = re.compile(r'const\s+source\s+=\s+"([^"]*)"', re.I)

    for link in soup.css("li.f1-podium--item > a.f1-podium--link"):
        li = link.parent
        if not li:
            continue
        rank = li.css_first(".f1-podium--rank")
        time_el = li.css_first(".SaatZamanBilgisi")
        drv = li.css_first(".f1-podium--driver")
        if not (rank and time_el and drv):
            continue
        if time_el.text(strip=True).lower() != "live":
            continue
        sport = rank.text(strip=True)
        name = drv.text(strip=True)
        if inner := drv.css_first("span.d-md-inline"):
            name = inner.text(strip=True)
        href = link.attributes.get("href")
        if not href:
            continue
        key = f"[{sport}] {name} ({ISE_TAG})"
        if key in events:
            continue
        rr = await network.request(href, headers={"Referer": ISE_BASE})
        src = None; ifr_url = None
        if rr:
            soup2 = HTMLParser(rr.content)
            iframe = soup2.css_first("iframe#wp_player")
            if iframe and (isrc := iframe.attributes.get("src")):
                ifr_url = isrc
                rr2 = await network.request(isrc)
                m = ptrn.search(rr2.text) if rr2 else None
                src = m[1] if m else None
        events[key] = _mk_entry(src, ifr_url or ISE_BASE, sport, name, link=href)
    ISE_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: StreamCenter (edgestream links)
# ============================================================
SC_TAG = "STRMCNTR"
SC_BASE = "https://streamecenter.live"
SC_ALT = "https://streame.center"
SC_CACHE = Cache(SC_TAG, exp=28800)


async def streamcenter_scrape() -> dict:
    events: dict = {}
    cached = SC_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    r = await network.request(urljoin(SC_BASE, "game-cards/embed"))
    if not r:
        return events
    soup = HTMLParser(r.content)
    now = Time.rn()

    for card in soup.css(".game-card-group"):
        se = card.css_first("h2")
        if not se:
            continue
        sport = "".join(i for i in se.text(strip=True).split("—")[-1] if i.isascii()).strip()
        for game in card.css(".game-card-row"):
            te = game.css_first(".game-card-when > time")
            if not te:
                continue
            ts = te.attributes.get("datetime")
            if not ts:
                continue
            ed = Time.fromisoformat(ts).astimezone(timezone.utc)
            if ed.date() != now.date():
                continue
            ne = game.css_first("h3")
            if not ne or not (evname := ne.attributes.get("aria-label")):
                continue
            for source in game.css(".game-card-source > a.game-card-open-link"):
                href = source.attributes.get("href")
                if not href:
                    continue
                lang = source.text(strip=True)
                link = urljoin(SC_BASE, href)
                key = f"[{sport}] {evname} | {lang} ({SC_TAG})"
                if key in events:
                    continue
                rr = await network.request(link, headers={"Referer": SC_BASE}, timeout=httpx.Timeout(25.0))
                src = None
                if rr:
                    soup2 = HTMLParser(rr.content)
                    iframe = soup2.css_first("iframe")
                    if iframe and (isrc := iframe.attributes.get("src")):
                        sid = dict(parse_qsl(urlsplit(isrc).query)).get("stream")
                        if sid:
                            src = (f"https://edgestream3.pro/stream/{sid}.m3u8"
                                   if sid.isdigit()
                                   else f"https://edgestream2.pro/hls/{sid}.m3u8")
                events[key] = _mk_entry(src, SC_ALT, sport, f"{evname} | {lang}", link=link)
    SC_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: Webcast (MLB/NFL/NHL)
# ============================================================
WC_TAG = "WEBCAST"
WC_CACHE = Cache(WC_TAG, exp=12600)
WC_BASES = {
    "MLB": {"base": "https://mlbwebcast.com", "api": "stream/check_stream.php"},
    "NFL": {"base": "https://nflwebcast.com", "api": "live/check_stream.php"},
    "NHL": {"base": "https://slapstreams.com", "api": "stream/check_stream.php"},
}


async def webcast_scrape() -> dict:
    import ast
    events: dict = {}
    cached = WC_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    r = await network.request(WC_BASES["MLB"]["base"])
    if not r:
        return events

    for sport, cfg in WC_BASES.items():
        rr = await network.request(cfg["base"])
        if not rr:
            continue
        soup = HTMLParser(rr.content)
        for row in soup.css("tr.singele_match_date"):
            vs = row.css_first("td.teamvs a")
            if not vs:
                continue
            name = vs.text(strip=True)
            for span in vs.css("span.mtdate"):
                name = name.replace(span.text(strip=True), "").strip()
            href = vs.attributes.get("href")
            if not href:
                continue
            name = " vs ".join(name.split("@"))
            link = urljoin(cfg["base"], href)
            key = f"[{sport}] {name} ({WC_TAG})"
            if key in events:
                continue
            er = await network.request(link, headers={"Referer": cfg["base"]})
            src = None
            if er:
                soup2 = HTMLParser(er.content)
                iframe = soup2.css_first('iframe[name="srcFrame"]')
                if iframe and (isrc := iframe.attributes.get("src")):
                    if isrc.lower() == "about:blank":
                        isrc = iframe.attributes.get("data-litespeed-src")
                    if isrc:
                        ir = await network.request(isrc, headers={"Referer": link})
                        if ir:
                            m = re.search(r'var\s+\w*=\[([^"]*)\];', ir.text, re.I)
                            if m:
                                try:
                                    eid, ets, ept = ast.literal_eval(m[1])
                                    params = dict(zip(["id", "ts", "pt"], [eid, ets, ept]))
                                    ar = await network.request(
                                        urljoin(cfg["base"], cfg["api"]),
                                        headers={"Referer": isrc}, params=params)
                                    if ar and not ar.json().get("error"):
                                        src = ar.json().get("url")
                                except Exception:
                                    pass
            events[key] = _mk_entry(src, cfg["base"], sport, name, link=link)
    WC_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: TimStreams
# ============================================================
TIM_TAG = "TIMSTRM"
TIM_BASE = "https://timst.top"
TIM_CACHE = Cache(TIM_TAG, exp=7200)
TIM_API = Cache(f"{TIM_TAG}-api", exp=19800)


async def timstreams_scrape() -> dict:
    events: dict = {}
    cached = TIM_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    now = Time.rn()
    api_data = TIM_API.load(per_entry=False)
    if not api_data:
        rr = await network.request(urljoin(TIM_BASE, "api/live-upcoming"))
        if not rr:
            return events
        api_data = rr.json()
        api_data["timestamp"] = now.timestamp()
        TIM_API.write(api_data)

    start = now - timedelta(hours=3)
    end = now + timedelta(minutes=30)
    genres = {g["id"]: {0: g["name"], **{s["id"]: s["name"] for s in g.get("sub_categories", [])}}
              for g in api_data.get("genres", [])}

    num_ptrn = re.compile(r"var\s+_(\w+)=\[([^\]]*)\],", re.S)
    idx_ptrn = re.compile(r"(_[a-z]+\d+)=(\d+)")
    m3u_ptrn = re.compile(r'(var\s?signed_)?url\s?=\s?"(.*)";', re.I)

    for ev in api_data.get("events") or []:
        try:
            name = ev["name"]; genre = ev["genre"]; sub = ev["sub_genre"]
            etime = ev["time"]; streams = ev["streams"]
            if 17 <= genre <= 18:
                continue
            ed = Time.from_str(etime, tz_name="EST")
            sport = genres.get(genre, {}).get(sub, "Live Event")
            if not (start <= ed <= end):
                continue
            surl = streams[0].get("url")
            if not surl:
                continue
            key = f"[{sport}] {name} ({TIM_TAG})"
            if key in events:
                continue
            rr = await network.request(surl, headers={"Referer": TIM_BASE})
            src = None
            if rr:
                nums = num_ptrn.findall(rr.text)
                idxs = idx_ptrn.findall(rr.text)
                if nums and idxs:
                    nl = (int(n.strip()) for n in nums[-1][-1].split(","))
                    if len(idxs) > 2: del idxs[-1]
                    x, y = (int(i[-1].strip()) for i in idxs)
                    js = "".join(chr(((i ^ x) - y + 256) & 255) for i in nl)
                    mm = m3u_ptrn.search(js)
                    if mm:
                        src = json.loads(f'"{mm[2]}"')
            events[key] = _mk_entry(src, surl, sport, name, logo=ev.get("logo"), link=surl)
        except Exception:
            continue
    TIM_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: OvoStream
# ============================================================
OVO_TAG = "OVO"
OVO_BASE = "https://ovostream.net/"
OVO_CACHE = Cache(OVO_TAG, exp=28800)


async def ovostream_scrape() -> dict:
    events: dict = {}
    cached = OVO_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    r = await network.request(f"{OVO_BASE}?")
    if not r:
        return events
    soup = HTMLParser(r.content)
    ptrn = re.compile(r'var\s?sourceurl\s?=\s?"(.*)";', re.I)
    for card in soup.css(".card"):
        watch = card.css_first("a.watch-btn")
        if not watch or not (href := watch.attributes.get("href")):
            continue
        teams = [i.text(strip=True) for i in card.css(".team-name") if i]
        if not teams:
            continue
        sport_el = card.css_first(".sport-tag")
        sport = sport_el.text(strip=True).upper() if sport_el and len(sport_el.text(strip=True)) <= 4 else (sport_el.text(strip=True).capitalize() if sport_el else "Live Event")
        name = teams[0] if len(teams) == 1 else " vs ".join(i.strip() for i in teams)
        link = urljoin(OVO_BASE, href)
        key = f"[{sport}] {name} ({OVO_TAG})"
        if key in events:
            continue
        rr = await network.request(link, headers={"Referer": OVO_BASE})
        src = None; ifr = None
        if rr:
            s2 = HTMLParser(rr.content)
            box = s2.css_first(".player-box > iframe")
            if box and (isrc := box.attributes.get("src")):
                ifr = isrc
                rr2 = await network.request(isrc, headers={"Referer": link})
                m = ptrn.search(rr2.text) if rr2 else None
                src = m[1] if m else None
        events[key] = _mk_entry(src, ifr or link, sport, name, link=link)
    OVO_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: EmbedSport
# ============================================================
EMB_TAG = "EMBEDSPRT"
EMB_BASE = "https://embedsport.live/"
EMB_CACHE = Cache(EMB_TAG, exp=10800)
EMB_HTML = Cache(f"{EMB_TAG}-html", exp=28800)


async def embedsport_scrape() -> dict:
    events: dict = {}
    cached = EMB_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    now = Time.rn()
    html_data = EMB_HTML.load(per_entry=False)
    if not html_data:
        r = await network.request(EMB_BASE)
        if not r:
            return events
        soup = HTMLParser(r.content)
        events_raw = {}
        for card in soup.css(".stream-card"):
            try:
                sport = card.attributes.get("data-category")
                ets = card.attributes.get("data-start")
                enc = card.attributes.get("data-servers")
                if not all([sport, ets, enc]) or sport.lower() == "24/7 streams":
                    continue
                ed = Time.from_ts(int(ets))
                if ed.date() != now.date():
                    continue
                ne = card.css_first(".leading-tight")
                if not ne:
                    continue
                name = ne.text(strip=True)
                info = json.loads(base64.b64decode(enc).decode())
                eid = info[0].get("encoded_id")
                if not eid:
                    continue
                events_raw[f"[{sport}] {name} ({EMB_TAG})"] = {
                    "sport": sport, "name": name, "event_id": eid,
                    "event_ts": ed.timestamp(), "timestamp": now.timestamp(),
                }
            except Exception:
                continue
        html_data = {"timestamp": now.timestamp(), "events": events_raw}
        EMB_HTML.write(html_data)

    start = (now - timedelta(minutes=30)).timestamp()
    end = (now + timedelta(minutes=30)).timestamp()
    ptrn = re.compile(r'const\s+stream\s+=\s+"([^"]*)"', re.I)

    for key, v in html_data.get("events", {}).items():
        if key in events:
            continue
        if not (start <= v["event_ts"] <= end or v["event_ts"] == 0):
            continue
        rr = await network.request(
            "https://embedfootball.site/ppv/",
            params={"id": v["event_id"]},
            headers={"Referer": EMB_BASE})
        src = None; ifr = None
        if rr:
            m = ptrn.search(rr.text)
            if m:
                src = m[1]; ifr = str(rr.url)
        events[key] = _mk_entry(src, ifr or EMB_BASE, v["sport"], v["name"], link=ifr)
    EMB_CACHE.write(events)
    return events


# ============================================================
# SCRAPER: Sportspass + WatchFooty (Playwright) — đặt trong orchestrator
# ============================================================
SPRP_TAG = "SPRTSPASS"
SPRP_BASE = "https://streamseast.eu"
SPRP_CACHE = Cache(SPRP_TAG, exp=10800)
# Mới — chỉ soccer (streamseast.eu có path /soccer)
SPRP_SPORTS = ["Soccer"]


async def _sprp_process(page, url: str, n: int) -> tuple[str | None, str | None, str | None]:
    captured: list[str] = []
    got = asyncio.Event()
    m3u_ptrn = re.compile(r"^(?!.*(?:knitcdn|jwpltx)).*\.m3u8", re.I)

    def on_req(req):
        if m3u_ptrn.search(req.url):
            captured.append(req.url)
            got.set()

    page.on("request", on_req)
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=8000)
        if not resp or resp.status != 200:
            return None, None, None
        name = "Sporting Event"
        try:
            name = await page.locator("h1.match-head").inner_text(timeout=1500)
        except Exception:
            pass
        try:
            ifr = page.locator("iframe.embed-responsive-item")
            await ifr.wait_for(timeout=1500)
            isrc = await ifr.get_attribute("src")
        except Exception:
            return name, None, None
        await page.goto(isrc, wait_until="domcontentloaded", timeout=3000)
        try:
            await asyncio.wait_for(got.wait(), timeout=6)
        except asyncio.TimeoutError:
            return name, isrc, None
        if captured:
            if "indianservers" in captured[0].lower():
                return name, isrc, None
            return name, isrc, captured[0]
    except Exception:
        return None, None, None
    finally:
        try: page.remove_listener("request", on_req)
        except Exception: pass


async def sportspass_scrape(browser) -> dict:
    events: dict = {}
    cached = SPRP_CACHE.load()
    events.update({k: v for k, v in cached.items() if v.get("source")})

    now = Time.rn()
    start = now - timedelta(hours=3)
    end = now + timedelta(minutes=5)
    date_ptrn = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z", re.I)

    for sp in SPRP_SPORTS:
        r = await network.request(urljoin(SPRP_BASE, sp.lower()))
        if not r:
            continue
        soup = HTMLParser(r.content)
        for ev in soup.css("a.matches"):
            href = ev.attributes.get("href")
            if not href:
                continue
            link = urljoin(SPRP_BASE, href)
            sc = ev.css_first("script")
            ed = None
            if sc and (mm := date_ptrn.search(sc.text(strip=True))):
                ed = Time.fromisoformat(mm[0]).astimezone(timezone.utc)
            elif ev.css_first("span.status-badge.badge.bg-success"):
                ed = now
            if not ed or not (start <= ed <= end):
                continue
            key = f"[{sp}] {href.split('/')[-1]} ({SPRP_TAG})"
            if key in events:
                continue

            ctx = await browser.new_context(user_agent=Network.UA)
            page = await ctx.new_page()
            try:
                name, ifr, src = await _sprp_process(page, link, 1)
                events[key] = _mk_entry(src, ifr or SPRP_BASE, sp, name or href, link=link)
            finally:
                await page.close()
                await ctx.close()
    SPRP_CACHE.write(events)
    return events


# ============================================================
# Tennis-specific passthrough: lọc các entry sport chứa "tennis"
# ============================================================
def filter_tennis(events: dict) -> dict:
    return {k: v for k, v in events.items()
            if re.search(r"tennis|atp|wta|roland|wimbledon|us open|australian open",
                         k, re.I)}


# ============================================================
# Run all
# ============================================================
async def run_all_scrapers(browser=None) -> dict:
    tasks = [
        xyzstreams_scrape(),
        fawa_scrape(),
        pelotalibre_scrape(),
        streamtp_scrape(),
        streamxhd_scrape(),
        streamfree_scrape(),
        streamgate_scrape(),
        tvf90_scrape(),
        # mainportal_scrape(),
        reedstreams_scrape(),
        dami_scrape(),
        flyembed_scrape(),
        istreameast_scrape(),
        streamcenter_scrape(),
        # webcast_scrape(),
        timstreams_scrape(),
        ovostream_scrape(),
        embedsport_scrape(),
    ]
    if browser is not None:
        tasks.append(sportspass_scrape(browser))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    combined: dict = {}
    for r in results:
        if isinstance(r, dict):
            combined.update(r)
    return combined
