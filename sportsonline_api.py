import datetime
import re
import urllib.request
import os
import sys

# ============================================================
# Cấu hình
# ============================================================
# URL mặc định nếu biến môi trường SPORTSONLINE trống
DEFAULT_URL = "https://sportsonline.gl/prog.txt"

# Số giờ tối đa cho phép trận đã bắt đầu (nếu vượt quá → bỏ qua)
MAX_HOURS_PAST = 4

# ============================================================
# Ánh xạ ngôn ngữ tĩnh cho các mã kênh không có trong file gốc
# ============================================================
STATIC_LANG_MAP = {
    "SPORTTV1": "PT",
    "SPORTTV2": "PT",
    "SPORTTV3": "PT",
    "SPORTTV4": "PT",
    "SPORTTV5": "PT",
}


def extract_channel_code(url: str) -> str:
    """
    Trích xuất mã kênh từ URL stream.
    Ví dụ:
        .../channels/hd/hd2.php       -> HD2
        .../channels/bra/br5.php      -> BR5
        .../channels/pt/sporttv2.php  -> SPORTTV2
    """
    match = re.search(
        r"/channels/(?:hd|bra|pt)/([^/.]+)\.php", url, re.IGNORECASE
    )
    if match:
        return match.group(1).upper()
    return ""


def parse_language_line(line: str):
    """
    Phân tích dòng định nghĩa ngôn ngữ kênh (VD: "HD2 ENGLISH").
    Trả về (channel_code, language_tag) hoặc None.
    """
    match = re.match(r"^(HD\d{1,2}|BR\d)\s+(.+)$", line.strip(), re.IGNORECASE)
    if not match:
        return None

    channel_code = match.group(1).upper()
    lang_desc = match.group(2).strip().upper()

    # Lấy ngôn ngữ đầu tiên (trước dấu &)
    primary = lang_desc.split("&")[0].strip()

    lang_map = {
        "ENGLISH": "EN",
        "FRENCH": "FR",
        "SPANISH": "ES",
        "ITALIAN": "IT",
        "GERMAN": "DE",
        "PORTUGUESE": "PT",
        "BRAZILIAN": "PT-BR",
        "INDIAN": "IN",
        "ARABIC": "AR",
        "GREEK": "EL",
        "ROMANIAN": "RO",
        "POLISH": "PL",
        "HUNGARIAN": "HU",
    }

    for key, tag in lang_map.items():
        if key in primary:
            return (channel_code, tag)

    if len(primary) >= 2:
        return (channel_code, primary[:2])

    return (channel_code, "EN")


def build_m3u_header() -> str:
    return "#EXTM3U\n"


