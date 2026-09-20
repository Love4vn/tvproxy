"""
🎯 SĂN LINK XOILAC - Lọc nam, nhiều giải, tự động click "XEM THÊM"
- Chỉ Xoilac (đã bỏ ColaTV, Gavang, Socolive)
- Lọc bỏ: Nữ, Trẻ (U*, Youth, Junior...)
- Mở rộng giải: C1/C2/C3, FIFA, Euro, Nations League, giao hữu châu Âu
- Tự động click "XEM THÊM" đến khi hết hoặc đến ngưỡng 24h
- Tự động thêm #EXTVLCOPT cho M3U
"""
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

# ==========================================
# CẤU HÌNH
# ==========================================
PROXY = {
    "server": "http://14.241.72.139:10906",
    "username": "hieumx",
    "password": "hieu123",
}

MAX_RETRIES = 3
DOMAIN_TIMEOUT = 12000
STREAM_WAIT_TRIES = 40
STREAM_WAIT_STEP_MS = 250

HOURS_AHEAD = 24            # Chỉ lấy trận trong vòng 24h tới
MAX_XEM_THEM_CLICKS = 15    # Trần số lần click XEM THÊM (an toàn)

# ==========================================
# SERVER (chỉ Xoilac)
# ==========================================
TAT_CA_SERVER = [
    ("Xoilac", "https://xoilacz.io", "/truc-tiep/", "xoilac"),
]

XOILAC_DOMAINS = [
    "https://xoilacz.io",
    "https://xoilaczzf.cc",
    "https://xoilacxth.tv",
    "https://xoilaczzb.cc",
    "https://xoilac7tv.tv",
    "https://xoilacvvr.tv",
]

# ==========================================
# LỌC GIẢI
# ==========================================
# ---- BLACKLIST: loại bỏ Nữ / Trẻ / Dự bị ----
EXCLUDE_KEYWORDS = [
    # Nữ
    r"\bnữ\b", r"\bnu\b", r"\bwomen\b", r"\bfemale\b", r"\bw\b",
    r"ladies", r"damen", r"feminine", r"femenil", r"feminino",
    # Trẻ / U
    r"\bu\d{2}\b", r"\bu-\d{2}\b", r"\bunder\s*\d{2}\b",
    r"\byouth\b", r"\bjunior\b", r"\btrẻ\b", r"\btre\b",
    r"\breserve\b", r"\bb\s*team\b", r"\bđội\s*b\b",
    r"\bacademy\b", r"\bhọc\s*viện\b", r"\bhlv\b.*\bu\d",
]

# ---- WHITELIST: chỉ giữ các giải nam hàng đầu ----
ALLOWED_LEAGUES = {
    # Top 5 châu Âu
    "premier league", "ngoại hạng anh", "epl",
    "bundesliga", "đức",
    "serie a", "seria a", "ý",
    "ligue 1", "ligue1", "pháp",
    "la liga", "laliga", "tây ban nha",

    # Cúp châu Âu
    "champions league", "cúp c1", "c1", "ucl",
    "europa league", "cúp c2", "c2", "uel",
    "conference league", "cúp c3", "c3", "uecl",
    "siêu cúp châu âu", "super cup",

    # ĐTQG
    "world cup", "fifa world cup", "worldcup",
    "euro", "euro 20", "uefa euro", "euro championship",
    "nations league", "uefa nations league",

    # Giao hữu quốc tế (châu Âu)
    "giao hữu", "friendly", "international friendly",

    # Cúp quốc gia top 5 (mở rộng)
    "fa cup", "carabao cup", "efl cup", "league cup",
    "dfb pokal", "coppa italia", "coupe de france", "copa del rey",
}

# ---- Các quốc gia châu Âu (dùng cho giao hữu) ----
EURO_COUNTRIES = {
    "anh", "england", "đức", "germany", "pháp", "france",
    "ý", "italy", "tây ban nha", "spain", "bồ đào nha", "portugal",
    "hà lan", "netherlands", "bỉ", "belgium", "thụy sĩ", "switzerland",
    "áo", "austria", "đan mạch", "denmark", "thụy điển", "sweden",
    "na uy", "norway", "phần lan", "finland", "ba lan", "poland",
    "croatia", "serbia", "scotland", "wales", "ireland", "cộng hòa séc",
    "czech", "slovakia", "slovenia", "hungary", "romania", "bulgaria",
    "hy lạp", "greece", "thổ nhĩ kỳ", "turkey", "ukraine", "nga",
}

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

