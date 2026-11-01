import os
import re
import sys
from playwright.sync_api import sync_playwright

# Danh sách domain Xoilac để thử
XOILAC_DOMAINS = [
    "https://xoilacz.io",
    "https://xoilaczzh.io",
    "https://xoilaczzf.cc",
    "https://xoilaczzb.cc",
    "https://xoilaczzc.cc",
    "https://xoilaczzd.cc",
    "https://xoilaczzh.cc",
    "https://xoilacxxi.cc",
    "https://xoilacxxe.cc",
    "https://xoilaczzzj.cc",
    "https://xoilacxbm.tv",
    "https://xoilacxth.tv",
    "https://xoilacxbi.tv",
    "https://xoilac7tv.tv",
    "https://xoilacvvr.tv",
    "https://xoilacxbr.tv",
    "https://xoilaczbh.tv",
    "https://xoilaczzz.pro",
    "https://vebozbr.cc",
    "https://90phutzzu.tv",
    "https://xoilacxcd.tv",
    "https://xoilaczck.tv",
    "https://xoilacvbp.tv"
]

def get_latest_headers():
    print("🚀 Bắt đầu tự động dò tìm header mới nhất từ Xoilac...")
    captured_headers = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Chặn ảnh và font để chạy nhanh hơn
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "font"] else route.continue_())

        for domain in XOILAC_DOMAINS:
            print(f"  -> Thử domain: {domain}")
            try:
                page.goto(domain, timeout=15000, wait_until="domcontentloaded")
                page.wait_for_selector('.grid-matches__item', timeout=10000)
                
                # Tìm trận đấu đầu tiên
                match_links = page.locator('a[href*="/truc-tiep/"]').all()
                if not match_links:
                    print("     ⚠️ Không tìm thấy trận đấu nào.")
                    continue
                
                match_url = match_links[0].get_attribute('href')
                print(f"     -> Vào trận: {match_url}")
                page.goto(match_url, timeout=15000, wait_until="domcontentloaded")
                
                # Chờ danh sách server
                page.wait_for_selector('#tv_links a.player-link', timeout=10000)
                
                # Click server đầu tiên và bắt header
                captured = {"origin": None, "referer": None}
                
                def handle_response(response):
                    if captured["origin"]: return
                    u = response.url.lower()
                    if ".m3u8" in u or ".flv" in u:
                        if response.status in (200, 206):
                            req_headers = response.request.headers
                            captured["origin"] = req_headers.get("origin") or req_headers.get("Origin")
                            captured["referer"] = req_headers.get("referer") or req_headers.get("Referer")
                            
                page.on("response", handle_response)
                page.locator('#tv_links a.player-link').first.click(timeout=5000)
                
                # Đợi tối đa 8 giây để bắt request
                for _ in range(16):
                    if captured["origin"]:
                        break
                    page.wait_for_timeout(500)
                
                if captured["origin"]:
                    print(f"     ✅ Bắt được: Origin={captured['origin']} | Referer={captured['referer']}")
                    captured_headers = captured
                    break # Đã lấy được thì dừng vòng lặp domain
                else:
                    print("     ❌ Không bắt được request stream từ server này.")

            except Exception as e:
                print(f"     ⚠️ Lỗi ở domain {domain}: {str(e)[:100]}")
                continue

        browser.close()
    
    return captured_headers

def update_worker_file(origin, referer):
    file_path = "worker.js"
    if not os.path.exists(file_path):
        print(f"❌ Không tìm thấy file {file_path} để cập nhật.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Tạo block rule mới
    new_rules = f"""// [XOILAC_RULES_START]
        "quickscoreboardz.com":      {{ Origin: "{origin}", Referer: "{referer}" }},
        "domaincdn.cc":              {{ Origin: "{origin}", Referer: "{referer}" }},
        "jorvakstreamcache.com":     {{ Origin: "{origin}", Referer: "{referer}" }},
        "zundrixmediapipeline.com":  {{ Origin: "{origin}", Referer: "{referer}" }},
        // [XOILAC_RULES_END]"""

    # Regex tìm và thay thế đoạn giữa 2 thẻ
    pattern = re.compile(r'// \[XOILAC_RULES_START\].*?// \[XOILAC_RULES_END\]', re.DOTALL)
    
    if not pattern.search(content):
        print("❌ Không tìm thấy thẻ [XOILAC_RULES_START] trong worker.js. Bạn đã copy đúng file chưa?")
        return

    new_content = pattern.sub(new_rules, content)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    
    print(f"✅ Đã tự động cập nhật file {file_path} với header mới!")

if __name__ == "__main__":
    headers = get_latest_headers()
    if headers and headers["origin"] and headers["referer"]:
        update_worker_file(headers["origin"], headers["referer"])
    else:
        print("⚠️ Không lấy được header mới. Giữ nguyên cấu hình cũ trong worker.js.")
