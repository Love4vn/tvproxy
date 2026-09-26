import datetime
import re
import urllib.request
import urllib.parse
import os
import sys
import time
from playwright.sync_api import sync_playwright

# ============================================================
# Cấu hình
# ============================================================
DEFAULT_URL = "https://sportsonline.gl"
MAX_HOURS_PAST = 4

REFERRER = "https://zundrixmediapipeline.com"
ORIGIN = "https://zundrixmediapipeline.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

STATIC_LANG_MAP = {
    "SPORTTV1": "PT", "SPORTTV2": "PT", "SPORTTV3": "PT",
    "SPORTTV4": "PT", "SPORTTV5": "PT",
}


# ============================================================
# Playwright Engine - Trích xuất link Stream gốc từ trang PHP
# ============================================================
def extract_real_stream_url(php_url: str) -> str:
    """
    Truy cập ngầm vào trang PHP bằng Playwright, lắng nghe network
    để tóm lấy link stream (.m3u8 ưu tiên, fallback .flv/.ts) thực sự đang phát.
    """
    print(f"   🔍 Đang quét mã nguồn kênh: {php_url} ...", flush=True)

    m3u8_url = [None]   # ưu tiên playlist
    other_url = [None]  # fallback segment / flv

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1024, "height": 768},
                user_agent=USER_AGENT,
            )
            page = context.new_page()

            def handle_request(request):
                url_lower = request.url.lower()
                if ".m3u8" in url_lower:
                    if m3u8_url[0] is None:
                        m3u8_url[0] = request.url
                elif ".flv" in url_lower or ".ts" in url_lower:
                    if other_url[0] is None:
                        other_url[0] = request.url

            page.on("request", handle_request)

            try:
                page.goto(php_url, timeout=20000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"      ⚠️ goto cảnh báo: {str(e)[:80]}", flush=True)

            # Chờ tối đa ~6 giây, thoát ngay khi có m3u8
            for _ in range(24):
                if m3u8_url[0]:
                    break
                time.sleep(0.25)

            try:
                browser.close()
            except Exception:
                pass
    except Exception as e:
        print(f"      ⚠️ Lỗi Playwright: {str(e)[:80]}", flush=True)

    final_url = m3u8_url[0] or other_url[0]
    if final_url:
        print(f"      ✅ Phát hiện link trực tiếp: {final_url[:70]}...", flush=True)
        return final_url

    print("      ❌ Không tìm thấy luồng video trực tiếp.", flush=True)
    return ""