# ==========================================
# HEADER TỰ ĐỘNG
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


def is_excluded(name):
    """True nếu là giải Nữ / Trẻ."""
    if not name:
        return False
    t = name.lower()
    for pat in EXCLUDE_KEYWORDS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


def contains_top_league(text):
    if not text:
        return False
    t = text.lower()
    return any(league in t for league in ALLOWED_LEAGUES)


def has_euro_country(text):
    """Kiểm tra text có chứa tên quốc gia châu Âu (cho giao hữu)."""
    if not text:
        return False
    t = text.lower()
    return any(c in t for c in EURO_COUNTRIES)


def is_friendly(text):
    """Phát hiện trận giao hữu."""
    if not text:
        return False
    t = text.lower()
    return any(kw in t for kw in ("giao hữu", "friendly", "friendlies"))


def should_keep(name, sport_hint="", container_text=""):
    """
    Quy tắc:
    - Tennis: luôn giữ
    - Bóng đá: PHẢI thoả (a) không phải Nữ/Trẻ, (b) thuộc whitelist HOẶC
      (giao hữu + có quốc gia châu Âu)
    """
    sport = detect_sport(name, sport_hint)

    # Tennis: luôn giữ
    if sport == "tennis":
        return True

    combined = f"{name} {container_text}"

    # Bóng đá: loại Nữ/Trẻ trước
    if is_excluded(combined):
        return False

    # Whitelist giải
    if contains_top_league(combined):
        return True

    # Giao hữu châu Âu
    if is_friendly(combined) and has_euro_country(combined):
        return True

    return False


def parse_match_datetime(text):
    """
    Trích xuất 'HH:MM - DD/MM' từ text.
    Trả về datetime hoặc None.
    """
    if not text:
        return None
    # Pattern: "20:30 - 20/09"
    m = re.search(r'(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2})/(\d{1,2})', text)
    if not m:
        return None
    hh, mm, dd, mo = map(int, m.groups())
    now = datetime.now()
    try:
        dt = datetime(now.year, mo, dd, hh, mm)
        # Nếu ngày đã qua (ví dụ hôm qua) -> cộng 1 năm
        if dt < now - timedelta(days=1):
            dt = dt.replace(year=now.year + 1)
        return dt
    except ValueError:
        return None


def is_within_24h(text):
    """True nếu thời gian <= now + 24h. Nếu không parse được -> coi như OK."""
    dt = parse_match_datetime(text)
    if dt is None:
        return True
    return dt <= datetime.now() + timedelta(hours=HOURS_AHEAD)


