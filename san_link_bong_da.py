"""
🎯 SĂN LINK XOILAC - Bản cuối cùng
✅ Fix: Loại triệt để Hạng 2 Đức (Hạng 2 Đức, 2. Bundesliga, ...)
✅ Fix: Xử lý redirect xoilacz.io -> domain sống
✅ Chỉ Bóng đá (nam) + Tennis
✅ Top 5 châu Âu cấp 1 + C1/C2/C3 + WC/Euro/Nation League + giao hữu EU
✅ Auto click "XEM THÊM" đến 24h tới
✅ Lấy TẤT CẢ server con (ROY/HD ROY/FABIO...)
✅ Tự động thêm #EXTVLCOPT cho M3U
"""
import re
import time
import unicodedata
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
DOMAIN_TIMEOUT = 25000          # Đủ dài cho redirect chain
STREAM_WAIT_TRIES = 40          # ~10s chờ stream mỗi nút
STREAM_WAIT_STEP_MS = 250
HOURS_AHEAD = 24
MAX_XEM_THEM_CLICKS = 15

# ==========================================
# DANH SÁCH SERVER + DOMAIN
# ==========================================
TAT_CA_SERVER = [
    ("Xoilac", "https://xoilacz.io", "/truc-tiep/", "xoilac"),
]

# Danh sách domain - sẽ thử lần lượt đến khi có 1 domain sống
# Bao gồm cả domain đích có thể redirect tới
XOILAC_DOMAINS = [
    "https://xoilacz.io",        # Domain chính (có thể redirect)
    "https://xoilaczzf.cc",      # Domain đích hay gặp
    "https://xoilaczzb.cc",      # Domain đích khác
    "https://xoilaczzc.cc",
    "https://xoilaczzd.cc",
    "https://xoilacxth.tv",
    "https://xoilac7tv.tv",
    "https://xoilacvvr.tv",
]

# ==========================================
# HELPERS CHUẨN HÓA TIẾNG VIỆT
# ==========================================
def normalize_vn(text):
    """Chuẩn hóa về không dấu, lowercase."""
    if not text:
        return ""
    text = str(text).lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = text.replace('đ', 'd')
    return text
def format_match_name(name):
    """
    Đổi:  'Fulham vs Manchester United lúc 22:30 ngày 20/09/2026'
    ->    'Fulham vs Manchester United | 22:30 | 20/09/2026'
    Nếu không match pattern thì trả về nguyên gốc.
    """
    if not name:
        return name
    m = re.search(
        r'\s*l[uú]c\s+(\d{1,2}:\d{2})\s+ng[aà]y\s+(\d{1,2}/\d{1,2}(?:/\d{4})?)',
        name, re.IGNORECASE
    )
    if m:
        clean = name[:m.start()].strip()
        time_str = m.group(1)
        date_str = m.group(2)
        return f"{clean} | {time_str} | {date_str}"
    return name.strip()

# ==========================================
# 🚫 SPORT WHITELIST — CHỈ CHẤP NHẬN 2 MÔN
# ==========================================
SPORT_WHITELIST = {"football", "tennis"}

OTHER_SPORT_KEYWORDS = [
    # Bóng rổ
    r"\bbasketball\b", r"\bbong\s*ro\b", r"\bnba\b", r"\beuroleague\b",
    r"\beuro\s*league\b", r"\bbbl\b", r"\bnbb\b", r"\bacb\b",
    r"\bbrose\s*bamberg\b", r"\balba\b", r"\bldlc\b", r"\bfiba\b",
    # Bóng chuyền
    r"\bvolleyball\b", r"\bbong\s*chuyen\b", r"\bvnl\b",
    # Cầu lông
    r"\bbadminton\b", r"\bcau\s*long\b", r"\bbwf\b",
    # Bóng bàn
    r"\btable\s*tennis\b", r"\bbong\s*ban\b", r"\bwtt\b",
    # Esports
    r"\besports?\b", r"\blol\b", r"\bleague\s*of\s*legends\b",
    r"\bdota\s*2?\b", r"\bcs\s*:?\s*go\b", r"\bcsgo\b",
    r"\bvalorant\b", r"\bpubg\b", r"\bmobile\s*legends\b",
    # Khác
    r"\bbaseball\b", r"\bbong\s*chay\b", r"\bmlb\b",
    r"\bhandball\b", r"\bbong\s*nem\b",
    r"\bhockey\b", r"\bkhuc\s*con\s*cau\b", r"\bnhl\b",
    r"\brugby\b", r"\bcricket\b", r"\bgolf\b", r"\bbilliards\b",
    r"\bsnooker\b", r"\bdart\b", r"\bformula\s*1\b", r"\bf1\b",
]

