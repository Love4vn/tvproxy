"""
🎯 SĂN LINK BÓNG ĐÁ - Xoilac + Gavang + ColaTV
- Lấy TẤT CẢ server con (ROY/HD ROY/FABIO/CRIS/Giàng A Dân...)
- Chỉ lấy Bóng đá (top 5 giải) + Tennis
- Tự động thêm #EXTVLCOPT cho M3U
"""
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

# ==========================================
# CẤU HÌNH CHUNG
# ==========================================
PROXY = {
    "server": "http://14.241.72.139:10906",
    "username": "hieumx",
    "password": "hieu123",
}

MAX_RETRIES = 3
DOMAIN_TIMEOUT = 12000
STREAM_WAIT_TRIES = 40          # ~10s chờ stream cho mỗi nút
STREAM_WAIT_STEP_MS = 250

# Chỉ lấy bóng đá top 5 giải. Đặt False để lấy mọi bóng đá.
REQUIRE_TOP_LEAGUE_ONLY = True

# ==========================================
# DANH SÁCH SERVER
# ==========================================
TAT_CA_SERVER = [
    ("Xoilac", "https://xoilacz.io",    "/truc-tiep/", "xoilac"),
    ("Gavang", "https://gavanglink.co", "/truc-tiep/", "gavang"),
    ("ColaTV", "https://colatv77.live", "",            "colatv"),
]

XOILAC_DOMAINS = [
    "https://xoilacz.io",
    "https://xoilaczzf.cc",
    "https://xoilacxth.tv",
    "https://xoilac.cfd",
    "https://xoilactv.pro",
    "https://xoilac7.tv",
]

COLATV_DOMAINS = [
    "https://colatv77.live",
    # Thêm domain dự phòng nếu bạn biết
    # "https://colatv.tv",
    # "https://colatv.live",
]

# ==========================================
# MAP MÔN THỂ THAO
# ==========================================
SPORT_MAP = {
    "football": "Bóng đá",
    "tennis": "Tennis",
    "bóng đá": "Bóng đá",
    "quần vợt": "Tennis",
}

SPORT_NORMALIZE = {
    "football": "football", "bóng đá": "football", "bong da": "football",
    "tennis": "tennis", "quần vợt": "tennis", "quan vot": "tennis",
}

TENNIS_KEYWORDS = ["tennis", "quần vợt", "atp", "wta", "grand slam"]

ALLOWED_LEAGUES = {
    "premier league", "ngoại hạng anh", "epl",
    "bundesliga", "đức",
    "serie a", "seria a", "ý",
    "ligue 1", "ligue1", "pháp",
    "la liga", "laliga", "tây ban nha",
}

# ==========================================
# HEADER TỰ ĐỘNG CHO M3U
# ==========================================
REFERER_MAP = {
    "quickscoreboardz.com":     "https://live1.quickscoreboardz.com/",
    "zundrixmediapipeline.com": "https://live2.zundrixmediapipeline.com/",
    "domainkqt.cc":             "https://xl365.domainkqt.cc/",
    "api-score.com":            "https://animation.api-score.com/",
    "edgenextcdn.net":          None,
}

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")


# ==========================================
# HELPERS
# ==========================================
def normalize_sport(s):
    if not s:
        return ""
    return SPORT_NORMALIZE.get(s.lower().strip(), "")


def detect_sport(name="", sport_hint=""):
    hint = (sport_hint or "").lower().strip()
    if hint in ("football", "bóng đá", "soccer"):
        return "football"
    if hint in ("tennis", "quần vợt"):
        return "tennis"
    name_lower = (name or "").lower()
    for kw in TENNIS_KEYWORDS:
        if kw in name_lower:
            return "tennis"
    return ""


def contains_top_league(text):
    if not text:
        return False
    t = text.lower()
    return any(league in t for league in ALLOWED_LEAGUES)