def build_m3u_entry(
    title: str,
    time_str: str,
    date_str: str,
    lang: str,
    group_title: str,
    stream_url: str,
) -> str:
    """
    Tạo một mục M3U hoàn chỉnh với đầy đủ header EXTVLCOPT.
    """
    # Đổi " x " thành " vs "
    display_title = title.replace(" x ", " vs ").replace(" X ", " vs ")

    # Tên hiển thị cuối: "Italy vs Belgium | 01:45 | 26/09/2026 [EN]"
    display_name = f"{display_title} | {time_str} | {date_str} [{lang}]"

    lines = []
    extinf = (
        f'#EXTINF:-1 tvg-name="{display_title}" '
        f'tvg-language="{lang}" '
        f'group-title="{group_title}",{display_name}'
    )
    lines.append(extinf)

    lines.append(
        "#EXTVLCOPT:http-referrer=https://live2.zundrixmediapipeline.com/"
    )
    lines.append(
        "#EXTVLCOPT:http-origin=https://live2.zundrixmediapipeline.com/"
    )
    lines.append(
        "#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    lines.append(stream_url)

    return "\n".join(lines)


def main():
    # ============================================================
    # Lấy URL: ưu tiên biến môi trường, nếu trống dùng mặc định
    # ============================================================
    url = os.getenv("SPORTSONLINE")
    if not url or not url.strip():
        print(f"⚠️  Biến SPORTSONLINE trống, dùng URL mặc định: {DEFAULT_URL}")
        url = DEFAULT_URL

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"❌ Tải dữ liệu thất bại: {e}")
        sys.exit(1)

    lines = [line.strip() for line in html.splitlines() if line.strip()]

    # ============================================================
    # Bước 1: Xây dựng bảng ánh xạ kênh -> ngôn ngữ
    # ============================================================
    channel_lang_map = {}
    for line in lines:
        if re.match(r"^[A-Z]+DAY$", line.upper()):
            continue
        result = parse_language_line(line)
        if result:
            ch_code, lang_tag = result
            if ch_code not in channel_lang_map:
                channel_lang_map[ch_code] = lang_tag

    for ch, lang in STATIC_LANG_MAP.items():
        if ch not in channel_lang_map:
            channel_lang_map[ch] = lang

    print(f"📡 Bảng ánh xạ kênh-ngôn ngữ: {channel_lang_map}")

    # ============================================================
    # Bước 2: Xây dựng bảng ánh xạ ngày (logic gốc)
    # ============================================================
    file_days = [
        line.upper() for line in lines if re.match(r"^[A-Z]+DAY$", line.upper())
    ]

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

    # ============================================================
    # Bước 3: Xác định mốc thời gian Việt Nam hiện tại và ngưỡng bỏ qua
    # ============================================================
    # GitHub Actions chạy UTC, Việt Nam là UTC+7
    now_utc = datetime.datetime.utcnow()
    now_vn = now_utc + datetime.timedelta(hours=7)

    # Ngưỡng: trận đã bắt đầu trước mốc này → bỏ
    cutoff_vn = now_vn - datetime.timedelta(hours=MAX_HOURS_PAST)

    print(f"🕒 Giờ Việt Nam hiện tại: {now_vn.strftime('%d/%m/%Y %H:%M')}")
    print(
        f"🚫 Bỏ qua các trận bắt đầu trước: "
        f"{cutoff_vn.strftime('%d/%m/%Y %H:%M')}"
    )

    # ============================================================
    # Bước 4: Phân tích từng dòng sự kiện
    # ============================================================
    current_day_name = None
    grouped_by_date = {}
    last_hour = -1
    day_offset = 0
    skipped_past = 0

    for line in lines:
        if re.match(r"^[A-Z]+DAY$", line.upper()):
            current_day_name = line.upper()
            last_hour = -1
            day_offset = 0
            continue

        if any(
            k in line.upper()
            for k in [
                "NEW DOMAIN",
                "IMPORTANT!",
                "READ!",
                "24/7 CHANNELS",
                "INFO:",
                "EMAIL:",
            ]
        ):
            continue

        match = re.match(
            r"^(\d{2}:\d{2})\s+([^|]+?)(?:\s*\|\s*(https?://\S+))?$", line
        )
        if not match:
            continue

        if not current_day_name or current_day_name not in day_dates_map:
            continue

        orig_time = match.group(1)
        raw_title = match.group(2).strip()
        station_url = match.group(3).strip() if match.group(3) else ""

        if (
            re.match(
                r"^(HD\d+|BR\d+|SPORTS|ENGLISH|SPANISH|GERMAN)",
                raw_title,
                re.IGNORECASE,
            )
            and not station_url
        ):
            continue

        current_hour = int(orig_time.split(":")[0])

        # Logic qua đêm
        if last_hour != -1 and current_hour < last_hour:
            day_offset += 1
        last_hour = current_hour

        base_date_str = day_dates_map[current_day_name]
        base_dt = datetime.datetime.strptime(base_date_str, "%d-%m-%Y")
        base_dt = base_dt + datetime.timedelta(days=day_offset)

        raw_datetime_str = f"{base_dt.strftime('%d-%m-%Y')} {orig_time}"

        try:
            dt_obj = datetime.datetime.strptime(
                raw_datetime_str, "%d-%m-%Y %H:%M"
            )
            # Giờ gốc + 6 = giờ Việt Nam
            dt_th = dt_obj + datetime.timedelta(hours=6)
            th_date = dt_th.strftime("%Y-%m-%d")          # key sắp xếp
            th_time = dt_th.strftime("%H:%M")
            th_date_display = dt_th.strftime("%d/%m/%Y")  # hiển thị
            # group-title mới: "Sport Events D/M/YYYY" (không có 0 đứng đầu)
            group_title = (
                f"Sport Events {dt_th.day}/{dt_th.month}/{dt_th.year}"
            )
        except Exception:
            th_date = base_dt.strftime("%Y-%m-%d")
            th_time = orig_time
            th_date_display = base_dt.strftime("%d/%m/%Y")
            group_title = (
                f"Sport Events {base_dt.day}/{base_dt.month}/{base_dt.year}"
            )
            dt_th = base_dt

        # ============================================================
        # Lọc trận đã bắt đầu quá MAX_HOURS_PAST tiếng
        # ============================================================
        if dt_th < cutoff_vn:
            skipped_past += 1
            continue

        if th_date not in grouped_by_date:
            grouped_by_date[th_date] = {}

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
            lang = channel_lang_map.get(channel_code, "EN")

            existing_urls = [
                s[0] for s in grouped_by_date[th_date][match_key]["streams"]
            ]
            if station_url not in existing_urls:
                grouped_by_date[th_date][match_key]["streams"].append(
                    (station_url, lang)
                )

    # ============================================================
    # Bước 5: Tạo file M3U
    # ============================================================
    m3u_lines = [build_m3u_header()]

    for date_key in sorted(grouped_by_date.keys()):
        matches = list(grouped_by_date[date_key].values())
        matches.sort(key=lambda x: x["time"])

        for m in matches:
            for stream_url, lang in m["streams"]:
                entry = build_m3u_entry(
                    title=m["title"],
                    time_str=m["time"],
                    date_str=m["date_display"],
                    lang=lang,
                    group_title=m["group_title"],
                    stream_url=stream_url,
                )
                m3u_lines.append(entry)

    output_path = "sportsonline.m3u"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines))

    total = sum(len(v["streams"]) for v in grouped_by_date.values())
    print(f"✅ Đã lưu file M3U thành công! Tổng số kênh: {total}")
    print(f"🚫 Đã bỏ qua {skipped_past} kênh của các trận đã bắt đầu quá "
          f"{MAX_HOURS_PAST} tiếng")
    print(f"📁 File: {output_path}")


if __name__ == "__main__":
    main()