# ==========================================
# 🚫 HARD EXCLUDE — LOẠI NGAY NẾU MATCH
# ==========================================
HARD_EXCLUDE_PATTERNS = [
    # ---- Nữ / Trẻ / Dự bị ----
    r"\bnu\b", r"\bwomen\b", r"\bfemale\b", r"\bladies\b",
    r"\bdamen\b", r"\bfeminine\b", r"\bfemenil\b", r"\bfeminino\b",
    r"\bu\d{2}\b", r"\bu-\d{2}\b", r"\bunder\s*\d{2}\b",
    r"\byouth\b", r"\bjunior\b", r"\btre\b", r"\breserve\b",
    r"\bacademy\b", r"\bhoc\s*vien\b", r"\bdoi\s*b\b",

    # ==========================================
    # ---- HẠNG 2 CỦA TOP 5 (ĐÃ FIX KỸ) ----
    # ==========================================
    # Hạng 2 Đức / 2. Bundesliga / Bundesliga 2
    r"hang\s*(2|hai|nhi)\s*[^\w]*(duc|bundesliga|germany)",
    r"hang\s*(2|hai|nhi)\s*duc",
    r"2\.?\s*bundesliga",
    r"bundesliga\s*2\b",
    r"bundesliga\s*(2|zwei)",

    # Hạng 2 Anh / Championship / EFL Championship
    r"hang\s*(2|hai|nhi)\s*[^\w]*(anh|england)",
    r"\befl\s*championship\b",
    r"\bchampionship\b",
    r"\bleague\s*one\b",
    r"\bleague\s*two\b",
    r"hang\s*(1|nhat|nh[âa]t)\s*anh",     # Hạng nhất Anh = Championship

    # Hạng 2 Ý / Serie B
    r"hang\s*(2|hai|nhi)\s*[^\w]*(y\b|italia|italy)",
    r"\bserie\s*b\b",
    r"serie\s*b\b",

    # Hạng 2 Pháp / Ligue 2
    r"hang\s*(2|hai|nhi)\s*[^\w]*(phap|france)",
    r"\bligue\s*2\b",
    r"ligue\s*2\b",

    # Hạng 2 TBN / La Liga 2 / Segunda
    r"hang\s*(2|hai|nhi)\s*[^\w]*(tbn|tay\s*ban\s*nha|spain)",
    r"\bla\s*liga\s*2\b", r"\blaliga\s*2\b",
    r"\bsegunda\b", r"\bsegunda\s*division\b",
    r"la\s*liga\s*2\b", r"laliga\s*2\b",

    # ---- Hạng 3+ của top 5 ----
    r"\b3\.?\s*liga\b",
    r"\bregionalliga\b",
    r"hang\s*(3|ba)\s*(duc|anh|y|phap|tbn)",
    r"\bleague\s*3\b",

    # ---- Các giải khác có thể nhầm ----
    r"\bchallenger\s*pro\b",
    r"\bk\s*league\s*2\b",

    # ---- Châu Á ----
    r"\bbhutan\b", r"\bthai\s*land\b", r"\bthai\s*league\b",
    r"\bmalaysia\b", r"\bindonesia\b", r"\bphilippines\b",
    r"\bsingapore\b", r"\bmyanmar\b", r"\bcambodia\b", r"\bcampuchia\b",
    r"\btrung\s*quoc\b", r"\bchina\b", r"\bcsl\b",
    r"\bnhat\b", r"\bjapan\b", r"\bj\s*league\b", r"\bj1\b", r"\bj2\b",
    r"\bhan\s*quoc\b", r"\bkorea\b", r"\bk\s*league\b",
    r"\ban\s*do\b", r"\bindia\b", r"\bisl\b",
    r"\biran\b", r"\biraq\b", r"\bsaudi\b", r"\barab\b", r"\ba\s*rap\b",
    r"\buae\b", r"\bqatar\b", r"\bkuwait\b", r"\bbahrain\b", r"\boman\b",
    r"\buzbekistan\b", r"\bkazakhstan\b", r"\bkyrgyz\b", r"\btajikistan\b",
    r"\bviet\s*nam\b", r"\bv\.?\s*league\b", r"\bvleague\b",
    r"\bafc\s*champions\b", r"\bafc\s*cup\b",

    # ---- Châu Mỹ ----
    r"\bvenezuela\b",
    r"\bbrasil\b", r"\bbrazil\b", r"\bbrasileir[ao]\b",
    r"\bargentina\b", r"\bprimera\s*division\b",
    r"\bmexico\b", r"\bliga\s*mx\b", r"\bmls\b",
    r"\bchile\b", r"\bcolombia\b", r"\bperu\b", r"\becuador\b",
    r"\buruguay\b", r"\bparaguay\b", r"\bbolivia\b",
    r"\bcosta\s*rica\b", r"\bhonduras\b", r"\bguatemala\b", r"\bpanama\b",
    r"\bconcacaf\b", r"\bcopa\s*america\b", r"\bcopa\s*libertadores\b",
    r"\bconcacaf\s*champions\b", r"\bleagues\s*cup\b", r"\bcanada\b",
    r"\bcanadian\s*premier\b",

    # ---- Châu Phi ----
    r"\begypt\b", r"\bai\s*cap\b", r"\bmaroc\b", r"\bmorocco\b",
    r"\btunisia\b", r"\balgeria\b", r"\bnam\s*phi\b", r"\bsouth\s*africa\b",
    r"\bnigeria\b", r"\bghana\b", r"\bcaf\b", r"\bafcon\b",
    r"\bcaf\s*champions\b",

    # ---- Châu Đại Dương ----
    r"\baustralia\b", r"\ba-?league\b", r"\bnew\s*zealand\b",

    # ---- Châu Âu nhưng KHÔNG PHẢI TOP 5 ----
    r"\bczech\b", r"\bsec\b", r"\bfortuna\s*liga\b", r"\bchance\s*liga\b",
    r"\baustria\b", r"\bbundesliga\s*ao\b",
    r"\bthuy\s*si\b", r"\bswitzerland\b", r"\bsuper\s*league\s*thuy\b",
    r"\bbelgium\b", r"\bpro\s*league\s*bi\b", r"\bjupiler\b",
    r"\bholland\b", r"\bnetherlands\b", r"\beredivisie\b",
    r"\bportugal\b", r"\bbo\s*dao\s*nha\b", r"\bprimeira\s*liga\b",
    r"\bturkey\b", r"\btho\s*nhi\s*ky\b", r"\bsuper\s*lig\b",
    r"\bgreece\b", r"\bhy\s*lap\b",
    r"\bscotland\b", r"\bscottish\b",
    r"\bwales\b", r"\bwelsh\b", r"\bnorthern\s*ireland\b",
    r"\bireland\b", r"\bireland\s*premier\b",
    r"\bcroatia\b", r"\bserbia\b",
    r"\bpoland\b", r"\bekstraklasa\b",
    r"\bukraine\b", r"\bnga\b", r"\brussia\b",
    r"\bdenmark\b", r"\bdan\s*mach\b", r"\bsuperliga\b",
    r"\bsweden\b", r"\bthuy\s*dien\b", r"\ballsvenskan\b",
    r"\bnorway\b", r"\bna\s*uy\b", r"\beliteserien\b",
    r"\bfinland\b", r"\bphan\s*lan\b", r"\bveikkausliiga\b",
    r"\bromania\b", r"\bbulgaria\b", r"\bhungary\b",
    r"\bslovenia\b", r"\bslovakia\b",
    r"\bbosnia\b", r"\balbania\b", r"\bmacedonia\b",
    r"\biceland\b", r"\bcyprus\b", r"\bmalta\b",
    r"\bluxembourg\b", r"\bestonia\b", r"\blatvia\b", r"\blithuania\b",
    r"\bbelarus\b", r"\bmoldova\b", r"\bgeorgia\b", r"\barmenia\b",
    r"\bazerbaijan\b",
]