def should_keep(name, sport_hint="", container_text=""):
    sport = detect_sport(name, sport_hint)
    if sport == "tennis":
        return True
    if not REQUIRE_TOP_LEAGUE_ONLY:
        return sport in ("football", "")
    return contains_top_league(f"{name} {container_text}")


def build_extvlc_headers(stream_url: str) -> str:
    """Sinh #EXTVLCOPT phù hợp dựa vào domain CDN."""
    if not stream_url:
        return ""
    domain = urlparse(stream_url).netloc.lower()
    headers = []

    for key, ref in REFERER_MAP.items():
        if key in domain:
            referer = ref or f"https://{domain}/"
            headers.append(f"#EXTVLCOPT:http-referrer={referer}")
            headers.append(f"#EXTVLCOPT:http-origin={referer}")
            break

    headers.append(f"#EXTVLCOPT:http-user-agent={DEFAULT_UA}")
    return "\n".join(headers)


# ==========================================
# HÀM LÕI
# ==========================================
def san_full_server_qua_proxy():
    print("🚀 BẮT ĐẦU QUÉT (Xoilac + Gavang + ColaTV)", flush=True)
    print(f"   → Chỉ lấy: Bóng đá (top 5 giải) + Tennis", flush=True)
    print(f"   → Lấy TẤT CẢ server con (ROY/HD ROY/CRIS/Giàng A Dân...)", flush=True)

    danh_sach_phat = []
    server_da_thanh_cong = set()

    for lan_thu in range(1, MAX_RETRIES + 1):
        print(f"\n==========================================", flush=True)
        print(f"🔄 VÒNG QUÉT {lan_thu}/{MAX_RETRIES}", flush=True)
        print(f"==========================================", flush=True)

        server_can_quet = [s for s in TAT_CA_SERVER if s[0] not in server_da_thanh_cong]
        if not server_can_quet:
            print("✅ Tất cả server đã quét xong!", flush=True)
            break

        print(f"📋 Cần quét: {', '.join(s[0] for s in server_can_quet)}", flush=True)
        so_tram_loi_vong_nay = 0
        so_tram_ok_vong_nay = 0

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    proxy=PROXY,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                    ],
                )
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=DEFAULT_UA,
                    locale="vi-VN",
                )
                context.set_default_timeout(15000)
                context.set_default_navigation_timeout(DOMAIN_TIMEOUT)

                # Stealth
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                    Object.defineProperty(navigator, 'languages',
                        {get: () => ['vi-VN','vi','en-US','en']});
                """)

                def chan_tai_nguyen_thua(route):
                    if route.request.resource_type in ["image", "media"]:
                        route.abort()
                    else:
                        route.continue_()
                context.route("**/*", chan_tai_nguyen_thua)

                # ==========================================
                # LỌC DANH SÁCH PHÒNG
                # ==========================================
                def _loc_trung(danh_sach_raw, url_goc):
                    result = {}
                    for item in danh_sach_raw:
                        url = item.get('url', '')
                        ten = item.get('ten', '').strip()
                        sport = item.get('sport', '')
                        container_text = item.get('container', '')

                        if not url or url == url_goc or url == url_goc + "/":
                            continue
                        if not should_keep(ten, sport, container_text):
                            continue

                        if url not in result or len(ten) > len(result.get(url, {}).get('ten', '')):
                            result[url] = {
                                'ten': ten if ten else "Trận đấu đang chờ cập nhật",
                                'thumb': item.get('thumb',
                                                  'https://img.icons8.com/color/512/football2.png'),
                                'sport': detect_sport(ten, sport) or sport,
                            }
                    return result

                def lay_phong_xoilac(page, url_goc, keyword_link):
                    raw = page.evaluate(f"""
                        (() => {{
                            const results = [];
                            document.querySelectorAll('.grid-matches__item').forEach(item => {{
                                const sport = item.getAttribute('data-sport') || 'football';
                                const linkEl = item.querySelector('a[href*="{keyword_link}"]');
                                if (!linkEl) return;
                                const img = item.querySelector('img');
                                results.push({{
                                    url: linkEl.href,
                                    ten: linkEl.getAttribute('title') || linkEl.innerText.trim().replace(/\\n/g, ' - '),
                                    thumb: img ? img.src : "",
                                    sport: sport,
                                    container: item.innerText || ""
                                }});
                            }});
                            document.querySelectorAll('.match-horizontals-item[href*="{keyword_link}"]').forEach(a => {{
                                if (results.some(r => r.url === a.href)) return;
                                const img = a.querySelector('img');
                                results.push({{
                                    url: a.href,
                                    ten: a.innerText.trim().replace(/\\n/g, ' - '),
                                    thumb: img ? img.src : "",
                                    sport: 'football',
                                    container: (a.closest('.match-horizontals') || a.parentElement || a).innerText || ""
                                }});
                            }});
                            return results;
                        }})()
                    """)
                    return _loc_trung(raw, url_goc)

                def lay_phong_gavang(page, url_goc):
                    raw = page.evaluate("""
                        (() => {
                            const results = [];
                            document.querySelectorAll('.match-card').forEach(card => {
                                const sport = card.getAttribute('data-sport') || 'football';
                                const linkEl = card.querySelector('a[class*="absolute"]')
                                              || card.querySelector('a');
                                if (!linkEl) return;
                                const href = linkEl.getAttribute('href') || '';
                                if (!href || href === '/' || href === '#') return;
                                const title = linkEl.getAttribute('data-title')
                                            || linkEl.getAttribute('data-tooltip') || '';
                                const imgs = card.querySelectorAll('img');
                                let thumb = '';
                                for (const img of imgs) {
                                    const src = img.getAttribute('src')
                                              || img.getAttribute('data-src') || '';
                                    if (src && !src.includes('flag')
                                        && src.includes('thesports')) { thumb = src; break; }
                                }
                                if (!thumb && imgs.length > 0)
                                    thumb = imgs[0].getAttribute('src') || '';
                                results.push({
                                    url: linkEl.href,
                                    ten: title || linkEl.innerText.trim().replace(/\\n/g, ' - '),
                                    thumb: thumb,
                                    sport: sport,
                                    container: card.innerText || ""
                                });
                            });
                            return results;
                        })()
                    """)
                    return _loc_trung(raw, url_goc)

                def lay_phong_colatv(page, url_goc):
                    """
                    ColaTV: React SPA - phải chờ render xong mới có DOM.
                    Quét mọi internal link có dấu hiệu tên trận.
                    """
                    # Chờ React render
                    page.wait_for_timeout(6000)

                    raw = page.evaluate("""
                        (() => {
                            const results = [];
                            const seen = new Set();
                            const NAV_PATTERN = /^(trang chủ|home|đăng nhập|đăng ký|login|register|menu|tìm kiếm|search|lịch thi đấu|kết quả|bảng xếp hạng|tin tức|liên hệ|giới thiệu|highlight|xem lại|video|live|trực tiếp)$/i;
                            const URL_BLACKLIST = /\\.(png|jpg|jpeg|gif|svg|ico|css|js|woff|woff2|ttf)$/i;

                            document.querySelectorAll('a[href]').forEach(a => {
                                const href = a.href || '';
                                if (!href) return;
                                if (href.startsWith('javascript:')) return;
                                if (href.startsWith('mailto:')) return;
                                if (href.startsWith('tel:')) return;
                                if (URL_BLACKLIST.test(href)) return;
                                if (href === location.href) return;
                                if (href === location.origin + '/' || href === location.origin) return;
                                if (!href.includes(location.hostname)) return;

                                const text = (a.innerText || a.textContent || '')
                                    .trim().replace(/\\s+/g, ' ');
                                if (!text || text.length < 5 || text.length > 200) return;
                                if (NAV_PATTERN.test(text)) return;

                                // Phải có dấu hiệu tên trận (vs, gặp, hoặc ít nhất 3 từ)
                                const hasVsMark = /\\bvs\\b|\\bgặp\\b|\\s-\\s/i.test(text);
                                const wordCount = text.split(' ').length;
                                if (!hasVsMark && wordCount < 3) return;

                                if (seen.has(href)) return;
                                seen.add(href);

                                const img = a.querySelector('img');
                                let thumb = '';
                                if (img) {
                                    thumb = img.getAttribute('src')
                                         || img.getAttribute('data-src')
                                         || img.getAttribute('data-lazy-src') || '';
                                }

                                let sport = 'football';
                                if (/tennis|quần vợt/i.test(text)) sport = 'tennis';

                                // Container text = cha gần nhất
                                const parent = a.closest(
                                    'li, article, .card, .item, [class*="match"], [class*="Match"], [class*="card"], [class*="item"]'
                                ) || a.parentElement;
                                const containerText = parent ? (parent.innerText || '') : text;

                                results.push({
                                    url: href,
                                    ten: text,
                                    thumb: thumb,
                                    sport: sport,
                                    container: containerText
                                });
                            });

                            return results;
                        })()
                    """)

                    # Debug nếu 0 kết quả
                    if not raw:
                        all_links = page.evaluate("""
                            Array.from(document.querySelectorAll('a[href]'))
                                .map(a => a.href)
                                .filter(h => h.includes(location.hostname))
                                .slice(0, 30)
                        """)
                        print(f"     🔍 Debug: {len(all_links)} internal links "
                              f"(chưa khớp filter). Mẫu: "
                              f"{all_links[:5]}", flush=True)

                    return _loc_trung(raw, url_goc)

                # ==========================================
                # DÒ NÚT SERVER (generic)
                # ==========================================
                def detect_server_buttons(page):
                    return page.evaluate("""
                        () => {
                            const btns = [];
                            const seen = new Set();

                            // 1) Xoilac style
                            document.querySelectorAll('#tv_links a.player-link').forEach(a => {
                                const label = (a.innerText || '').trim().split('\\n').pop().trim();
                                const key = 'tv-' + (a.getAttribute('data-link') || '');
                                if (seen.has(key)) return;
                                seen.add(key);
                                btns.push({
                                    idx: a.getAttribute('data-link') || '0',
                                    label: label || ('Server ' + btns.length),
                                    selector: '#tv_link_' + (a.getAttribute('data-link') || '0')
                                });
                            });
                            if (btns.length > 0) return btns;

                            // 2) Fallback: quét trong vùng player
                            const zones = document.querySelectorAll(
                                '.tv-servers, .player-servers, .server-list, ' +
                                '.list-server, .tab-server, .tv-links, #tv_links, ' +
                                '[class*="server"], [class*="Server"], ' +
                                '[class*="player-link"], [class*="PlayerLink"], ' +
                                '[class*="list-link"], [class*="link-server"], ' +
                                '[class*="btn-link"], [class*="btnLink"]'
                            );

                            let scanRoot = null;
                            for (const z of zones) {
                                if (z.querySelectorAll('a, button, div[role="button"], li').length > 0) {
                                    scanRoot = z;
                                    break;
                                }
                            }
                            const root = scanRoot || document;

                            const elements = root.querySelectorAll(
                                'a, button, div[role="button"], li[role="button"], li a, li button'
                            );

                            elements.forEach((el, i) => {
                                if (el.querySelector('iframe, video')) return;
                                const label = (el.innerText || el.textContent || '')
                                              .trim().split('\\n')[0].trim();
                                if (!label || label.length > 40) return;
                                if (/trang chủ|đăng nhập|đăng ký|menu|tìm kiếm|search|home|logo/i.test(label))
                                    return;
                                if (/^(play|pause|mute|volume|fullscreen|\\d+)$/i.test(label)) return;

                                const key = 'gen-' + label + '-' + i;
                                if (seen.has(key)) return;
                                seen.add(key);

                                el.setAttribute('data-ext-btn', String(i));
                                btns.push({
                                    idx: String(i),
                                    label: label,
                                    selector: `[data-ext-btn="${i}"]`
                                });
                            });

                            return btns.slice(0, 20);
                        }
                    """)

                # ==========================================
                # LẤY TẤT CẢ SERVER CON
                # ==========================================
                def lay_tat_ca_server_con(page, link_phong):
                    streams = []
                    seen_urls = set()

                    try:
                        page.goto(link_phong, timeout=20000, wait_until="domcontentloaded")

                        # ColaTV là SPA -> chờ React render
                        page.wait_for_timeout(3000)

                        # Đóng popup
                        try:
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(300)
                            for sel in ['.close', '.closebtn', '[aria-label="Close"]',
                                        '.modal-close', '.popup-close']:
                                try:
                                    page.locator(sel).first.click(timeout=700)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        try:
                            page.wait_for_selector(
                                'iframe, video, xg-player, #tv_links, .tv-servers, [class*="server"]',
                                timeout=8000
                            )
                        except Exception:
                            pass
                        page.wait_for_timeout(2000)

                        buttons = detect_server_buttons(page)
                        if not buttons:
                            buttons = [{'idx': '0', 'label': 'Server 1', 'selector': 'body'}]

                        print(f"     📺 {len(buttons)} server con: "
                              f"{[b['label'] for b in buttons]}", flush=True)

                        for btn in buttons:
                            target_url = [None]

                            def handle(req):
                                if target_url[0]:
                                    return
                                u = req.url.lower()
                                if ".m3u8" in u or ".flv" in u or ".mpd" in u:
                                    target_url[0] = req.url

                            page.on("request", handle)
                            try:
                                try:
                                    page.click(btn['selector'], timeout=5000)
                                except Exception:
                                    try:
                                        page.get_by_text(btn['label'], exact=False)\
                                            .first.click(timeout=5000)
                                    except Exception:
                                        pass

                                for _ in range(STREAM_WAIT_TRIES):
                                    if target_url[0]:
                                        break
                                    page.wait_for_timeout(STREAM_WAIT_STEP_MS)

                                # Nếu chưa có -> click giữa player (XGPlayer thường cần click)
                                if not target_url[0]:
                                    try:
                                        page.mouse.click(960, 500)
                                    except Exception:
                                        pass
                                    for _ in range(20):
                                        if target_url[0]:
                                            break
                                        page.wait_for_timeout(STREAM_WAIT_STEP_MS)
                            except Exception as e:
                                print(f"        ⚠️ [{btn['label']}] lỗi click: "
                                      f"{str(e)[:60]}", flush=True)
                            finally:
                                page.remove_listener("request", handle)

                            if target_url[0] and target_url[0] not in seen_urls:
                                seen_urls.add(target_url[0])
                                streams.append({"label": btn["label"],
                                                "url": target_url[0]})
                                print(f"        ✅ [{btn['label']}] "
                                      f"{target_url[0][:75]}", flush=True)
                            else:
                                print(f"        ⛔ [{btn['label']}] không bắt được stream",
                                      flush=True)

                    except Exception as e:
                        print(f"     ⚠️ Lỗi extract streams: {str(e)[:80]}", flush=True)

                    return streams

                # ==========================================
                # QUÉT 1 SERVER
                # ==========================================
                def quet_trang(ten_nhom, url_trang_chu, keyword_link, kieu_quet=""):
                    nonlocal so_tram_loi_vong_nay, so_tram_ok_vong_nay
                    page = context.new_page()
                    print(f"\n📥 QUÉT SERVER: {ten_nhom.upper()}", flush=True)
                    ket_qua_tram = []

                    try:
                        if kieu_quet == "xoilac":
                            domains = XOILAC_DOMAINS
                        elif kieu_quet == "colatv":
                            domains = COLATV_DOMAINS
                        else:
                            domains = [url_trang_chu]

                        url_dung = None
                        for domain in domains:
                            try:
                                print(f"   🔗 Thử: {domain}", flush=True)
                                page.goto(domain, timeout=DOMAIN_TIMEOUT,
                                          wait_until="domcontentloaded")
                                title = (page.title() or "").lower()
                                if "just a moment" in title or "checking your browser" in title:
                                    print(f"   🛡️ Cloudflare challenge", flush=True)
                                    continue

                                if kieu_quet == "gavang":
                                    page.wait_for_function(
                                        "document.querySelectorAll('.match-card').length > 0",
                                        timeout=DOMAIN_TIMEOUT)
                                elif kieu_quet == "colatv":
                                    # SPA: chờ React render + có ít nhất vài link
                                    page.wait_for_function(
                                        "document.querySelectorAll('a[href]').length > 5",
                                        timeout=DOMAIN_TIMEOUT)
                                    page.wait_for_timeout(4000)  # Đợi API match list
                                else:
                                    page.wait_for_function(
                                        f"document.querySelectorAll('a[href*=\"{keyword_link}\"]').length > 0",
                                        timeout=DOMAIN_TIMEOUT)
                                url_dung = domain
                                print(f"   ✅ Sống: {domain}", flush=True)
                                break
                            except Exception as e:
                                print(f"   ❌ Chết: {domain} | {str(e)[:80]}", flush=True)
                                continue

                        if not url_dung:
                            raise Exception("Tất cả domain đều chết!")

                        page.wait_for_timeout(1500)

                        if kieu_quet == "xoilac":
                            danh_sach_phong = lay_phong_xoilac(page, url_dung, keyword_link)
                        elif kieu_quet == "gavang":
                            danh_sach_phong = lay_phong_gavang(page, url_dung)
                        elif kieu_quet == "colatv":
                            danh_sach_phong = lay_phong_colatv(page, url_dung)
                        else:
                            danh_sach_phong = {}

                        print(f"🎯 {ten_nhom}: {len(danh_sach_phong)} phòng (đã lọc giải)",
                              flush=True)

                        for stt, (link_phong, data_phong) in enumerate(danh_sach_phong.items(), 1):
                            ten_tran = data_phong['ten']
                            anh_thumb = data_phong['thumb']
                            sport_key = data_phong.get('sport', '')

                            mon_vn = SPORT_MAP.get(normalize_sport(sport_key), "Bóng đá")
                            nhom_m3u = f"{ten_nhom} - {mon_vn}"

                            print(f"\n   [{stt}/{len(danh_sach_phong)}] {ten_tran[:70]}",
                                  flush=True)

                            streams = lay_tat_ca_server_con(page, link_phong)
                            for s in streams:
                                ket_qua_tram.append({
                                    'nhom': nhom_m3u,
                                    'ten': f"{ten_tran} [{s['label']}]",
                                    'link': s['url'],
                                    'thumb': anh_thumb,
                                    'server': s['label'],
                                    'tran': ten_tran,
                                })

                        so_tram_ok_vong_nay += 1
                        server_da_thanh_cong.add(ten_nhom)
                        danh_sach_phat.extend(ket_qua_tram)
                        print(f"\n✅ {ten_nhom}: {len(ket_qua_tram)} luồng!", flush=True)

                    except Exception as e:
                        error_msg = str(e)
                        print(f"⚠️ Lỗi {ten_nhom}: {error_msg[:120]}", flush=True)
                        so_tram_loi_vong_nay += 1
                        if any(x in error_msg for x in
                               ("ERR_CONNECTION_RESET", "ERR_PROXY_CONNECTION_FAILED",
                                "ERR_TIMED_OUT", "ERR_TUNNEL_CONNECTION_FAILED")):
                            return "PROXY_DEAD"
                    finally:
                        page.close()
                    return "OK"

                for ten_nhom, url_tc, keyword, kieu_quet in server_can_quet:
                    status = quet_trang(ten_nhom, url_tc, keyword, kieu_quet)
                    if status == "PROXY_DEAD":
                        print("🚫 Proxy chết! Đổi IP mới...", flush=True)
                        break

                browser.close()
        except Exception as e:
            print(f"🔥 Lỗi hệ thống: {e}", flush=True)

        print(f"\n📊 Vòng {lan_thu}: ✅ {so_tram_ok_vong_nay} OK, "
              f"❌ {so_tram_loi_vong_nay} fail", flush=True)
        print(f"📊 Tích lũy: {len(danh_sach_phat)} luồng "
              f"từ {len(server_da_thanh_cong)}/{len(TAT_CA_SERVER)} server", flush=True)

        if so_tram_ok_vong_nay == 0 and so_tram_loi_vong_nay > 0 and lan_thu < MAX_RETRIES:
            print("⚠️ Proxy xịt. Ngủ 30s...", flush=True)
            time.sleep(30)
            continue

        if len(server_da_thanh_cong) < len(TAT_CA_SERVER) and lan_thu < MAX_RETRIES:
            con_lai = [s[0] for s in TAT_CA_SERVER if s[0] not in server_da_thanh_cong]
            print(f"🔄 Còn: {', '.join(con_lai)} – ngủ 30s...", flush=True)
            time.sleep(30)
            continue

        print("🏆 Quét xong toàn bộ!", flush=True)
        break

    # ==========================================
    # LỌC TRÙNG & XUẤT M3U
    # ==========================================
    seen = set()
    danh_sach_sach = []
    for luong in danh_sach_phat:
        if luong['link'] not in seen:
            seen.add(luong['link'])
            danh_sach_sach.append(luong)

    if danh_sach_sach:
        da_loc = len(danh_sach_phat) - len(danh_sach_sach)
        if da_loc > 0:
            print(f"🧹 Đã lọc {da_loc} link trùng.", flush=True)

        print(f"\n📦 Đang ghi M3U...", flush=True)
        with open("tong_hop_bong_da.m3u", "w", encoding="utf-8") as file:
            file.write("#EXTM3U\n")
            for luong in danh_sach_sach:
                file.write(f'#EXTINF:-1 group-title="{luong["nhom"]}" '
                           f'tvg-logo="{luong["thumb"]}", '
                           f'⚽ {luong["ten"]}\n')

                ext_headers = build_extvlc_headers(luong['link'])
                if ext_headers:
                    file.write(ext_headers + "\n")

                file.write(f'{luong["link"]}\n')

        print(f"🎉 TỔNG CỘNG {len(danh_sach_sach)} TRẬN/LUỒNG!", flush=True)

        nhom_count = {}
        for l in danh_sach_sach:
            nhom_count[l['nhom']] = nhom_count.get(l['nhom'], 0) + 1
        print(f"📊 Chi tiết: {', '.join(f'{k}: {v}' for k, v in nhom_count.items())}",
              flush=True)

        server_count = {}
        for l in danh_sach_sach:
            srv = l.get('server', '') or '(mặc định)'
            server_count[srv] = server_count.get(srv, 0) + 1
        print(f"📺 Server con: {', '.join(f'{k}: {v}' for k, v in server_count.items())}",
              flush=True)
    else:
        print(f"❌ Không có luồng nào sau {MAX_RETRIES} lần thử!", flush=True)
        with open("tong_hop_bong_da.m3u", "w", encoding="utf-8") as file:
            file.write("#EXTM3U\n")


if __name__ == "__main__":
    san_full_server_qua_proxy()
