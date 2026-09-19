import time
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

# ==========================================
# DANH SÁCH SERVER (đã lược bớt 4 server)
# ==========================================
TAT_CA_SERVER = [
    ("Socolive", "https://bit.ly/socolive",  "/room/",       "socolive"),
    ("Xoilac",   "https://xoilacz.io",       "/truc-tiep/",  "xoilac"),
    ("Gavang",   "https://gavanglink.co",    "/truc-tiep/",  "gavang"),
]

# Domain dự phòng (thử lần lượt)
XOILAC_DOMAINS = [
    "https://xoilacz.io",
    "https://xoilac.cfd",
    "https://xoilactv.pro",
    "https://xoilac7.tv",
]

SOCOLIVE_DOMAINS = [
    "https://bit.ly/socolive",
    "https://socoliveae.tv",
    "https://socolive-football.pro",
    "https://socolive711.com",
    "https://drepo.io",
    "https://socolive55z.top",
]

# ==========================================
# LỌC MÔN THỂ THAO (chỉ bóng đá + tennis)
# ==========================================
ALLOWED_SPORTS = {"football", "tennis"}
ALLOWED_TABS_VN = {"Bóng đá", "Tennis"}

SPORT_NORMALIZE = {
    "football": "football", "bóng đá": "football", "bong da": "football",
    "tennis": "tennis",
}

SPORT_MAP = {
    "football": "Bóng đá",
    "tennis": "Tennis",
}


def normalize_sport(s):
    if not s:
        return ""
    return SPORT_NORMALIZE.get(s.lower().strip(), "")


def is_allowed_sport(sport):
    """True nếu sport trống (mặc định coi là bóng đá) hoặc thuộc football/tennis."""
    n = normalize_sport(sport)
    if not n:
        return True
    return n in ALLOWED_SPORTS