# ==========================================
# ✅ WHITELIST — CHỈ GIỮ NẾU MATCH CHÍNH XÁC
# ==========================================
TOP_LEAGUE_PATTERNS = [
    # ---- Top 5 châu Âu cấp 1 ----
    r"\bpremier\s*league\b",
    r"\bngoai\s*hang\s*anh\b",
    r"\bepl\b",
    r"\bla\s*liga\b(?!\s*2)", r"\blaliga\b(?!\s*2)",
    r"\bbundesliga\b(?!\s*2)(?!\s*zwei)",
    r"\bserie\s*a\b(?!\s*b)",
    r"\bligue\s*1\b",

    # ---- Cúp châu Âu ----
    r"\bchampions\s*league\b", r"\buefa\s*champions\b",
    r"\bcup\s*c1\b", r"\bcup\s*1\b", r"\bucl\b",
    r"\beuropa\s*league\b", r"\bcup\s*c2\b", r"\buel\b",
    r"\bconference\s*league\b", r"\bcup\s*c3\b", r"\buecl\b",
    r"\bsieu\s*cup\s*chau\s*au\b", r"\bsuper\s*cup\s*uefa\b",
    r"\buefa\s*super\s*cup\b",

    # ---- ĐTQG ----
    r"\bworld\s*cup\b", r"\bfifa\s*world\s*cup\b", r"\bworldcup\b",
    r"\buefa\s*euro\b", r"\beuro\s*20\d{2}\b",
    r"\beuro\s*championship\b", r"\beuro\s*cup\b",
    r"\buefa\s*nations\s*league\b", r"\bnations\s*league\b",
    r"\buefa\s*nations\b",
]

