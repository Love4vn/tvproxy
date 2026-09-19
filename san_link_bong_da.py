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
DOMAIN_TIMEOUT = 12000

# Chỉ lấy bóng đá top 5 giải. False = lấy mọi bóng đá.
REQUIRE_TOP_LEAGUE_ONLY = True

# ==========================================
# SERVER (Socolive đã tắt)
# ==========================================
TAT_CA_SERVER = [
    # ("Socolive", "https://bit.ly/socolive",  "/room/",       "socolive"),  # TẮT
    ("Xoilac",   "https://xoilacz.io",       "/truc-tiep/",  "xoilac"),
    ("Gavang",   "https://gavanglink.co",    "/truc-tiep/",  "gavang"),
]

XOILAC_DOMAINS = [
    "https://xoilacz.io",
    "https://xoilaczzf.cc",
    "https://xoilacxth.tv",
    "https://xoilac.cfd",
    "https://xoilactv.pro",
    "https://xoilac7.tv",
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


# ==========================================
# HÀM LÕI
# ==========================================
def san_full_server_qua_proxy():
    print("🚀 BẮT ĐẦU QUÉT (Xoilac + Gavang)", flush=True)
    print(f"   → Chỉ lấy: Bóng đá (top 5 giải) + Tennis", flush=True)
    print(f"   → Lấy TẤT CẢ server con (ROY/HD ROY/FABIO/...)", flush=True)

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
                    user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/120.0.0.0 Safari/537.36"),
                    locale="vi-VN",
                )
                context.set_default_timeout(15000)
                context.set_default_navigation_timeout(DOMAIN_TIMEOUT)

                # Stealth
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['vi-VN','vi','en-US','en']});
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
                                    sport: sport,
                                    container: card.innerText || ""
                                });
                            });
                            return results;
                        })()
                    """)
                    return _loc_trung(raw, url_goc)

                # ==========================================
                # LẤY TẤT CẢ SERVER CON CỦA 1 TRẬN (Xoilac)
                # ==========================================
                def lay_tat_ca_server_con(page, link_phong):
                    """
                    Vào 1 phòng, click từng button `#tv_link_N`
                    -> hứng từng request .m3u8/.flv
                    Trả về list: [{'label': 'ROY', 'url': 'https://...'}, ...]
                    """
                    streams = []
                    seen_urls = set()

                    try:
                        page.goto(link_phong, timeout=20000, wait_until="domcontentloaded")
                        # Chờ player + buttons render
                        try:
                            page.wait_for_selector('#tv_links a.player-link', timeout=8000)
                        except Exception:
                            pass
                        page.wait_for_timeout(3000)

                        # Đọc danh sách buttons
                        buttons = page.evaluate("""() => {
                            const btns = document.querySelectorAll('#tv_links a.player-link');
                            return Array.from(btns).map(a => ({
                                idx: a.getAttribute('data-link') || '0',
                                label: (a.innerText || '').trim().split('\\n').pop().trim() || ('Kênh ' + (a.getAttribute('data-link') || '0')),
                            }));
                        }""")

                        if not buttons:
                            buttons = [{'idx': '0', 'label': 'Server 1'}]

                        print(f"     📺 {len(buttons)} server con: {[b['label'] for b in buttons]}", flush=True)

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
                                # Click button theo id, fallback theo text
                                try:
                                    page.click(f'#tv_link_{btn["idx"]}', timeout=5000)
                                except Exception:
                                    try:
                                        page.get_by_role("link", name=btn["label"]).first.click(timeout=5000)
                                    except Exception:
                                        pass

                                # Chờ stream mới (tối đa ~10s)
                                for _ in range(40):
                                    if target_url[0]:
                                        break
                                    page.wait_for_timeout(250)

                                # Nếu chưa có → click vào giữa player để trigger play
                                if not target_url[0]:
                                    try:
                                        page.mouse.click(960, 500)
                                    except Exception:
                                        pass
                                    for _ in range(20):
                                        if target_url[0]:
                                            break
                                        page.wait_for_timeout(250)
                            except Exception as e:
                                print(f"        ⚠️ [{btn['label']}] lỗi click: {str(e)[:60]}", flush=True)
                            finally:
                                page.remove_listener("request", handle)

                            if target_url[0] and target_url[0] not in seen_urls:
                                seen_urls.add(target_url[0])
                                streams.append({"label": btn["label"], "url": target_url[0]})
                                print(f"        ✅ [{btn['label']}] {target_url[0][:75]}", flush=True)
                            else:
                                print(f"        ⛔ [{btn['label']}] không bắt được stream", flush=True)
                    except Exception as e:
                        print(f"     ⚠️ Lỗi extract streams: {str(e)[:80]}", flush=True)

                    return streams

                # ==========================================
                # FALLBACK: lấy 1 stream từ phòng (Gavang)
                # ==========================================
                def lay_1_stream(page, link_phong):
                    stream_link = [None]

                    def handle(req):
                        if stream_link[0]:
                            return
                        u = req.url.lower()
                        if ".m3u8" in u or ".flv" in u:
                            stream_link[0] = req.url

                    page.on("request", handle)
                    try:
                        page.goto(link_phong, timeout=20000, wait_until="domcontentloaded")
                        for _ in range(24):
                            if stream_link[0]: break
                            page.wait_for_timeout(250)
                        if not stream_link[0]:
                            try:
                                page.mouse.click(960, 300)
                                page.wait_for_timeout(300)
                                page.mouse.click(960, 540)
                            except Exception:
                                pass
                            for _ in range(20):
                                if stream_link[0]: break
                                page.wait_for_timeout(250)
                    except Exception:
                        pass
                    finally:
                        page.remove_listener("request", handle)
                    return stream_link[0]

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
                        else:
                            domains = [url_trang_chu]

                        url_dung = None
                        for domain in domains:
                            try:
                                print(f"   🔗 Thử: {domain}", flush=True)
                                page.goto(domain, timeout=DOMAIN_TIMEOUT, wait_until="domcontentloaded")
                                title = (page.title() or "").lower()
                                if "just a moment" in title or "checking your browser" in title:
                                    print(f"   🛡️ Cloudflare challenge", flush=True)
                                    continue

                                if kieu_quet == "gavang":
                                    page.wait_for_function(
                                        "document.querySelectorAll('.match-card').length > 0",
                                        timeout=DOMAIN_TIMEOUT)
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
                        else:
                            danh_sach_phong = {}

                        print(f"🎯 {ten_nhom}: {len(danh_sach_phong)} phòng (đã lọc giải)", flush=True)

                        for stt, (link_phong, data_phong) in enumerate(danh_sach_phong.items(), 1):
                            ten_tran = data_phong['ten']
                            anh_thumb = data_phong['thumb']
                            sport_key = data_phong.get('sport', '')

                            mon_vn = SPORT_MAP.get(normalize_sport(sport_key), "Bóng đá")
                            nhom_m3u = f"{ten_nhom} - {mon_vn}"

                            print(f"\n   [{stt}/{len(danh_sach_phong)}] {ten_tran[:70]}", flush=True)

                            # Xoilac: lấy nhiều server con
                            if kieu_quet == "xoilac":
                                streams = lay_tat_ca_server_con(page, link_phong)
                                for s in streams:
                                    ket_qua_tram.append({
                                        'nhom': nhom_m3u,
                                        'ten': f"{ten_tran} [{s['label']}]",
                                        'link': s['url'],
                                        'thumb': anh_thumb,
                                        'server': s['label'],
                                        'tran': ten_tran,   # tên trận gốc, không có [label]
                                    })
                            else:
                                # Gavang / khác: 1 stream duy nhất
                                stream_link = lay_1_stream(page, link_phong)
                                if stream_link:
                                    ket_qua_tram.append({
                                        'nhom': nhom_m3u,
                                        'ten': ten_tran,
                                        'link': stream_link,
                                        'thumb': anh_thumb,
                                        'server': '',
                                        'tran': ten_tran,
                                    })
                                    print(f"        ✅ {stream_link[:80]}", flush=True)

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

        print(f"\n📊 Vòng {lan_thu}: ✅ {so_tram_ok_vong_nay} OK, ❌ {so_tram_loi_vong_nay} fail", flush=True)
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
                # ten đã bao gồm [ROY], [HD ROY]...
                file.write(f'#EXTINF:-1 group-title="{luong["nhom"]}" '
                           f'tvg-logo="{luong["thumb"]}", ⚽ {luong["ten"]}\n')
                file.write(f'{luong["link"]}\n')

        print(f"🎉 TỔNG CỘNG {len(danh_sach_sach)} TRẬN/LUỒNG!", flush=True)

        # Thống kê theo nhóm
        nhom_count = {}
        for l in danh_sach_sach:
            nhom_count[l['nhom']] = nhom_count.get(l['nhom'], 0) + 1
        print(f"📊 Chi tiết: {', '.join(f'{k}: {v}' for k, v in nhom_count.items())}", flush=True)

        # Thống kê server label (ROY/HD ROY/...)
        server_count = {}
        for l in danh_sach_sach:
            srv = l.get('server', '') or '(mặc định)'
            server_count[srv] = server_count.get(srv, 0) + 1
        print(f"📺 Server con đã lấy: {', '.join(f'{k}: {v}' for k, v in server_count.items())}", flush=True)
    else:
        print(f"❌ Không có luồng nào sau {MAX_RETRIES} lần thử!", flush=True)
        with open("tong_hop_bong_da.m3u", "w", encoding="utf-8") as file:
            file.write("#EXTM3U\n")


if __name__ == "__main__":
    san_full_server_qua_proxy()