# ==========================================
# HÀM LÕI
# ==========================================
def san_full_server_qua_proxy():
    print("🚀 KHỞI ĐỘNG CHIẾN DỊCH QUÉT (Socolive / Xoilac / Gavang – chỉ Bóng đá + Tennis)...", flush=True)

    danh_sach_phat = []           # Tích lũy xuyên vòng
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
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/120.0.0.0 Safari/537.36"),
                )
                context.set_default_timeout(20000)
                context.set_default_navigation_timeout(30000)

                # Chặn ảnh/media cho nhẹ proxy
                def chan_tai_nguyen_thua(route):
                    if route.request.resource_type in ["image", "media"]:
                        route.abort()
                    else:
                        route.continue_()
                context.route("**/*", chan_tai_nguyen_thua)

                # ==========================================
                # TRÍCH XUẤT DANH SÁCH PHÒNG THEO SERVER
                # ==========================================
                def _loc_trung(danh_sach_raw, url_goc):
                    result = {}
                    for item in danh_sach_raw:
                        url = item.get('url', '')
                        ten = item.get('ten', '').strip()
                        sport = item.get('sport', '')

                        if not is_allowed_sport(sport):
                            continue
                        if not url or url == url_goc or url == url_goc + "/":
                            continue

                        if url not in result or len(ten) > len(result.get(url, {}).get('ten', '')):
                            result[url] = {
                                'ten': ten if ten else "Trận đấu đang chờ cập nhật",
                                'thumb': item.get('thumb',
                                                  'https://img.icons8.com/color/512/football2.png'),
                                'sport': normalize_sport(sport) or sport,
                            }
                    return result

                def lay_phong_xoilac(page, url_goc, keyword_link):
                    """Xoilac: .grid-matches__item có data-sport"""
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
                                    sport: sport
                                }});
                            }});
                            document.querySelectorAll('.match-horizontals-item[href*="{keyword_link}"]').forEach(a => {{
                                if (results.some(r => r.url === a.href)) return;
                                const img = a.querySelector('img');
                                results.push({{
                                    url: a.href,
                                    ten: a.innerText.trim().replace(/\\n/g, ' - '),
                                    thumb: img ? img.src : "",
                                    sport: 'football'
                                }});
                            }});
                            return results;
                        }})()
                    """)
                    return _loc_trung(raw, url_goc)

                def lay_phong_gavang(page, url_goc):
                    """Gavang: .match-card có data-sport"""
                    raw = page.evaluate("""
                        (() => {
                            const results = [];
                            document.querySelectorAll('.match-card').forEach(card => {
                                const sport = card.getAttribute('data-sport') || 'football';
                                const linkEl = card.querySelector('a[class*="absolute"]') || card.querySelector('a');
                                if (!linkEl) return;
                                const href = linkEl.getAttribute('href') || '';
                                if (!href || href === '/' || href === '#') return;

                                const title = linkEl.getAttribute('data-title') || linkEl.getAttribute('data-tooltip') || '';
                                const imgs = card.querySelectorAll('img');
                                let thumb = '';
                                for (const img of imgs) {
                                    const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
                                    if (src && !src.includes('flag') && src.includes('thesports')) { thumb = src; break; }
                                }
                                if (!thumb && imgs.length > 0) thumb = imgs[0].getAttribute('src') || '';

                                results.push({
                                    url: linkEl.href,
                                    ten: title || linkEl.innerText.trim().replace(/\\n/g, ' - '),
                                    thumb: thumb,
                                    sport: sport
                                });
                            });
                            return results;
                        })()
                    """)
                    return _loc_trung(raw, url_goc)

                def lay_phong_socolive(page, url_goc):
                    """Socolive: click tab chỉ Bóng đá + Tennis"""
                    all_rooms = {}

                    sport_tabs = page.evaluate("""
                        Array.from(document.querySelectorAll('.live-type-item'))
                            .map(li => li.innerText.trim())
                            .filter(t => t === 'Bóng đá' || t === 'Tennis')
                    """)
                    print(f"   🏷️ Tab sẽ click: {sport_tabs}", flush=True)

                    def _get_rooms_in_visible_container():
                        return page.evaluate("""
                            (() => {
                                const results = [];
                                const containers = document.querySelectorAll('ul.hot-content, ul.live-type-content');
                                let activeContainer = null;
                                for (const c of containers) {
                                    if (!c.hidden && c.children.length > 0) { activeContainer = c; break; }
                                }
                                const cleanText = t => t.trim().split('\\n').join(' - ');
                                const parseItem = a => {
                                    const parent = a.closest('li') || a;
                                    const imgs = parent.querySelectorAll('img');
                                    let thumb = '';
                                    for (const img of imgs) {
                                        const src = img.getAttribute('data-src') || img.getAttribute('src') || '';
                                        if (src && !src.includes('avatar') && !src.includes('icon') && !src.includes('hot-live') && !src.includes('none')) {
                                            thumb = src; break;
                                        }
                                    }
                                    return { url: a.href, ten: cleanText(a.innerText), thumb: thumb };
                                };
                                if (!activeContainer) {
                                    document.querySelectorAll('.hot-content:not([hidden]) li a[href*="/room/"]').forEach(a => results.push(parseItem(a)));
                                    return results;
                                }
                                activeContainer.querySelectorAll('li a[href*="/room/"]').forEach(a => results.push(parseItem(a)));
                                return results;
                            })()
                        """)

                    if sport_tabs:
                        for tab_name in sport_tabs:
                            try:
                                for el in page.query_selector_all('.live-type-item'):
                                    if el.inner_text().strip() == tab_name:
                                        el.click(); break
                                page.wait_for_timeout(1500)  # giảm từ 2500 -> 1500
                                rooms = _get_rooms_in_visible_container()
                                print(f"   → {tab_name}: {len(rooms)} phòng", flush=True)
                                for room in rooms:
                                    if room['url'] not in all_rooms:
                                        all_rooms[room['url']] = {
                                            'ten': room['ten'] or "Phòng BLV",
                                            'thumb': room['thumb'] or
                                                     'https://img.icons8.com/color/512/football2.png',
                                            'sport': tab_name,
                                        }
                            except Exception as e:
                                print(f"   ⚠️ Lỗi tab {tab_name}: {e}", flush=True)
                    else:
                        # Fallback: chưa xác định được tab -> coi tất cả là bóng đá
                        print("   ℹ️ Không có tab Bóng đá/Tennis, lấy toàn bộ phòng...", flush=True)
                        rooms = page.evaluate("""
                            Array.from(document.querySelectorAll('a[href*="/room/"]')).map(a => {
                                const parent = a.closest('li') || a;
                                const imgs = parent.querySelectorAll('img');
                                let thumb = '';
                                for (const img of imgs) {
                                    const src = img.getAttribute('data-src') || img.src || '';
                                    if (src && !src.includes('avatar') && !src.includes('icon')) { thumb = src; break; }
                                }
                                return { url: a.href, ten: a.innerText.trim().split('\\n').join(' - '), thumb: thumb };
                            })
                        """)
                        return _loc_trung([{**r, 'sport': 'football'} for r in rooms], url_goc)

                    return all_rooms

                # ==========================================
                # BẮT STREAM (event-driven, thoát sớm)
                # ==========================================
                def bat_stream_tu_phong(page, link_phong):
                    stream_link = [None]

                    def handle_request(req):
                        if stream_link[0]:
                            return
                        u = req.url.lower()
                        if ".m3u8" in u or ".flv" in u:
                            stream_link[0] = req.url

                    page.on("request", handle_request)
                    try:
                        page.goto(link_phong, timeout=25000, wait_until="domcontentloaded")

                        # Poll nhanh: tối đa ~6s, check mỗi 250ms
                        for _ in range(24):
                            if stream_link[0]:
                                break
                            page.wait_for_timeout(250)

                        # Nếu chưa có, click play rồi chờ thêm ~5s
                        if not stream_link[0]:
                            try:
                                page.mouse.click(960, 300)
                                page.wait_for_timeout(300)
                                page.mouse.click(960, 540)
                            except Exception:
                                pass
                            for _ in range(20):
                                if stream_link[0]:
                                    break
                                page.wait_for_timeout(250)
                    except Exception:
                        pass
                    finally:
                        page.remove_listener("request", handle_request)

                    return stream_link[0]

                # ==========================================
                # QUÉT TỔNG: DISPATCH THEO SERVER
                # ==========================================
                def quet_trang(ten_nhom, url_trang_chu, keyword_link, kieu_quet=""):
                    nonlocal so_tram_loi_vong_nay, so_tram_ok_vong_nay
                    page = context.new_page()
                    print(f"\n📥 QUÉT SERVER: {ten_nhom.upper()}", flush=True)
                    ket_qua_tram = []

                    try:
                        # === 1. Mở trang chủ (có fallback domain) ===
                        if kieu_quet == "xoilac":
                            domains = XOILAC_DOMAINS
                        elif kieu_quet == "socolive":
                            domains = SOCOLIVE_DOMAINS
                        else:
                            domains = [url_trang_chu]

                        url_dung = None
                        for domain in domains:
                            try:
                                print(f"   🔗 Thử domain: {domain}", flush=True)
                                page.goto(domain, timeout=25000, wait_until="domcontentloaded")

                                if kieu_quet == "gavang":
                                    page.wait_for_function(
                                        "document.querySelectorAll('.match-card').length > 0",
                                        timeout=25000,
                                    )
                                else:
                                    page.wait_for_function(
                                        f"document.querySelectorAll('a[href*=\"{keyword_link}\"]').length > 0",
                                        timeout=25000,
                                    )
                                url_dung = domain
                                print(f"   ✅ Sống: {domain}", flush=True)
                                break
                            except Exception as e:
                                print(f"   ❌ Chết: {domain}", flush=True)
                                continue

                        if not url_dung:
                            raise Exception("Tất cả domain đều chết!")

                        # === 2. Trích xuất danh sách phòng ===
                        page.wait_for_timeout(1500)  # giảm từ 5s -> 1.5s

                        if kieu_quet == "xoilac":
                            danh_sach_phong = lay_phong_xoilac(page, url_dung, keyword_link)
                        elif kieu_quet == "socolive":
                            danh_sach_phong = lay_phong_socolive(page, url_dung)
                        elif kieu_quet == "gavang":
                            danh_sach_phong = lay_phong_gavang(page, url_dung)
                        else:
                            danh_sach_phong = {}

                        print(f"🎯 {ten_nhom}: {len(danh_sach_phong)} phòng (đã lọc bóng đá/tennis)",
                              flush=True)

                        # === 3. Bắt stream từng phòng ===
                        for stt, (link_phong, data_phong) in enumerate(danh_sach_phong.items(), 1):
                            ten_tran = data_phong['ten']
                            anh_thumb = data_phong['thumb']
                            sport_key = data_phong.get('sport', '')

                            mon_vn = SPORT_MAP.get(normalize_sport(sport_key), "Bóng đá")
                            nhom_m3u = f"{ten_nhom} - {mon_vn}"

                            print(f"   [{stt}/{len(danh_sach_phong)}] {ten_tran[:60]}", flush=True)
                            stream_link = bat_stream_tu_phong(page, link_phong)

                            if stream_link:
                                ket_qua_tram.append({
                                    'nhom': nhom_m3u,
                                    'ten': ten_tran,
                                    'link': stream_link,
                                    'thumb': anh_thumb,
                                })
                                print(f"        ✅ {stream_link[:80]}", flush=True)

                        so_tram_ok_vong_nay += 1
                        server_da_thanh_cong.add(ten_nhom)
                        danh_sach_phat.extend(ket_qua_tram)
                        print(f"✅ {ten_nhom}: {len(ket_qua_tram)} luồng!", flush=True)

                    except Exception as e:
                        error_msg = str(e)
                        print(f"⚠️ Lỗi {ten_nhom}: {error_msg}", flush=True)
                        so_tram_loi_vong_nay += 1
                        if any(x in error_msg for x in
                               ("ERR_CONNECTION_RESET", "ERR_PROXY_CONNECTION_FAILED", "ERR_TIMED_OUT")):
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

        print(f"\n📊 Vòng {lan_thu}: ✅ {so_tram_ok_vong_nay} OK, ❌ {so_tram_loi_vong_nay} fail",
              flush=True)
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
                           f'tvg-logo="{luong["thumb"]}", ⚽ {luong["ten"]}\n')
                file.write(f'{luong["link"]}\n')

        print(f"🎉 TỔNG CỘNG {len(danh_sach_sach)} TRẬN!", flush=True)
        nhom_count = {}
        for l in danh_sach_sach:
            nhom_count[l['nhom']] = nhom_count.get(l['nhom'], 0) + 1
        print(f"📊 Chi tiết: {', '.join(f'{k}: {v}' for k, v in nhom_count.items())}", flush=True)
    else:
        print(f"❌ Thất bại sau {MAX_RETRIES} lần!", flush=True)
        with open("tong_hop_bong_da.m3u", "w", encoding="utf-8") as file:
            file.write("#EXTM3U\n")


if __name__ == "__main__":
    san_full_server_qua_proxy()