# ============================================================
# Các hàm tiện ích
# ============================================================
def extract_channel_code(url: str) -> str:
    match = re.search(r"/channels/(?:hd|bra|pt)/([^/.]+)\.php", url, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return ""


def parse_language_line(line: str):
    match = re.match(r"^(HD\d{1,2}|BR\d)\s+(.+)$", line.strip(), re.IGNORECASE)
    if not match:
        return None

    channel_code = match.group(1).upper()
    lang_desc = match.group(2).strip().upper()
    primary = lang_desc.split("&")[0].strip()

    lang_map = {
        "ENGLISH": "EN", "FRENCH": "FR", "SPANISH": "ES", "ITALIAN": "IT",
        "GERMAN": "DE", "PORTUGUESE": "PT", "BRAZILIAN": "PT-BR", "INDIAN": "IN",
        "ARABIC": "AR", "GREEK": "EL", "ROMANIAN": "RO", "POLISH": "PL",
        "HUNGARIAN": "HU",
    }

    for key, tag in lang_map.items():
        if key in primary:
            return (channel_code, tag)

    if len(primary) >= 2:
        return (channel_code, primary[:2])
    return (channel_code, "EN")


def build_stream_url_tivimate(stream_url: str) -> str:
    """Định dạng link hoàn chỉnh đính kèm header bypass cho IPTV Player."""
    try:
        domain = urllib.parse.urlparse(stream_url).netloc.lower()
        if not domain:
            raise ValueError("no domain")
        ref_header = f"https://{domain}/"
    except Exception:
        ref_header = REFERRER + "/"

    return (
        f"{stream_url}"
        f"|User-Agent={USER_AGENT}"
        f"|Referer={ref_header}"
        f"|Origin={ref_header}"
    )


def build_extinf_line(title: str, time_str: str, date_str: str,
                      lang: str, group_title: str) -> str:
    display_title = title.replace(" x ", " vs ").replace(" X ", " vs ")
    display_name = f"{display_title} | {time_str} | {date_str} [{lang}]"
    return (
        f'#EXTINF:-1 tvg-name="{display_title}" '
        f'tvg-language="{lang}" '
        f'group-title="{group_title}",{display_name}'
    )


# ============================================================
# Hàm chạy chính
# ============================================================
def main():
    url = os.getenv("SPORTSONLINE")
    if not url or not url.strip():
        print(f"⚠️ Biến SPORTSONLINE trống, dùng URL mặc định: {DEFAULT_URL}")
        url = DEFAULT_URL

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"❌ Tải dữ liệu thất bại: {e}")
        sys.exit(1)

    lines = [line.strip() for line in html.splitlines() if line.strip()]

    # ---------- Xây dựng bảng ánh xạ ngôn ngữ ----------
    channel_lang_by_day = {}
    current_day_for_lang = None

    for line in lines:
        day_match = re.match(r"^([A-Z]+DAY)$", line.upper().strip())
        if day_match:
            current_day_for_lang = day_match.group(1)
            channel_lang_by_day.setdefault(current_day_for_lang, {})
            continue

        if current_day_for_lang is None:
            continue

        result = parse_language_line(line)
        if result:
            ch_code, lang_tag = result
            channel_lang_by_day[current_day_for_lang].setdefault(ch_code, lang_tag)

    def lookup_lang(day_name: str, channel_code: str) -> str:
        if day_name in channel_lang_by_day:
            if channel_code in channel_lang_by_day[day_name]:
                return channel_lang_by_day[day_name][channel_code]
        for d_map in channel_lang_by_day.values():
            if channel_code in d_map:
                return d_map[channel_code]
        return STATIC_LANG_MAP.get(channel_code, "EN")

    # ---------- Tính toán ngày dương lịch tương ứng ----------
    file_days = [line.upper() for line in lines if re.match(r"^[A-Z]+DAY$", line.upper())]
    today_name = datetime.datetime.now().strftime("%A").upper()
    today_date = datetime.datetime.now()

    day_dates_map = {}
    try:
        found_today_idx = file_days.index(today_name)
    except ValueError:
        found_today_idx = 0

    for idx, fd in enumerate(file_days):
        offset = idx - found_today_idx
        calc_date = today_date + datetime.timedelta(days=offset)
        day_dates_map[fd] = calc_date.strftime("%d-%m-%Y")

    # ---------- Cấu hình mốc thời gian lọc ----------
    # ---------- Cấu hình mốc thời gian lọc (naive, giờ VN) ----------
    now_utc_naive = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    now_vn = now_utc_naive + datetime.timedelta(hours=7)
    cutoff_vn = now_vn - datetime.timedelta(hours=MAX_HOURS_PAST)

    print(f"🕒 Giờ Việt Nam hiện tại: {now_vn.strftime('%d/%m/%Y %H:%M')}")

    # ---------- Duyệt lịch phát sóng ----------
    current_day_name = None
    grouped_by_date = {}
    last_hour = -1
    day_offset = 0
    skipped_past = 0

    skip_keywords = ["NEW DOMAIN", "IMPORTANT!", "READ!", "24/7 CHANNELS",
                     "INFO:", "EMAIL:"]

    for line in lines:
        if re.match(r"^[A-Z]+DAY$", line.upper()):
            current_day_name = line.upper()
            last_hour = -1
            day_offset = 0
            continue

        if any(k in line.upper() for k in skip_keywords):
            continue

        match = re.match(
            r"^(\d{2}:\d{2})\s+([^|]+?)(?:\s*\|\s*(https?://\S+))?$",
            line,
        )
        if not match:
            continue

        if not current_day_name or current_day_name not in day_dates_map:
            continue

        orig_time = match.group(1)
        raw_title = match.group(2).strip()
        station_url = match.group(3).strip() if match.group(3) else ""

        # Bỏ dòng tiêu đề ngôn ngữ / channel code lạc
        if re.match(
            r"^(HD\d+|BR\d+|SPORTS|ENGLISH|SPANISH|GERMAN)",
            raw_title, re.IGNORECASE,
        ) and not station_url:
            continue

        current_hour = int(orig_time.split(":")[0])
        if last_hour != -1 and current_hour < last_hour:
            day_offset += 1
        last_hour = current_hour

        base_date_str = day_dates_map[current_day_name]
        base_dt = datetime.datetime.strptime(base_date_str, "%d-%m-%Y")
        base_dt = base_dt + datetime.timedelta(days=day_offset)

        raw_datetime_str = f"{base_dt.strftime('%d-%m-%Y')} {orig_time}"

        try:
            dt_obj = datetime.datetime.strptime(raw_datetime_str, "%d-%m-%Y %H:%M")
            dt_th = dt_obj + datetime.timedelta(hours=6)
            th_date = dt_th.strftime("%Y-%m-%d")
            th_time = dt_th.strftime("%H:%M")
            th_date_display = dt_th.strftime("%d/%m/%Y")
            group_title = f"Sport Events {dt_th.day}/{dt_th.month}/{dt_th.year}"
        except Exception:
            dt_th = base_dt
            th_date = base_dt.strftime("%Y-%m-%d")
            th_time = orig_time
            th_date_display = base_dt.strftime("%d/%m/%Y")
            group_title = f"Sport Events {base_dt.day}/{base_dt.month}/{base_dt.year}"

        if dt_th < cutoff_vn:
            skipped_past += 1
            continue

        grouped_by_date.setdefault(th_date, {})
        match_key = f"{th_time}_{raw_title}"

        if match_key not in grouped_by_date[th_date]:
            grouped_by_date[th_date][match_key] = {
                "time": th_time,
                "date_display": th_date_display,
                "group_title": group_title,
                "title": raw_title,
                "streams": [],
            }

        if station_url:
            channel_code = extract_channel_code(station_url)
            lang = lookup_lang(current_day_name, channel_code)
            existing_urls = [s[0] for s in grouped_by_date[th_date][match_key]["streams"]]
            if station_url not in existing_urls:
                grouped_by_date[th_date][match_key]["streams"].append((station_url, lang))

    print(f"⏭️  Đã bỏ qua {skipped_past} trận đã kết thúc trước đó {MAX_HOURS_PAST}h.")

    # --------------------------------------------------------
    # Vòng lặp chuyển đổi link .php thành link stream trực tiếp
    # --------------------------------------------------------
    print("\n🚀 BẮT ĐẦU CHUYỂN ĐỔI LINK .PHP THÀNH FILE LUỒNG IPTV...")

    final_iptv_m3u_lines = ["#EXTM3U"]
    valid_stream_count = 0

    for date_key in sorted(grouped_by_date.keys()):
        matches = list(grouped_by_date[date_key].values())
        matches.sort(key=lambda x: x["time"])

        for m in matches:
            for php_url, lang in m["streams"]:
                real_video_url = extract_real_stream_url(php_url)
                if not real_video_url:
                    continue

                extinf = build_extinf_line(
                    title=m["title"],
                    time_str=m["time"],
                    date_str=m["date_display"],
                    lang=lang,
                    group_title=m["group_title"],
                )
                formatted_stream = build_stream_url_tivimate(real_video_url)

                final_iptv_m3u_lines.append(extinf)
                final_iptv_m3u_lines.append(formatted_stream)
                valid_stream_count += 1

    # ---------- Xuất file ----------
    output_filename = "sportsonline_live_streams.m3u"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(final_iptv_m3u_lines) + "\n")

    print("\n🎉 HOÀN THÀNH XUẤT FILE M3U!")
    print(f"📊 Tổng số link stream đã ghi: {valid_stream_count}")
    print(f"📁 Tên file đầu ra: {output_filename}")


if __name__ == "__main__":
    main()