def build_extvlc_headers(stream_url: str) -> str:
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
    print("🚀 BẮT ĐẦU QUÉT XOILAC", flush=True)
    print(f"   → Chỉ Bóng đá NAM + top giải mở rộng", flush=True)
    print(f"   → Loại bỏ: Nữ, Trẻ (U*, Youth, Junior...)", flush=True)
    print(f"   → Cửa sổ thời gian: {HOURS_AHEAD}h tới", flush=True)
    print(f"   → Tự động click 'XEM THÊM' (max {MAX_XEM_THEM_CLICKS} lần)", flush=True)

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

                        # Lọc Nữ / Trẻ / Whitelist
                        if not should_keep(ten, sport, container_text):
                            continue

                        # Lọc theo thời gian <= 24h
                        if not is_within_24h(container_text):
                            continue

                        if url not in result or len(ten) > len(result.get(url, {}).get('ten', '')):
                            result[url] = {
                                'ten': ten if ten else "Trận đấu",
                                'thumb': item.get('thumb',
                                                  'https://img.icons8.com/color/512/football2.png'),
                                'sport': detect_sport(ten, sport) or sport,
                            }
                    return result

                # ==========================================
                # CLICK "XEM THÊM"
                # ==========================================
                def click_xem_them_loop(page, max_clicks=MAX_XEM_THEM_CLICKS):
                    """
                    Click 'XEM THÊM' liên tục cho tới khi:
                    - Không tìm thấy nút
                    - Click mà count không tăng (hết data)
                    - Đã click đủ max_clicks
                    """
                    clicked = 0
                    for i in range(max_clicks):
                        # Đếm số match hiện tại
                        count_before = page.evaluate(
                            "document.querySelectorAll('.grid-matches__item, .match-horizontals-item').length"
                        )

                        # Tìm nút XEM THÊM (dò đa dạng selector)
                        btn_found = page.evaluate("""
                            () => {
                                const patterns = ['XEM THÊM', 'Xem thêm', 'XEM THÊM ', 'Tải thêm', 'Xem Thêm'];
                                const candidates = document.querySelectorAll(
                                    'button, a, div[role="button"], span[role="button"], .btn, [class*="load-more"], [class*="loadmore"], [class*="xem-them"]'
                                );
                                for (const el of candidates) {
                                    const t = (el.innerText || '').trim();
                                    if (patterns.includes(t) || /xem\\s*th[eê]m/i.test(t)) {
                                        // Kiểm tra còn visible không
                                        const rect = el.getBoundingClientRect();
                                        if (rect.width > 0 && rect.height > 0) {
                                            el.setAttribute('data-ext-xemthem', '1');
                                            return true;
                                        }
                                    }
                                }
                                return false;
                            }
                        """)

                        if not btn_found:
                            if i == 0:
                                print(f"     ℹ️ Không có nút XEM THÊM", flush=True)
                            else:
                                print(f"     ✅ Đã click {clicked} lần, hết nút", flush=True)
                            break

                        try:
                            page.click('[data-ext-xemthem="1"]', timeout=5000)
                        except Exception:
                            try:
                                page.get_by_text("XEM THÊM", exact=False).first.click(timeout=5000)
                            except Exception:
                                break

                        # Chờ data mới
                        try:
                            page.wait_for_function(
                                f"document.querySelectorAll('.grid-matches__item, .match-horizontals-item').length > {count_before}",
                                timeout=8000
                            )
                        except Exception:
                            print(f"     ⚠️ Click {i+1} không load thêm được gì -> dừng",
                                  flush=True)
                            break

                        count_after = page.evaluate(
                            "document.querySelectorAll('.grid-matches__item, .match-horizontals-item').length"
                        )
                        clicked += 1
                        print(f"     🔽 Click XEM THÊM #{clicked}: "
                              f"{count_before} → {count_after} trận", flush=True)

                        # Nếu count không tăng -> hết
                        if count_after <= count_before:
                            break

                        # Scroll xuống cuối để nút hiện lại (1 số web ẩn nút sau click)
                        try:
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            page.wait_for_timeout(500)
                        except Exception:
                            pass

                    return clicked

                # ==========================================
                # LẤY PHÒNG XOILAC
                # ==========================================
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

                # ==========================================
                # DÒ NÚT SERVER CON
                # ==========================================
                def detect_server_buttons(page):
                    return page.evaluate("""
                        () => {
                            const btns = [];
                            const seen = new Set();

                            // 1) Xoilac: #tv_links a.player-link
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
                            return btns;
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
                        page.wait_for_timeout(2500)

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
                            page.wait_for_selector('#tv_links a.player-link', timeout=8000)
                        except Exception:
                            pass
                        page.wait_for_timeout(2000)

                        buttons = detect_server_buttons(page)
                        if not buttons:
                            buttons = [{'idx': '0', 'label': 'Server 1',
                                        'selector': 'body'}]

                        print(f"     📺 {len(buttons)} server con: "
                              f"{[b['label'] for b in buttons]}", flush=True)

                        for btn in buttons:
                            target_url = [None]

                            def handle(req):
                                if target_url[0]:
                                    return
                                u = req.url.lower()
                                if ".m3u8" in u or ".flv" in u:
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
                        url_dung = None
                        for domain in XOILAC_DOMAINS:
                            try:
                                print(f"   🔗 Thử: {domain}", flush=True)
                                page.goto(domain, timeout=DOMAIN_TIMEOUT,
                                          wait_until="domcontentloaded")
                                title = (page.title() or "").lower()
                                if "just a moment" in title or "checking your browser" in title:
                                    print(f"   🛡️ Cloudflare challenge", flush=True)
                                    continue
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

                        page.wait_for_timeout(2000)

                        # === CLICK XEM THÊM ĐỂ LOAD ĐỦ ===
                        print(f"   🔽 Bắt đầu click 'XEM THÊM'...", flush=True)
                        n_clicks = click_xem_them_loop(page)
                        print(f"   ✅ Đã click {n_clicks} lần", flush=True)

                        # === QUÉT DANH SÁCH PHÒNG SAU KHI LOAD HẾT ===
                        danh_sach_phong = lay_phong_xoilac(page, url_dung, keyword_link)

                        print(f"🎯 {ten_nhom}: {len(danh_sach_phong)} phòng "
                              f"(nam + top giải + ≤{HOURS_AHEAD}h)", flush=True)

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
        print(f"📊 Tích lũy: {len(danh_sach_phat)} luồng", flush=True)

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