# Quốc gia EU cho giao hữu
EURO_COUNTRIES = {
    "anh", "england", "duc", "germany", "phap", "france",
    "y", "italy", "tay ban nha", "spain", "bo dao nha", "portugal",
    "ha lan", "netherlands", "bi", "belgium", "thuy si", "switzerland",
    "ao", "austria", "dan mach", "denmark",
    "thuy dien", "sweden", "na uy", "norway",
    "phan lan", "finland", "ba lan", "poland",
    "croatia", "serbia", "scotland", "wales", "ireland",
    "cong hoa sec", "czech", "slovakia", "slovenia",
    "hungary", "romania", "bulgaria",
    "hy lap", "greece", "tho nhi ky", "turkey",
    "ukraine", "nga", "russia",
}

FRIENDLY_KEYWORDS = ("giao huu", "friendly", "friendlies")


# ==========================================
# LOGIC LỌC
# ==========================================
def is_other_sport(text):
    """True nếu text chứa từ khóa của MÔN KHÁC."""
    if not text:
        return False
    t = normalize_vn(text)
    for pat in OTHER_SPORT_KEYWORDS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


def is_hard_excluded(text):
    """True nếu text chứa từ khóa bị cấm."""
    if not text:
        return False
    t = normalize_vn(text)
    for pat in HARD_EXCLUDE_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


def contains_top_league(text):
    """True nếu text khớp whitelist regex."""
    if not text:
        return False
    t = normalize_vn(text)
    for pat in TOP_LEAGUE_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


def has_euro_country(text):
    if not text:
        return False
    t = normalize_vn(text)
    return any(c in t for c in EURO_COUNTRIES)


def is_friendly(text):
    if not text:
        return False
    t = normalize_vn(text)
    return any(kw in t for kw in FRIENDLY_KEYWORDS)


