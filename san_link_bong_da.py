import os
import requests
import time
from playwright.sync_api import sync_playwright

# ==========================================
# HÀM API: LẤY IP TỪ PROXYXOAY.SHOP
# ==========================================
def lay_proxy_tu_api():
    print("🔄 Đang gọi API ProxyXoay xin IP mới...", flush=True)
    
    api_key = "HZjISqEzmNZkVapIOpceYm"
    url = f"https://proxyxoay.shop/api/get.php?key={api_key}&nhamang=Random&tinhthanh=0"
    
    try:
        response = requests.get(url, timeout=15).json()
        if response.get("status") == 100:
            ip_port = response.get("proxyhttp", "").rstrip(":") 
            nha_mang = response.get("Nha Mang", "Unknown")
            print(f"✅ Đã bốc được IP: {ip_port} (Mạng: {nha_mang})", flush=True)
            return ip_port
        else:
            print(f"⚠️ API báo lỗi: {response.get('message')}", flush=True)
            return None
    except Exception as e:
        print(f"❌ Kẹt mạng lúc gọi API: {e}", flush=True)
        return None

# ==========================================
# HÀM LÕI: ĐIỀU KHIỂN TRÌNH DUYỆT ĐI SĂN
# ==========================================
def san_full_server_qua_proxy():
    print("🚀 KHỞI ĐỘNG CHIẾN DỊCH VÉT SẠCH 7 SERVER (CHIA THỂ LOẠI & KIỂM ĐỊNH PROXY)...", flush=True)
    
    MAX_RETRIES = 3

    # ==========================================
    # DANH SÁCH NGŨ LONG (5 SERVER)
    # (tên, url, keyword_link, kiểu_quét)
    # kiểu_quét: "" = chuẩn, "xoilac", "socolive", "thiendinh"
    # ==========================================
    tat_ca_server = [
        ("Socolive", "https://bit.ly/socolive", "/room/", "socolive"),
        ("Xoilac", "https://xoilaccg.tv", "/truc-tiep/", "xoilac"),
        ("Gavang", "https://gavanglink.co", "/truc-tiep/", "gavang"),
        ("Quechoa", "https://quechoa11.live", "/truc-tiep/", ""),
        ("ThienDinh", "https://sv2.thiendinh3.live/trang-chu", "", "thiendinh"),
        ("Hoiquan", "https://sv2.hoiquan6.live/trang-chu", "", "thiendinh"),
        ("Thapcam", "https://thapcamtivi.app", "/truc-tiep", "thapcam"),
    ]

    # Domain dự phòng cho Xoilac (thử lần lượt)
    XOILAC_DOMAINS = [
        "https://xoilaccg.tv",
        "https://xoilac.cfd",
        "https://xoilactv.pro",
        "https://xoilac7.tv",
    ]

    # Bảng ánh xạ tên môn thể thao
    SPORT_MAP = {
        "football": "Bóng đá",
        "basketball": "Bóng rổ",
        "tennis": "Tennis",
        "badminton": "Cầu lông",
        "volleyball": "Bóng chuyền",
        "esports": "Esports",
        "lol": "Esports",
        "dota2": "Esports",
        "csgo": "Esports",
        "baseball": "Bóng chày",
        "billiards": "Billiards",
    }

    danh_sach_phat = []           # Tích lũy kết quả xuyên suốt các vòng, KHÔNG reset
    server_da_thanh_cong = set()  # Đánh dấu server đã quét OK, không quét lại

    for lan_thu in range(1, MAX_RETRIES + 1):
        print(f"\n==========================================", flush=True)
        print(f"🔄 BẮT ĐẦU VÒNG QUÉT LẦN {lan_thu}/{MAX_RETRIES}", flush=True)
        print(f"==========================================", flush=True)

        # Chỉ quét lại các server chưa thành công
        server_can_quet = [s for s in tat_ca_server if s[0] not in server_da_thanh_cong]
        if not server_can_quet:
            print("✅ Tất cả server đã quét thành công, không cần chạy thêm!", flush=True)
            break

        print(f"📋 Cần quét: {', '.join(s[0] for s in server_can_quet)}", flush=True)

        print(f"🔄 Sử dụng Proxy tĩnh...", flush=True)
        cau_hinh_proxy = {
            "server": "http://14.241.72.139:10906",
            "username": "hieumx",
            "password": "hieu123"
        }
        so_tram_loi_vong_nay = 0
        so_tram_ok_vong_nay = 0

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True, 
                    proxy=cau_hinh_proxy,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )

                # Chặn tải ảnh và video để web chạy nhanh mượt & tiết kiệm băng thông proxy (Không chặn css/font để giữ DOM hợp lệ cho Playwright click)
                def chan_tai_nguyen_thua(route):
                    if route.request.resource_type in ["image", "media"]:
                        route.abort()
                    else:
                        route.continue_()
                context.route("**/*", chan_tai_nguyen_thua)

                # ==========================================
                # CÁC HÀM TRÍCH XUẤT PHÒNG THEO KIỂU SERVER
                # Mỗi hàm trả về dict: {url: {ten, thumb, sport}}
                # ==========================================

                def _loc_trung(danh_sach_raw, url_goc):
                    """Lọc trùng & chuẩn hóa danh sách phòng"""
                    result = {}
                    for item in danh_sach_raw:
                        url = item.get('url', '')
                        ten = item.get('ten', '').strip()
                        if not url or url == url_goc or url == url_goc + "/":
                            continue
                        if url not in result or len(ten) > len(result.get(url, {}).get('ten', '')):
                            result[url] = {
                                'ten': ten if ten else "Trận đấu đang chờ cập nhật",
                                'thumb': item.get('thumb', 'https://img.icons8.com/color/512/football2.png'),
                                'sport': item.get('sport', '')
                            }
                    return result

                def lay_phong_chuan(page, url_goc, keyword_link):
                    """Quét chuẩn: lấy tất cả link chứa keyword (Gavang, Quechoa)"""
                    raw = page.evaluate(f"""
                        Array.from(document.querySelectorAll('a[href*="{keyword_link}"]')).map(a => {{
                            let img = a.querySelector('img');
                            return {{
                                url: a.href,
                                ten: a.innerText.trim().replace(/\\n/g, ' - '),
                                thumb: img ? img.src : "https://img.icons8.com/color/512/football2.png",
                                sport: ''
                            }}
                        }})
                    """)
                    return _loc_trung(raw, url_goc)

                def lay_phong_xoilac(page, url_goc, keyword_link):
                    """Xoilac: đọc data-sport từ .grid-matches__item"""
                    raw = page.evaluate(f"""
                        (() => {{
                            const results = [];
                            // Grid chính (có data-sport)
                            document.querySelectorAll('.grid-matches__item').forEach(item => {{
                                const sport = item.getAttribute('data-sport') || 'football';
                                const linkEl = item.querySelector('a[href*="{keyword_link}"]');
                                if (!linkEl) return;
                                const img = item.querySelector('img');
                                results.push({{
                                    url: linkEl.href,
                                    ten: linkEl.getAttribute('title') || linkEl.innerText.trim().replace(/\\n/g, ' - '),
                                    thumb: img ? img.src : "https://img.icons8.com/color/512/football2.png",
                                    sport: sport
                                }});
                            }});
                            // Thanh ngang (match-horizontals) mặc định football
                            document.querySelectorAll('.match-horizontals-item[href*="{keyword_link}"]').forEach(a => {{
                                const url = a.href;
                                if (results.some(r => r.url === url)) return;
                                const img = a.querySelector('img');
                                results.push({{
                                    url: url,
                                    ten: a.innerText.trim().replace(/\\n/g, ' - '),
                                    thumb: img ? img.src : "https://img.icons8.com/color/512/football2.png",
                                    sport: 'football'
                                }});
                            }});
                            return results;
                        }})()
                    """)
                    return _loc_trung(raw, url_goc)

                def lay_phong_gavang(page, url_goc):
                    """Gavang: đọc data-sport từ .match-card (Alpine.js với tab football/basketball)"""
                    raw = page.evaluate("""
                        (() => {
                            const results = [];
                            const hostname = location.hostname;
                            document.querySelectorAll('.match-card').forEach(card => {
                                const sport = card.getAttribute('data-sport') || 'football';
                                // Link nằm trong thẻ a absolute inset-0
                                const linkEl = card.querySelector('a[class*="absolute"]') || card.querySelector('a');
                                if (!linkEl) return;
                                const href = linkEl.getAttribute('href') || '';
                                if (!href || href === '/' || href === '#') return;

                                const title = linkEl.getAttribute('data-title') || linkEl.getAttribute('data-tooltip') || '';
                                // Thumbnail từ img đội
                                const imgs = card.querySelectorAll('img');
                                let thumb = '';
                                for (const img of imgs) {
                                    const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
                                    if (src && !src.includes('flag') && src.includes('thesports')) {
                                        thumb = src; break;
                                    }
                                }
                                if (!thumb && imgs.length > 0) {
                                    thumb = imgs[0].getAttribute('src') || '';
                                }

                                results.push({
                                    url: linkEl.href,
                                    ten: title || linkEl.innerText.trim().replace(/\\n/g, ' - '),
                                    thumb: thumb || 'https://img.icons8.com/color/512/football2.png',
                                    sport: sport
                                });
                            });
                            return results;
                        })()
                    """)
                    return _loc_trung(raw, url_goc)

                def lay_phong_socolive(page, url_goc):
                    """Socolive: click từng tab thể loại (Bóng đá, Bóng rổ, Esports)"""
                    all_rooms = {}

                    # Lấy danh sách tab thể loại (bỏ qua "Trực tiếp" và "HOT")
                    sport_tabs = page.evaluate("""
                        Array.from(document.querySelectorAll('.live-type-item'))
                            .map(li => li.innerText.trim())
                            .filter(t => t && t !== 'Trực tiếp' && !t.includes('HOT') && !t.includes('Tất cả'))
                    """)
                    print(f"   🏷️ Tab thể loại Socolive: {sport_tabs}", flush=True)

                    def _get_rooms_in_visible_container():
                        """Lấy phòng từ container đang visible (không hidden)"""
                        return page.evaluate("""
                            (() => {
                                const results = [];
                                const containers = document.querySelectorAll('ul.hot-content, ul.live-type-content');
                                let activeContainer = null;
                                for (const c of containers) {
                                    if (!c.hidden && c.children.length > 0) {
                                        activeContainer = c;
                                        break;
                                    }
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
                                    return { url: a.href, ten: cleanText(a.innerText), thumb: thumb || '' };
                                };
                                if (!activeContainer) {
                                    document.querySelectorAll('.hot-content:not([hidden]) li a[href*="/room/"]').forEach(a => results.push(parseItem(a)));
                                    return results;
                                }
                                activeContainer.querySelectorAll('li a[href*="/room/"]').forEach(a => results.push(parseItem(a)));
                                return results;
                            })()
                        """)

                    if sport_tabs and len(sport_tabs) > 0:
                        for tab_name in sport_tabs:
                            try:
                                # Click tab thể loại
                                tab_els = page.query_selector_all('.live-type-item')
                                clicked = False
                                for el in tab_els:
                                    if el.inner_text().strip() == tab_name:
                                        el.click()
                                        clicked = True
                                        break
                                if not clicked:
                                    continue
                                page.wait_for_timeout(2500)

                                rooms = _get_rooms_in_visible_container()
                                print(f"   → {tab_name}: {len(rooms)} phòng", flush=True)

                                for room in rooms:
                                    if room['url'] not in all_rooms:
                                        all_rooms[room['url']] = {
                                            'ten': room['ten'] if room['ten'] else "Phòng BLV",
                                            'thumb': room['thumb'] or 'https://img.icons8.com/color/512/football2.png',
                                            'sport': tab_name
                                        }
                            except Exception as e:
                                print(f"   ⚠️ Lỗi tab {tab_name}: {e}", flush=True)
                                continue

                    # Fallback: nếu không tìm thấy tab, lấy tất cả phòng
                    if not all_rooms:
                        print("   ℹ️ Không tìm tab thể loại, lấy toàn bộ phòng...", flush=True)
                        rooms = page.evaluate("""
                            Array.from(document.querySelectorAll('a[href*="/room/"]')).map(a => {
                                const parent = a.closest('li') || a;
                                const imgs = parent.querySelectorAll('img');
                                let thumb = '';
                                for (const img of imgs) {
                                    const src = img.getAttribute('data-src') || img.src || '';
                                    if (src && !src.includes('avatar') && !src.includes('icon')) { thumb = src; break; }
                                }
                                return {
                                    url: a.href,
                                    ten: a.innerText.trim().split('\\n').join(' - '),
                                    thumb: thumb || 'https://img.icons8.com/color/512/football2.png',
                                    sport: ''
                                }
                            })
                        """)
                        return _loc_trung(rooms, url_goc)

                    return all_rooms

                def lay_phong_thapcam(page, url_goc):
                    """Thapcam: Đọc match info từ thẻ cha của link"""
                    raw = page.evaluate("""
                        Array.from(document.querySelectorAll('a[href*="/truc-tiep"]')).map(a => {
                            let img = a.querySelector('img');
                            let parent = a.closest('.match-card') || a.closest('li') || a.closest('.item') || a.parentElement.parentElement;
                            let rawText = parent ? parent.innerText : a.innerText;
                            let cleanText = rawText.trim().split('\\n').join(' - ').replace(/  +/g, ' ').replace(/XEM LIVE/g, '').replace(/ - - /g, ' - ').trim();
                            // Nếu cleanText bắt đầu hoặc kết thúc bằng " - ", cắt đi
                            if (cleanText.startsWith('- ')) cleanText = cleanText.substring(2);
                            if (cleanText.endsWith(' -')) cleanText = cleanText.substring(0, cleanText.length - 2);
                            
                            let sport = 'football';
                            if (a.href.includes('bong-ro') || a.href.includes('basketball')) sport = 'basketball';
                            else if (a.href.includes('tennis')) sport = 'tennis';
                            else if (a.href.includes('bong-chuyen')) sport = 'volleyball';
                            else if (a.href.includes('esport')) sport = 'esports';

                            return {
                                url: a.href,
                                ten: cleanText || 'Trận đấu',
                                thumb: img ? (img.getAttribute('src') || img.getAttribute('data-src') || '') : '',
                                sport: sport
                            }
                        }).filter(r => r.ten.length > 3)
                    """)
                    # Lấy những phòng không bị trùng url
                    return _loc_trung(raw, url_goc)

                def lay_phong_thiendinh(page, url_goc):
                    """ThienDinh: React SPA, click sidebar từng môn"""
                    all_rooms = {}
                    NAV_TEXTS = ['Trực tuyến', 'Bóng đá', 'Bóng chuyền', 'Billiards', 'Esports', 'Cầu lông', 'Tennis', 'Trang chủ', 'Lịch thi đấu', 'Kết quả', 'Xem lại']

                    mon_sidebar = [
                        ("Bóng đá",     "Bóng đá"),
                        ("Bóng chuyền", "Bóng chuyền"),
                        ("Tennis",       "Tennis"),
                        ("Billiards",    "Billiards"),
                        ("Esports",      "Esports"),
                        ("Cầu lông",    "Cầu lông"),
                    ]

                    def _get_thiendinh_rooms():
                        return page.evaluate("""
                            (() => {
                                const results = [];
                                const seen = new Set();
                                const navTexts = ['Trực tuyến','Bóng đá','Bóng chuyền','Billiards','Esports','Cầu lông','Tennis','Trang chủ','Lịch thi đấu','Kết quả','Xem lại'];
                                const mainEl = document.querySelector('main, [class*="content"], [class*="match"], [class*="list"]') || document.body;
                                mainEl.querySelectorAll('a[href]').forEach(a => {
                                    const href = a.getAttribute('href') || '';
                                    if (!href || href === '/' || href === '/trang-chu' || href === '#') return;
                                    if (href.startsWith('javascript:')) return;
                                    if (href.startsWith('http') && !href.includes(location.hostname)) return;
                                    if (seen.has(href)) return;
                                    const text = (a.textContent || '').trim();
                                    if (navTexts.includes(text)) return;
                                    if (!text || text.length < 2) return;
                                    seen.add(href);
                                    const img = a.querySelector('img');
                                    const cleanText = text.split('\\n').join(' - ').replace(/  +/g, ' ').trim();
                                    results.push({
                                        url: a.href,
                                        ten: cleanText || 'Trận đấu',
                                        thumb: img ? (img.src || img.getAttribute('data-src') || '') : ''
                                    });
                                });
                                return results;
                            })()
                        """)

                    for ten_mon, sport_tag in mon_sidebar:
                        try:
                            found = False
                            for el in page.query_selector_all('a, button, li, span'):
                                try:
                                    el_text = el.inner_text().strip()
                                    if el_text == ten_mon or el_text.startswith(ten_mon + ' ') or el_text.startswith(ten_mon + '\n'):
                                        el.click()
                                        found = True
                                        break
                                except:
                                    continue
                            if not found:
                                print(f"   ⚠️ Không tìm thấy sidebar: {ten_mon}", flush=True)
                                continue
                            page.wait_for_timeout(3000)
                            rooms = _get_thiendinh_rooms()
                            print(f"   🏷️ {ten_mon}: {len(rooms)} link", flush=True)
                            for room in rooms:
                                if room['url'] not in all_rooms:
                                    all_rooms[room['url']] = {
                                        'ten': room['ten'] or 'Trận đấu',
                                        'thumb': room['thumb'] or 'https://img.icons8.com/color/512/football2.png',
                                        'sport': sport_tag
                                    }
                        except Exception as e:
                            print(f"   ⚠️ Lỗi sidebar {ten_mon}: {e}", flush=True)
                            continue

                    if not all_rooms:
                        print("   ℹ️ Sidebar không hoạt động, lấy tất cả...", flush=True)
                        try:
                            for el in page.query_selector_all('a, button, li'):
                                try:
                                    if 'Trực tuyến' in el.inner_text():
                                        el.click()
                                        break
                                except:
                                    continue
                            page.wait_for_timeout(3000)
                            rooms = _get_thiendinh_rooms()
                            return _loc_trung([{**r, 'sport': ''} for r in rooms], url_goc)
                        except Exception:
                            pass

                # ==========================================
                # HÀM QUÉT TỔNG: DISPATCH THEO KIỂU SERVER
                # ==========================================
                def quet_trang(ten_nhom, url_trang_chu, keyword_link, kieu_quet=""):
                    nonlocal so_tram_loi_vong_nay, so_tram_ok_vong_nay
                    page = context.new_page()
                    print(f"\n📥 ĐANG QUÉT SERVER: {ten_nhom.upper()}", flush=True)
                    
                    ket_qua_tram = []
                    
                    try:
                        page.goto(url_trang_chu, timeout=60000, wait_until="domcontentloaded")
                        print("⏳ Đang rình Cloudflare mở cửa...", flush=True)
                        
                        # === PHÁT HIỆN PHÒNG CHIẾU ===
                        if kieu_quet == "xoilac":
                            # Thử lần lượt các domain dự phòng cho Xoilac
                            xoilac_ok = False
                            xoilac_url_dung = url_trang_chu
                            for xoilac_domain in XOILAC_DOMAINS:
                                try:
                                    print(f"   🔗 Thử Xoilac domain: {xoilac_domain}", flush=True)
                                    page.goto(xoilac_domain, timeout=30000, wait_until="domcontentloaded")
                                    page.wait_for_function(f"document.querySelectorAll('a[href*=\"{keyword_link}\"]').length > 0", timeout=30000)
                                    xoilac_url_dung = xoilac_domain
                                    xoilac_ok = True
                                    print(f"   ✅ Xoilac sống: {xoilac_domain}", flush=True)
                                    break
                                except Exception:
                                    print(f"   ❌ Domain chết: {xoilac_domain}", flush=True)
                                    continue
                            if not xoilac_ok:
                                raise Exception("Tất cả Xoilac domains đều chết!")
                            page.wait_for_timeout(5000)
                            danh_sach_phong = lay_phong_xoilac(page, xoilac_url_dung, keyword_link)
                        elif kieu_quet == "socolive":
                            page.wait_for_function(f"document.querySelectorAll('a[href*=\"{keyword_link}\"]').length > 0", timeout=60000)
                            page.wait_for_timeout(5000)
                            danh_sach_phong = lay_phong_socolive(page, url_trang_chu)
                        elif kieu_quet == "gavang":
                            # Alpine.js: chờ .match-card render
                            page.wait_for_function("document.querySelectorAll('.match-card').length > 0", timeout=60000)
                            page.wait_for_timeout(4000)
                            danh_sach_phong = lay_phong_gavang(page, url_trang_chu)
                        elif kieu_quet == "thapcam":
                            page.wait_for_function('document.querySelectorAll(\'a[href*="/truc-tiep"]\').length > 0', timeout=60000)
                            page.wait_for_timeout(3000)
                            danh_sach_phong = lay_phong_thapcam(page, url_trang_chu)
                        elif kieu_quet == "thiendinh":
                            # React SPA: chờ render xong
                            page.wait_for_timeout(10000)
                            danh_sach_phong = lay_phong_thiendinh(page, url_trang_chu)
                        else:
                            page.wait_for_function(f"document.querySelectorAll('a[href*=\"{keyword_link}\"]').length > 0", timeout=60000)
                            page.wait_for_timeout(5000)
                            danh_sach_phong = lay_phong_chuan(page, url_trang_chu, keyword_link)
                        
                        tong_so_tran = len(danh_sach_phong)
                        print(f"🎯 Phát hiện {tong_so_tran} phòng chiếu tại {ten_nhom}!", flush=True)
                        
                        # In chi tiết theo môn
                        mon_dem = {}
                        for d in danh_sach_phong.values():
                            sport_key = d.get('sport', '')
                            if sport_key:
                                mon_vn = SPORT_MAP.get(sport_key, sport_key)
                                mon_dem[mon_vn] = mon_dem.get(mon_vn, 0) + 1
                        if mon_dem:
                            print(f"   📋 Chia theo môn: {', '.join(f'{k}: {v}' for k, v in mon_dem.items())}", flush=True)

                        # === BẮT STREAM TỪNG PHÒNG ===
                        for stt, (link_phong, data_phong) in enumerate(danh_sach_phong.items(), 1):
                            ten_tran = data_phong['ten']
                            anh_thumb = data_phong['thumb']
                            sport_key = data_phong.get('sport', '')
                            
                            # Xác định tên nhóm M3U
                            if sport_key:
                                ten_mon_vn = SPORT_MAP.get(sport_key, sport_key)
                                nhom_m3u = f"{ten_nhom} - {ten_mon_vn}"
                            else:
                                nhom_m3u = ten_nhom
                            
                            stream_link = None
                            def bat_goi_tin(request):
                                nonlocal stream_link
                                url_lower = request.url.lower()
                                if ".flv" in url_lower or ".m3u8" in url_lower:
                                    stream_link = request.url
                            
                            page.on("request", bat_goi_tin)
                            try:
                                page.goto(link_phong, timeout=30000, wait_until="domcontentloaded")
                                page.wait_for_load_state("domcontentloaded")
                                page.wait_for_timeout(3000) 
                                
                                page.mouse.click(960, 300) 
                                page.wait_for_timeout(500)
                                page.mouse.click(960, 540) 
                                
                                page.wait_for_timeout(8000) 
                            except Exception:
                                pass 
                            finally:
                                page.remove_listener("request", bat_goi_tin)
                            
                            if stream_link:
                                ket_qua_tram.append({
                                    'nhom': nhom_m3u,
                                    'ten': ten_tran,
                                    'link': stream_link,
                                    'thumb': anh_thumb
                                })
                        
                        # Trạm này quét THÀNH CÔNG
                        so_tram_ok_vong_nay += 1
                        server_da_thanh_cong.add(ten_nhom)
                        danh_sach_phat.extend(ket_qua_tram)
                        print(f"✅ {ten_nhom}: Thu hoạch {len(ket_qua_tram)} luồng stream!", flush=True)

                    except Exception as e:
                        error_msg = str(e)
                        print(f"⚠️ Kẹt tường lửa hoặc web sập: {error_msg}", flush=True)
                        so_tram_loi_vong_nay += 1
                        
                        # Nếu lỗi là do proxy chết hẳn hoặc bị reset kết nối, báo hiệu để đổi proxy ngay
                        if "ERR_CONNECTION_RESET" in error_msg or "ERR_PROXY_CONNECTION_FAILED" in error_msg or "ERR_TIMED_OUT" in error_msg:
                            return "PROXY_DEAD"
                    finally:
                        page.close()
                    return "OK"

                # Quét từng server chưa thành công
                for ten_nhom, url_tc, keyword, kieu_quet in server_can_quet:
                    status = quet_trang(ten_nhom, url_tc, keyword, kieu_quet)
                    if status == "PROXY_DEAD":
                        print("🚫 Proxy chết hoặc bị chặn toàn tập! Hủy vòng quét này để đổi IP mới ngay lập tức...", flush=True)
                        break

                browser.close()
        except Exception as e:
            print(f"🔥 Lỗi hệ thống cốt lõi: {e}", flush=True)

        # ==========================================
        # ĐÁNH GIÁ CHẤT LƯỢNG VÒNG QUÉT
        # ==========================================
        print(f"\n📊 Kết quả vòng {lan_thu}: ✅ {so_tram_ok_vong_nay} OK, ❌ {so_tram_loi_vong_nay} fail", flush=True)
        print(f"📊 Tổng tích lũy: {len(danh_sach_phat)} luồng từ {len(server_da_thanh_cong)}/{len(tat_ca_server)} server", flush=True)

        if so_tram_ok_vong_nay == 0 and so_tram_loi_vong_nay > 0 and lan_thu < MAX_RETRIES:
            print("⚠️ Proxy hoàn toàn xịt vòng này. Ngủ 60s xin IP mới...", flush=True)
            time.sleep(60)
            continue

        if len(server_da_thanh_cong) < len(tat_ca_server) and lan_thu < MAX_RETRIES:
            server_con_lai = [s[0] for s in tat_ca_server if s[0] not in server_da_thanh_cong]
            print(f"🔄 Còn {len(server_con_lai)} server chưa quét được: {', '.join(server_con_lai)}", flush=True)
            print("⏳ Ngủ 60 giây rồi xin IP mới để thử server còn lại...", flush=True)
            time.sleep(60)
            continue

        print("🏆 Tất cả server đã quét xong!", flush=True)
        break

    # ==========================================
    # LỌC TRÙNG & ĐÓNG GÓI KẾT QUẢ CUỐI CÙNG
    # ==========================================
    seen_links = set()
    danh_sach_sach = []
    for luong in danh_sach_phat:
        if luong['link'] not in seen_links:
            seen_links.add(luong['link'])
            danh_sach_sach.append(luong)

    if danh_sach_sach:
        da_loc = len(danh_sach_phat) - len(danh_sach_sach)
        if da_loc > 0:
            print(f"🧹 Đã lọc {da_loc} link trùng lặp.", flush=True)

        print(f"\n📦 ĐANG ĐÓNG GÓI M3U VÀ CHIA THƯ MỤC...", flush=True)
        with open("tong_hop_bong_da.m3u", "w", encoding="utf-8") as file:
            file.write("#EXTM3U\n")
            for luong in danh_sach_sach:
                file.write(f'#EXTINF:-1 group-title="{luong["nhom"]}" tvg-logo="{luong["thumb"]}", ⚽ {luong["ten"]}\n')
                file.write(f'{luong["link"]}\n')
                
        print(f"🎉 ĐÃ VÉT SẠCH THÀNH CÔNG TỔNG CỘNG {len(danh_sach_sach)} TRẬN!", flush=True)
        nhom_count = {}
        for l in danh_sach_sach:
            nhom_count[l['nhom']] = nhom_count.get(l['nhom'], 0) + 1
        print(f"📊 Chi tiết: {', '.join(f'{k}: {v}' for k, v in nhom_count.items())}", flush=True)
    else:
        print(f"❌ ĐÃ THỬ HẾT {MAX_RETRIES} LẦN NHƯNG VẪN THẤT BẠI. HẸN CHU KỲ SAU!", flush=True)
        with open("tong_hop_bong_da.m3u", "w", encoding="utf-8") as file:
            file.write("#EXTM3U\n")

if __name__ == "__main__":
    san_full_server_qua_proxy()