def detect_sport(name="", sport_hint=""):
    """
    Trả về: 'football' | 'tennis' | 'other' | 'unknown'
    """
    hint = normalize_vn(sport_hint or "").strip()

    if hint in ("football", "soccer", "bong da"):
        return "football"
    if hint in ("tennis", "quan vot"):
        return "tennis"
    if hint:
        return "other"

    n = normalize_vn(name or "")
    if is_other_sport(n):
        return "other"
    if any(kw in n for kw in ("tennis", "quan vot", "atp", "wta")):
        return "tennis"
    return "unknown"


def should_keep(name, sport_hint="", container_text=""):
    """
    4 lớp bảo vệ:
    - LỚP 0: data-sport = môn khác → loại ngay
    - LỚP 1: từ khóa môn khác trong nội dung → loại ngay
    - LỚP 2: hard exclude (Nữ/Trẻ/Hạng 2+) → loại
    - LỚP 3: whitelist giải → giữ
    """
    # LỚP 0
    sport = detect_sport(name, sport_hint)
    if sport == "other":
        return False
    if sport == "tennis":
        return True

    combined = f"{name} {container_text}"

    # LỚP 1
    if is_other_sport(combined):
        return False

    # LỚP 2
    if is_hard_excluded(combined):
        return False

    # LỚP 3
    if contains_top_league(combined):
        return True

    # Giao hữu châu Âu
    if is_friendly(combined) and has_euro_country(combined):
        return True

    return False


# ==========================================
# TIME FILTER
# ==========================================
def parse_match_datetime(text):
    if not text:
        return None
    m = re.search(r'(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2})/(\d{1,2})', text)
    if not m:
        return None
    hh, mm, dd, mo = map(int, m.groups())
    now = datetime.now()
    try:
        dt = datetime(now.year, mo, dd, hh, mm)
        if dt < now - timedelta(days=1):
            dt = dt.replace(year=now.year + 1)
        return dt
    except ValueError:
        return None


def is_within_24h(text):
    dt = parse_match_datetime(text)
    if dt is None:
        return True
    return dt <= datetime.now() + timedelta(hours=HOURS_AHEAD)


# ==========================================
# HEADER M3U
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
# TEST FILTER (tùy chọn)
# ==========================================
def _test_filter():
    tests = [
        # --- Nên LOẠI ---
        ("Bayern Munchen vs Brose Bamberg", "basketball bundesliga", "basketball", False),
        ("LA Lakers vs Boston Celtics", "nba", "basketball", False),
        ("Vietnam vs Thailand", "bong chuyen", "volleyball", False),
        ("Lee Chong Wei vs Lin Dan", "cau long", "badminton", False),
        ("T1 vs GenG", "lol lck", "esports", False),
        ("Dep. La Guaira vs Deportivo Tachira", "venezuela primera", "", False),
        ("Tensung FC vs Drukpa FC", "bhutan premier league", "", False),
        ("FC Hradec Králové vs FK Teplice", "czech first league", "", False),
        # Hạng 2 Đức - các biến thể
        ("Hannover 96 vs VfL Bochum", "Hạng 2 Đức", "", False),
        ("Energie Cottbus vs St. Pauli", "2. Bundesliga", "", False),
        ("Arminia Bielefeld vs Heidenheim", "Hạng nhì Đức", "", False),
        ("Fortuna Düsseldorf vs Hamburg", "Bundesliga 2", "", False),
        # Hạng 2 các nước khác
        ("Arezzo vs SudTirol", "hang 2 y - serie b", "", False),
        ("Leeds vs Leicester", "EFL Championship", "", False),
        ("Ajaccio vs Guingamp", "Ligue 2", "", False),
        # Nữ/Trẻ
        ("Nữ AS Harima vs Nữ NGU Nagoya", "", "", False),
        ("U19 Bayern vs U19 Dortmund", "", "", False),
        # Quốc gia ngoài
        ("Bahia vs Flamengo", "brasileirao serie a", "", False),
        ("Al Nassr vs Al Hilal", "saudi pro league", "", False),
        ("Ajax vs PSV", "eredivisie ha lan", "", False),
        ("Benfica vs Porto", "primeira liga bo dao nha", "", False),
        ("Celtic vs Rangers", "scottish premiership", "", False),

        # --- Nên GIỮ ---
        ("Tottenham vs Aston Villa", "ngoai hang anh - premier league", "football", True),
        ("Bayer Leverkusen vs RB Leipzig", "bundesliga duc", "football", True),
        ("Real Madrid vs Barcelona", "la liga tay ban nha", "football", True),
        ("Inter Milan vs Juventus", "serie a y", "football", True),
        ("PSG vs Marseille", "ligue 1 phap", "football", True),
        ("Man City vs Real Madrid", "champions league - cup c1", "football", True),
        ("Roma vs Sevilla", "europa league - cup c2", "football", True),
        ("West Ham vs Fiorentina", "conference league", "football", True),
        ("Argentina vs France", "fifa world cup", "football", True),
        ("Anh vs Đức", "giao huu quoc te", "football", True),
        ("Tây Ban Nha vs Ý", "uefa nations league", "football", True),
        ("Sinner vs Alcaraz", "atp wimbledon", "tennis", True),
    ]
    print("\n🧪 TEST FILTER:")
    ok = 0
    for name, container, sport, expected in tests:
        result = should_keep(name, sport, container)
        status = "✅" if result == expected else "❌"
        if result == expected:
            ok += 1
        print(f"  {status} [{result}] sport={sport:10s} | {name[:48]} | {container[:35]}")
    print(f"\n📊 {ok}/{len(tests)} PASS\n")


# ==========================================
# HÀM GOTO XỬ LÝ REDIRECT
# ==========================================
def goto_with_redirect(page, url, timeout=DOMAIN_TIMEOUT):
    """
    Truy cập URL và chờ redirect hoàn tất.
    Trả về (final_url, success).
    """
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")

        # Chờ JS redirect chạy xong - poll URL tối đa 8s
        for _ in range(32):
            page.wait_for_timeout(250)
            # Nếu URL khác biệt và có pathname rõ ràng → OK
            cur = page.url
            if cur and cur != url and cur != "about:blank":
                # Đợi thêm 1s cho trang mới ổn định
                page.wait_for_timeout(1000)
                return page.url, True

        # Nếu URL không đổi → coi như không redirect, vẫn OK
        return page.url, True
    except Exception as e:
        print(f"     ⚠️ goto fail: {str(e)[:90]}", flush=True)
        return None, False


# ==========================================
# MAIN
# ==========================================
def san_full_server_qua_proxy():
    # _test_filter()  # <-- Bỏ comment để test filter
    print("🚀 BẮT ĐẦU QUÉT XOILAC", flush=True)
    print(f"   → Bóng đá (nam) + Tennis", flush=True)
    print(f"   → Top 5 châu Âu cấp 1 + C1/C2/C3 + WC/Euro/Nation League + giao hữu EU", flush=True)
    print(f"   → Loại: Nữ, Trẻ, Hạng 2+, môn khác", flush=True)

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
                    stats = {"total": 0, "other_sport": 0, "excluded": 0,
                             "not_whitelisted": 0, "time_out": 0, "kept": 0}
                    for item in danh_sach_raw:
                        stats["total"] += 1
                        url = item.get('url', '')
                        ten = item.get('ten', '').strip()
                        sport = item.get('sport', '')
                        container_text = item.get('container', '')

                        if not url or url == url_goc or url == url_goc + "/":
                            continue

                        combined = f"{ten} {container_text}"
                        sport_detected = detect_sport(ten, sport)

                        if sport_detected == "other":
                            stats["other_sport"] += 1
                            continue
                        if is_other_sport(combined):
                            stats["other_sport"] += 1
                            continue
                        if is_hard_excluded(combined):
                            stats["excluded"] += 1
                            continue
                        if not should_keep(ten, sport, container_text):
                            stats["not_whitelisted"] += 1
                            continue
                        if not is_within_24h(container_text):
                            stats["time_out"] += 1
                            continue

                        if url not in result or len(ten) > len(result.get(url, {}).get('ten', '')):
                            stats["kept"] += 1
                            result[url] = {
                                'ten': ten if ten else "Trận đấu",
                                'thumb': item.get('thumb',
                                                  'https://img.icons8.com/color/512/football2.png'),
                                'sport': sport_detected if sport_detected != "unknown" else "football",
                            }

                    print(f"     🔎 Lọc: tổng {stats['total']} → "
                          f"môn khác={stats['other_sport']} | "
                          f"cấm={stats['excluded']} | "
                          f"không whitelist={stats['not_whitelisted']} | "
                          f"quá 24h={stats['time_out']} | "
                          f"**giữ={stats['kept']}**", flush=True)
                    return result

                def click_xem_them_loop(page, max_clicks=MAX_XEM_THEM_CLICKS):
                    clicked = 0
                    for i in range(max_clicks):
                        count_before = page.evaluate(
                            "document.querySelectorAll('.grid-matches__item, .match-horizontals-item').length")
                        btn_found = page.evaluate("""
                            () => {
                                const patterns = ['XEM THÊM', 'Xem thêm', 'Tải thêm'];
                                const candidates = document.querySelectorAll(
                                    'button, a, div[role="button"], span[role="button"], .btn, [class*="load-more"], [class*="loadmore"]');
                                for (const el of candidates) {
                                    const t = (el.innerText || '').trim();
                                    if (patterns.includes(t) || /xem\\s*th[eê]m/i.test(t)) {
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
                            break
                        try:
                            page.click('[data-ext-xemthem="1"]', timeout=5000)
                        except Exception:
                            try:
                                page.get_by_text("XEM THÊM", exact=False).first.click(timeout=5000)
                            except Exception:
                                break
                        try:
                            page.wait_for_function(
                                f"document.querySelectorAll('.grid-matches__item, .match-horizontals-item').length > {count_before}",
                                timeout=8000)
                        except Exception:
                            break
                        count_after = page.evaluate(
                            "document.querySelectorAll('.grid-matches__item, .match-horizontals-item').length")
                        clicked += 1
                        print(f"     🔽 Click #{clicked}: {count_before} → {count_after} trận",
                              flush=True)
                        if count_after <= count_before:
                            break
                        try:
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            page.wait_for_timeout(500)
                        except Exception:
                            pass
                    return clicked

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

                def detect_server_buttons(page):
                    return page.evaluate("""
                        () => {
                            const btns = [];
                            const seen = new Set();
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
                            buttons = [{'idx': '0', 'label': 'Server 1', 'selector': 'body'}]
                        print(f"     📺 {len(buttons)} server: {[b['label'] for b in buttons]}",
                              flush=True)

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
                                print(f"        ⚠️ [{btn['label']}] {str(e)[:60]}", flush=True)
                            finally:
                                page.remove_listener("request", handle)

                            if target_url[0] and target_url[0] not in seen_urls:
                                seen_urls.add(target_url[0])
                                streams.append({"label": btn["label"], "url": target_url[0]})
                                print(f"        ✅ [{btn['label']}] "
                                      f"{target_url[0][:75]}", flush=True)
                            else:
                                print(f"        ⛔ [{btn['label']}] no stream", flush=True)
                    except Exception as e:
                        print(f"     ⚠️ {str(e)[:80]}", flush=True)
                    return streams

                # ==========================================
                # QUÉT 1 SERVER (đã fix redirect)
                # ==========================================
                def quet_trang(ten_nhom, url_trang_chu, keyword_link, kieu_quet=""):
                    nonlocal so_tram_loi_vong_nay, so_tram_ok_vong_nay
                    page = context.new_page()
                    print(f"\n📥 QUÉT: {ten_nhom.upper()}", flush=True)
                    ket_qua_tram = []

                    try:
                        url_dung = None
                        for domain in XOILAC_DOMAINS:
                            print(f"   🔗 Thử: {domain}", flush=True)
                            final_url, ok = goto_with_redirect(page, domain)

                            if not ok or not final_url:
                                continue

                            # Log redirect
                            if final_url != domain:
                                print(f"     🔄 Redirect → {final_url}", flush=True)

                            # Check Cloudflare challenge
                            title = (page.title() or "").lower()
                            if "just a moment" in title or "checking your browser" in title:
                                print(f"     🛡️ Cloudflare challenge", flush=True)
                                continue

                            # Chờ selector của trang chủ
                            try:
                                page.wait_for_function(
                                    f"document.querySelectorAll('a[href*=\"{keyword_link}\"]').length > 0",
                                    timeout=15000)
                                url_dung = final_url
                                print(f"   ✅ Sống: {final_url}", flush=True)
                                break
                            except Exception:
                                print(f"     ❌ Không tìm thấy link trận đấu", flush=True)
                                continue

                        if not url_dung:
                            raise Exception("Tất cả domain đều chết!")

                        page.wait_for_timeout(2000)
                        print(f"   🔽 Click XEM THÊM...", flush=True)
                        n_clicks = click_xem_them_loop(page)
                        print(f"   ✅ Đã click {n_clicks} lần", flush=True)

                        danh_sach_phong = lay_phong_xoilac(page, url_dung, keyword_link)
                        print(f"🎯 {ten_nhom}: {len(danh_sach_phong)} phòng", flush=True)

                        for stt, (link_phong, data_phong) in enumerate(danh_sach_phong.items(), 1):
                            ten_tran = format_match_name(data_phong['ten'])   # <-- format tên ở đây
                            anh_thumb = data_phong['thumb']
                            sport_key = data_phong.get('sport', '')
                            mon_vn = "Tennis" if sport_key == "tennis" else "Bóng đá"
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
                        print("🚫 Proxy chết!", flush=True)
                        break

                browser.close()
        except Exception as e:
            print(f"🔥 Lỗi hệ thống: {e}", flush=True)

        print(f"\n📊 Vòng {lan_thu}: ✅ {so_tram_ok_vong_nay} OK, "
              f"❌ {so_tram_loi_vong_nay} fail", flush=True)
        print(f"📊 Tích lũy: {len(danh_sach_phat)} luồng", flush=True)

        if so_tram_ok_vong_nay == 0 and so_tram_loi_vong_nay > 0 and lan_thu < MAX_RETRIES:
            print("⚠️ Ngủ 30s...", flush=True)
            time.sleep(30)
            continue

        if len(server_da_thanh_cong) < len(TAT_CA_SERVER) and lan_thu < MAX_RETRIES:
            print(f"🔄 Ngủ 30s...", flush=True)
            time.sleep(30)
            continue

        break

    # ==========================================
    # XUẤT M3U
    # ==========================================
    seen = set()
    # KHÔNG lọc trùng theo link nữa — giữ nguyên tất cả các trận khác nhau
    danh_sach_sach = danh_sach_phat

    if danh_sach_sach:
        da_loc = len(danh_sach_phat) - len(danh_sach_sach)
        if da_loc > 0:
            print(f"🧹 Lọc {da_loc} link trùng.", flush=True)

        print(f"\n📦 Ghi M3U...", flush=True)
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

        print(f"🎉 TỔNG {len(danh_sach_sach)} TRẬN/LUỒNG!", flush=True)

        nhom_count = {}
        for l in danh_sach_sach:
            nhom_count[l['nhom']] = nhom_count.get(l['nhom'], 0) + 1
        print(f"📊 {', '.join(f'{k}: {v}' for k, v in nhom_count.items())}", flush=True)

        server_count = {}
        for l in danh_sach_sach:
            srv = l.get('server', '') or '(mặc định)'
            server_count[srv] = server_count.get(srv, 0) + 1
        print(f"📺 Server con: {', '.join(f'{k}: {v}' for k, v in server_count.items())}",
              flush=True)
    else:
        print(f"❌ Không có luồng!", flush=True)
        with open("tong_hop_bong_da.m3u", "w", encoding="utf-8") as file:
            file.write("#EXTM3U\n")


if __name__ == "__main__":
    san_full_server_qua_proxy()
