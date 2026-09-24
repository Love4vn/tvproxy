"""
🎯 SĂN LINK XOILAC - Final v11
✅ Tổng hợp v10.1 → v10.5:
   - ĐTQG châu Âu ưu tiên giữ (Bồ Đào Nha vs Wales, Na Uy vs Đan Mạch...)
   - Format tên: "X vs Y | HH:MM | DD/MM/YYYY"
   - Không lọc trùng link giữa các trận
   - Blacklist Áo, Ấn Độ mở rộng
   - Tennis luôn giữ
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
DOMAIN_TIMEOUT = 25000
STREAM_WAIT_TRIES = 40
STREAM_WAIT_STEP_MS = 250
HOURS_AHEAD = 24
MAX_XEM_THEM_CLICKS = 15

# Debug
DEBUG_SHOW_REJECTED = True
DEBUG_REJECTED_LIMIT = 15
DEBUG_SHOW_KEPT = True
DEBUG_KEPT_LIMIT = 10

TAT_CA_SERVER = [
    ("Xoilac", "https://xoilacz.io", "/truc-tiep/", "xoilac"),
]

XOILAC_DOMAINS = [
    "https://xoilacz.io",
    "https://xoilaczzf.cc",
    "https://xoilaczzb.cc",
    "https://xoilaczzc.cc",
    "https://xoilaczzd.cc",
    "https://xoilaczzh.cc",
    "https://xoilacxth.tv",
    "https://xoilacxbi.tv",
    "https://xoilac7tv.tv",
    "https://xoilacvvr.tv",
]

# ==========================================
# HELPERS
# ==========================================
def normalize_vn(text):
    if not text:
        return ""
    text = str(text).lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = text.replace('đ', 'd')
    return text


def format_match_name(name):
    """
    'Hà Lan vs Đức lúc 01:45 ngày 25/09/2026'
    → 'Hà Lan vs Đức | 01:45 | 25/09/2026'
    """
    if not name:
        return name
    m = re.match(
        r'^(.*?)\s+lúc\s+(\d{1,2}:\d{2})\s+ngày\s+(\d{1,2}/\d{1,2}(?:/\d{4})?)$',
        name, re.IGNORECASE)
    if m:
        return f"{m.group(1).strip()} | {m.group(2)} | {m.group(3)}"
    return name


# ==========================================
# ⭐ WHITELIST CLB TOP 5
# ==========================================
TOP_TEAMS = [
    # ANH
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton",
    "chelsea", "coventry", "crystal palace", "everton", "fulham",
    "hull city", "ipswich", "leicester", "liverpool",
    "man city", "manchester city",
    "man united", "man utd", "manchester united",
    "newcastle", "nottingham forest", "southampton",
    "tottenham",
    # ĐỨC
    "augsburg", "bayer leverkusen", "leverkusen",
    "bayern munich", "bayern munchen", "bayern",
    "bochum",
    "borussia dortmund", "dortmund", "bvb",
    "borussia monchengladbach", "monchengladbach", "gladbach",
    "eintracht frankfurt", "frankfurt",
    "freiburg", "heidenheim", "hoffenheim",
    "holstein kiel", "kiel",
    "mainz",
    "rb leipzig", "leipzig",
    "st. pauli", "st pauli",
    "stuttgart", "union berlin",
    "werder bremen", "werder", "wolfsburg",
    # TBN
    "alaves", "athletic bilbao", "athletic club",
    "atletico madrid", "atletico",
    "barcelona", "barca",
    "celta vigo", "celta",
    "espanyol", "getafe", "girona",
    "las palmas", "leganes", "mallorca", "osasuna",
    "rayo vallecano",
    "real betis", "betis",
    "real madrid", "real sociedad",
    "sevilla", "valencia", "valladolid", "villarreal",
    # Ý
    "atalanta", "bologna", "cagliari", "como", "empoli",
    "fiorentina", "genoa", "hellas verona",
    "inter milan",
    "juventus", "juve",
    "lazio", "lecce",
    "ac milan",
    "monza", "napoli", "parma",
    "roma",
    "torino", "udinese", "venezia",
    # PHÁP
    "angers", "auxerre", "brest", "le havre",
    "rc lens",
    "lille", "lyon", "olympique lyonnais",
    "marseille", "olympique marseille",
    "as monaco",
    "montpellier", "nantes",
    "ogc nice",
    "paris saint-germain", "paris sg", "psg",
    "reims", "rennes", "stade rennais",
    "saint-etienne", "saint etienne",
    "strasbourg", "toulouse",
]

# ==========================================
# 🎾 TENNIS
# ==========================================
TENNIS_KEYWORDS = [
    "tennis", "quan vot", "atp", "wta",
    "grand slam", "wimbledon", "roland garros",
    "us open", "australian open", "atp tour", "wta tour",
    "davis cup", "billie jean king cup", "fed cup",
]

# ==========================================
# 🚫 OTHER SPORTS
# ==========================================
OTHER_SPORT_KEYWORDS = [
    r"\bbasketball\b", r"\bbong\s*ro\b", r"\bnba\b", r"\beuroleague\b",
    r"\beuro\s*league\b", r"\bbbl\b", r"\bnbb\b", r"\bacb\b",
    r"\bbrose\s*bamberg\b", r"\balba\b", r"\bldlc\b", r"\bfiba\b",
    r"\bvolleyball\b", r"\bbong\s*chuyen\b", r"\bvnl\b",
    r"\bbadminton\b", r"\bcau\s*long\b", r"\bbwf\b",
    r"\btable\s*tennis\b", r"\bbong\s*ban\b", r"\bwtt\b",
    r"\besports?\b", r"\blol\b", r"\bleague\s*of\s*legends\b",
    r"\bdota\s*2?\b", r"\bcs\s*:?\s*go\b", r"\bcsgo\b",
    r"\bvalorant\b", r"\bpubg\b", r"\bmobile\s*legends\b",
    r"\bbaseball\b", r"\bbong\s*chay\b", r"\bmlb\b",
    r"\bhandball\b", r"\bbong\s*nem\b",
    r"\bhockey\b", r"\bkhuc\s*con\s*cau\b", r"\bnhl\b",
    r"\brugby\b", r"\bcricket\b", r"\bgolf\b", r"\bbilliards\b",
    r"\bsnooker\b", r"\bdart\b", r"\bformula\s*1\b", r"\bf1\b",
]

# ==========================================
# 🚫 HARD EXCLUDE
# ==========================================
HARD_EXCLUDE_PATTERNS = [
    # Nữ / Trẻ / Dự bị / Huyền thoại
    r"\bnu\b", r"\bwomen\b", r"\bfemale\b", r"\bladies\b",
    r"\bdamen\b", r"\bfeminine\b", r"\bfemenil\b", r"\bfeminino\b",
    r"\bu\d{2}\b", r"\bu-\d{2}\b", r"\bunder\s*\d{2}\b",
    r"\byouth\b", r"\bjunior\b", r"\btre\b", r"\breserve\b",
    r"\bacademy\b", r"\bhoc\s*vien\b", r"\bdoi\s*b\b",
    r"\blegends?\b", r"\bhuyen\s*thoai\b", r"\bold\s*boys\b",

    # ĐỘI B
    r"\bcastilla\b", r"\bmestalla\b", r"\bpromesas\b",
    r"\bbilbao\s*athletic\b", r"\bsevilla\s*atletico\b",
    r"\bbarca\s*b\b", r"\bbarcelona\s*b\b",
    r"\breal\s*madrid\s*b\b", r"\breal\s*madrid\s*castilla\b",
    r"\batletico\s*madrid\s*b\b",
    r"\bvillarreal\s*b\b", r"\bcelta\s*b\b",
    r"\breal\s*sociedad\s*b\b",
    r"\bathletic\s*bilbao\s*b\b",

    # CLB nước ngoài đã lọt
    r"\balianza\b", r"\bsport\s*boys\b",
    r"\blippstadt\b", r"\bsant\s*andreu\b",
    r"\btembetary\b", r"\biteno\b", r"\bsportivo\b",
    r"\bsporting\s*cristal\b", r"\bcristal\b",
    r"\bad\s*tarma\b", r"\btarma\b",
    r"\bmohammedan\b", r"\beast\s*bengal\b", r"\bbengal\b",
    r"\bbombay\b", r"\bmumbai\b", r"\bnavanagar\b",
    r"\bgymkhana\b", r"\bifa\s*shield\b",
    r"\bsuper\s*division\b", r"\bindia\s*super\b",

    # ⭐ v10.2: Ấn Độ mở rộng
    r"\bsreenidi\b", r"\bdeccan\b",
    r"\bnortheast\s*united\b", r"\bnortheast\b",
    r"\bkerala\b", r"\bbengaluru\b", r"\bchennaiyin\b",
    r"\bgoa\b", r"\bhyderabad\b", r"\bodisha\b",
    r"\bjamshedpur\b", r"\bmumbai\s*city\b", r"\bpunjab\s*fc\b",
    r"\bsc\s*east\s*bengal\b", r"\batk\b", r"\bmohun\s*bagan\b",
    r"\bmohunbagan\b", r"\bgokulam\b", r"\bchurchill\b",
    r"\bdempo\b", r"\bsalgaocar\b", r"\bsporting\s*goa\b",
    r"\bshree\b", r"\bminerva\b", r"\baizawl\b", r"\bneroca\b",
    r"\brajasthan\b",

    # ⭐ v10.4: Áo
    r"\baustria\b", r"\bbundesliga\s*ao\b", r"\bbundesliga\s*austria\b",
    r"\boesterreich\b", r"\bosterreich\b",
    r"\bhartberg\b", r"\bkapfenberg\b", r"\bsturm\s*graz\b",
    r"\brapid\s*wien\b", r"\baustria\s*wien\b", r"\bred\s*bull\s*salzburg\b",
    r"\bsalzburg\b", r"\blask\b", r"\bwolfsberger\b", r"\baltach\b",
    r"\bried\b", r"\bklagenfurt\b", r"\bblau\s*weiss\b", r"\bwattens\b",

    # Amateur prefix
    r"\basc\s*\d{1,3}\b",
    r"\btsv\s*\d{1,3}\b",
    r"\bfsv\s*\d{1,3}\b",
    r"\bspvgg\s*\d{1,3}\b",
    r"\bsc\s*\d{1,3}\b",
    r"\bfc\s*\d{1,3}\b",

    # Hạng 3-9
    r"\bhang\s*[3-9]\b",
    r"\bhang\s*(ba|bon|tu|nam|sau|bay|tam|chin)\b",
    r"\bprimera\s*federacion\b", r"\bsegunda\s*federacion\b",
    r"\btercera\s*federacion\b",
    r"\bprimera\s*rfef\b", r"\bsegunda\s*rfef\b", r"\btercera\s*rfef\b",

    # Hạng 2 top 5
    r"hang\s*(2|hai|nhi)\s*[^\w]*(duc|bundesliga|germany)",
    r"hang\s*(2|hai|nhi)\s*[^\w]*(anh|england)",
    r"hang\s*(2|hai|nhi)\s*[^\w]*(y\b|italia|italy)",
    r"hang\s*(2|hai|nhi)\s*[^\w]*(phap|france)",
    r"hang\s*(2|hai|nhi)\s*[^\w]*(tbn|tay\s*ban\s*nha|spain)",
    r"2\.?\s*bundesliga", r"bundesliga\s*2\b", r"bundesliga\s*zwei",
    r"\bserie\s*b\b", r"\bligue\s*2\b",
    r"\bla\s*liga\s*2\b", r"\blaliga\s*2\b",
    r"\bsegunda\b", r"\bsegunda\s*division\b",
    r"\befl\s*championship\b", r"\bchampionship\b",
    r"\bleague\s*one\b", r"\bleague\s*two\b",
    r"\bregionalliga\b", r"\b3\.?\s*liga\b",
    r"\bchallenger\s*pro\b", r"\bk\s*league\s*2\b",

    # Hạng 3+ Đức
    r"\bd\s*[1-9]\b[\s\S]{0,80}(duc|germany|bundesliga|oberliga|westfalen)",
    r"\bd\s*[1-9]\s*(duc|germany|hang)",
    r"\boberliga\b", r"\bverbandsliga\b", r"\bkreisliga\b",
    r"\blandesliga\b", r"\bwestfalen\b", r"\bniederrhein\b",
    r"\bbayernliga\b", r"\bhessenliga\b", r"\bberlinliga\b",
    r"\bnordost\b", r"\bsudwest\b", r"\bnordliga\b", r"\bsudliga\b",

    # Anh hạng thấp
    r"\bnorthern\s*premier\b", r"\bnorthern\s*league\b",
    r"\bsouthern\s*premier\b", r"\bsouthern\s*league\b",
    r"\bisthmian\b", r"\bnpl\b", r"\bspl\b",
    r"\bpremier\s*division\b",
    r"\bcounty\s*league\b", r"\bnon[-\s]?league\b",
    r"\bcombinations?\b",

    # Trung Quốc
    r"\bchinese\b", r"\bcmcl\b", r"\bchina\s*championship\b",
    r"\bchina\s*league\b", r"\bchina\s*cup\b",
    r"\bliaoning\b", r"\bxinjiang\b", r"\bguangdong\b",
    r"\bsichuan\b", r"\bshaanxi\b", r"\bqingdao\b",
    r"\bwuhan\b", r"\bchongqing\b", r"\bjiangsu\b",
    r"\bshenzhen\b", r"\bdalian\b", r"\bguangzhou\b",
    r"\bshanghai\b", r"\bbeijing\b", r"\btianjin\b",
    r"\bhebei\b", r"\bshandong\b", r"\bzhejiang\b",
    r"\bhenan\b", r"\byunnan\b", r"\bxi'?an\b",

    # Ấn Độ cơ bản
    r"\bshillong\b", r"\bindian\b", r"\bindia\b", r"\bisl\b",
    r"\bi[-\s]?league\b", r"\bsantosh\b",

    # Nam Mỹ
    r"\bperu\b", r"\bperuvian\b",
    r"\bparaguay\b", r"\bparaguayan\b",
    r"\bclausura\b", r"\bapertura\b",
    r"\bcopa\s*sudamericana\b",
    r"\bcopa\s*de\s*la\s*liga\b",
    r"\bcopa\s*paraguay\b",
    r"\bprimera\s*division\s*(peru|paraguay|chile|colombia|ecuador|uruguay|bolivia|venezuela)",
    r"\bliga\s*1\s*(peru|chile|paraguay|colombia|ecuador|uruguay|bolivia|mexico)",
    r"\bdivision\s*profesional\b",
    r"\bcup\s*quoc\s*gia\s*(paraguay|peru|chile|colombia|ecuador|uruguay|bolivia|venezuela|brazil|argentina|mexico|nhat|han|trung)",

    # Quốc gia nhỏ
    r"\bsaint\s*kitts\b", r"\bnevis\b",
    r"\bbhutan\b", r"\bsri\s*lanka\b",
    r"\bgibraltar\b", r"\bfaroe\b",
    r"\bsomalia\b", r"\bzanzibar\b", r"\bethiopia\b", r"\beritrea\b",
    r"\bwelsh\b", r"\bscottish\b", r"\bnorthern\s*ireland\b",

    # Châu Á (còn lại)
    r"\bthai\s*land\b", r"\bthai\s*league\b",
    r"\bmalaysia\b", r"\bindonesia\b", r"\bphilippines\b",
    r"\bsingapore\b", r"\bmyanmar\b", r"\bcambodia\b", r"\bcampuchia\b",
    r"\btrung\s*quoc\b",
    r"\bnhat\b", r"\bjapan\b", r"\bj\s*league\b", r"\bj1\b", r"\bj2\b",
    r"\bhan\s*quoc\b", r"\bkorea\b", r"\bk\s*league\b",
    r"\ban\s*do\b",
    r"\biran\b", r"\biraq\b", r"\bsaudi\b", r"\barab\b", r"\ba\s*rap\b",
    r"\buae\b", r"\bqatar\b", r"\bkuwait\b", r"\bbahrain\b", r"\boman\b",
    r"\buzbekistan\b", r"\bkazakhstan\b", r"\bkyrgyz\b", r"\btajikistan\b",
    r"\bviet\s*nam\b", r"\bv\.?\s*league\b", r"\bvleague\b",
    r"\bafc\s*champions\b", r"\bafc\s*cup\b",

    # ⭐ v10: Bangladesh + Nam Á
    r"\bbangladesh\b", r"\bchattogram\b", r"\bdhaka\b",
    r"\bcomilla\b", r"\bsylhet\b", r"\brajshahi\b", r"\bkhulna\b",
    r"\bbashundhara\b", r"\bmohammedan\s*dhaka\b",
    r"\bafghanistan\b", r"\bnepal\b", r"\bpakistan\b",

    # Châu Mỹ
    r"\bvenezuela\b", r"\bbrasil\b", r"\bbrazil\b", r"\bbrasileir[ao]\b",
    r"\bargentina\b", r"\bprimera\s*division\b",
    r"\bmexico\b", r"\bliga\s*mx\b", r"\bmls\b",
    r"\bchile\b", r"\bcolombia\b", r"\becuador\b",
    r"\buruguay\b", r"\bbolivia\b",
    r"\bcosta\s*rica\b", r"\bhonduras\b", r"\bguatemala\b", r"\bpanama\b",
    r"\bconcacaf\b", r"\bcopa\s*america\b", r"\bcopa\s*libertadores\b",
    r"\bconcacaf\s*champions\b", r"\bleagues\s*cup\b", r"\bcanada\b",
    r"\bcanadian\s*premier\b",

    # Châu Phi
    r"\begypt\b", r"\bai\s*cap\b", r"\bmaroc\b", r"\bmorocco\b",
    r"\btunisia\b", r"\balgeria\b", r"\bnam\s*phi\b", r"\bsouth\s*africa\b",
    r"\bnigeria\b", r"\bghana\b", r"\bcaf\b", r"\bafcon\b",
    r"\bcaf\s*champions\b", r"\bsudan\b", r"\btanzania\b",
    r"\bnambia\b", r"\bcongo\b", r"\bnamibia\b",

    # Châu Đại Dương
    r"\baustralia\b", r"\ba[-\s]?league\b", r"\bnew\s*zealand\b",
    r"\btimor\s*leste\b", r"\btimor\b",

    # Châu Âu không top 5
    r"\bczech\b", r"\bsec\b", r"\bfortuna\s*liga\b", r"\bchance\s*liga\b",
    r"\bthuy\s*si\b", r"\bswitzerland\b",
    r"\bbelgium\b", r"\bpro\s*league\s*bi\b", r"\bjupiler\b",
    r"\bholland\b", r"\bnetherlands\b", r"\beredivisie\b",
    r"\bportugal\b", r"\bbo\s*dao\s*nha\b", r"\bprimeira\s*liga\b",
    r"\bturkey\b", r"\btho\s*nhi\s*ky\b", r"\bsuper\s*lig\b",
    r"\bscotland\b", r"\bwales\b",
    r"\bireland\b",
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
# ✅ WHITELIST GIẢI
# ==========================================
TOP_LEAGUE_PATTERNS = [
    r"\bpremier\s*league\b", r"\bngoai\s*hang\s*anh\b", r"\bepl\b",
    r"\bla\s*liga\b(?!\s*2)", r"\blaliga\b(?!\s*2)",
    # ⭐ v10.4: Không match Bundesliga Áo
    r"\bbundesliga\b(?!\s*2)(?!\s*zwei)(?!\s*ao)(?!\s*austria)(?!\s*oesterreich)",
    r"\bserie\s*a\b(?!\s*b)",
    r"\bligue\s*1\b",
    r"\bchampions\s*league\b", r"\buefa\s*champions\b",
    r"\bcup\s*c1\b", r"\bcup\s*1\b", r"\bucl\b",
    r"\beuropa\s*league\b", r"\bcup\s*c2\b", r"\buel\b",
    r"\bconference\s*league\b", r"\bcup\s*c3\b", r"\buecl\b",
    r"\bsieu\s*cup\s*chau\s*au\b", r"\bsuper\s*cup\s*uefa\b",
    r"\buefa\s*super\s*cup\b",
    r"\bworld\s*cup\b", r"\bfifa\s*world\s*cup\b", r"\bworldcup\b",
    r"\buefa\s*euro\b", r"\beuro\s*20\d{2}\b",
    r"\beuro\s*championship\b", r"\beuro\s*cup\b",
    r"\buefa\s*nations\s*league\b", r"\bnations\s*league\b",
    r"\buefa\s*nations\b", r"\buefa\s*nl\b",
]

# ⭐ v10.3: Mở rộng EURO_COUNTRIES
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
    "israel",
    "xu wales",
    "liechtenstein",
    "lithuania", "litva",
    "latvia", "lativia",
    "estonia",
    "kosovo",
    "montenegro",
    "albania",
    "macedonia", "bac macedonia",
    "bosnia", "bosnia and herzegovina",
    "iceland", "ai len",
    "malta",
    "luxembourg",
    "cyprus", "dao sip", "sec",
    "moldova",
    "belarus",
    "georgia",
    "armenia",
    "azerbaijan",
    "andorra",
    "san marino",
    "faroe", "quan dao faroe",
    "gibraltar",
}

FRIENDLY_KEYWORDS = ("giao huu", "friendly", "friendlies")


# ==========================================
# LOGIC
# ==========================================
def is_other_sport(text):
    if not text:
        return False
    t = normalize_vn(text)
    return any(re.search(p, t, re.IGNORECASE) for p in OTHER_SPORT_KEYWORDS)


def is_hard_excluded(text):
    if not text:
        return False
    t = normalize_vn(text)
    return any(re.search(p, t, re.IGNORECASE) for p in HARD_EXCLUDE_PATTERNS)


def contains_top_league(text):
    if not text:
        return False
    t = normalize_vn(text)
    return any(re.search(p, t, re.IGNORECASE) for p in TOP_LEAGUE_PATTERNS)


def contains_top_team(text):
    """⭐ v10: Bỏ qua đội B/C và đội amateur (có số trước)"""
    if not text:
        return False
    t = normalize_vn(text)
    for team in TOP_TEAMS:
        pattern = rf'(?<![a-z0-9]){re.escape(team)}(?![a-z0-9])'
        for m in re.finditer(pattern, t):
            prefix = t[max(0, m.start()-10):m.start()]
            # Bỏ qua đội amateur có số trước (ASC 09 Dortmund)
            if re.search(r'\d{1,4}\s*$', prefix):
                continue
            # ⭐ v10: Bỏ qua đội B/C (Las Palmas C, Barcelona B)
            suffix = t[m.end():m.end()+4]
            if re.match(r'\s+[bc]\b', suffix):
                continue
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


def is_tennis_text(text):
    if not text:
        return False
    t = normalize_vn(text)
    return any(kw in t for kw in TENNIS_KEYWORDS)


def is_euro_international_container(text):
    """⭐ v10.3: Container có dấu hiệu ĐTQG châu Âu"""
    if not text:
        return False
    t = normalize_vn(text)
    patterns = [
        r"\buefa\s*nl\b", r"\buefa\s*nations\b", r"\bnations\s*league\b",
        r"\buefa\s*euro\b", r"\beuro\s*20\d{2}\b", r"\beuro\s*championship\b",
        r"\bworld\s*cup\b", r"\bfifa\s*world\b",
        r"\bfriendly\b", r"\bgiao\s*huu\b", r"\bfriendlies\b",
        r"\bwc\s*qualif", r"\beuro\s*qualif",
    ]
    return any(re.search(p, t, re.IGNORECASE) for p in patterns)


def is_youth_or_women(name):
    """⭐ v10.3: Check U/Trẻ/Nữ"""
    if not name:
        return False
    t = normalize_vn(name)
    patterns = [r"\bu\s*\d{2}\b", r"\bnu\b", r"\bwomen\b", r"\bfemale\b",
                r"\byouth\b", r"\bjunior\b", r"\btre\b"]
    return any(re.search(p, t, re.IGNORECASE) for p in patterns)


def both_are_euro_countries(name):
    """
    ⭐ v10.5: Cả 2 đội trong tên đều là quốc gia châu Âu.
    VD: 'Na Uy vs Đan Mạch' → True
    """
    if not name:
        return False
    t = normalize_vn(name)
    # Bỏ "lúc HH:MM ngày DD/MM"
    t = re.sub(r'\s+luc\s+\d{1,2}:\d{2}\s+ngay\s+\d{1,2}/\d{1,2}(/\d{4})?', '', t)
    parts = re.split(r'\s+vs\s+', t)
    if len(parts) < 2:
        return False
    for part in parts[:2]:
        part = part.strip()
        found = False
        for country in EURO_COUNTRIES:
            if re.search(rf'\b{re.escape(country)}\b', part):
                found = True
                break
        if not found:
            return False
    return True


def detect_sport(name="", sport_hint="", container=""):
    hint = normalize_vn(sport_hint or "").strip()
    if hint in ("football", "soccer", "bong da"):
        return "football"
    if hint in ("tennis", "quan vot"):
        return "tennis"
    if hint and hint not in ("unknown", ""):
        return "other"

    combined = f"{name} {container}"
    if is_tennis_text(combined):
        return "tennis"
    if is_other_sport(combined):
        return "other"
    return "unknown"


def should_keep(name, sport_hint="", container_text=""):
    sport = detect_sport(name, sport_hint, container_text)

    if sport == "other":
        return False
    if sport == "tennis":
        return True

    # ⭐ v10.5: ĐTQG châu Âu (cả 2 đội đều châu Âu)
    if both_are_euro_countries(name) and not is_youth_or_women(name):
        return True

    # ⭐ v10.3: Container có dấu hiệu ĐTQG châu Âu
    if is_euro_international_container(container_text):
        if has_euro_country(name) and not is_youth_or_women(name):
            return True

    combined = f"{name} {container_text}"

    # --- Các check cũ ---
    if is_hard_excluded(name):
        return False
    if is_other_sport(name):
        return False
    if is_other_sport(combined):
        return False
    if is_hard_excluded(combined):
        return False

    if contains_top_team(name) or contains_top_team(container_text):
        return True
    if contains_top_league(combined):
        return True
    if is_friendly(combined) and has_euro_country(combined):
        return True

    return False


# ==========================================
# TIME
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
# M3U HEADER
# ==========================================
REFERER_MAP = {
    "quickscoreboardz.com":     "https://live1.quickscoreboardz.com/",
    "zundrixmediapipeline.com": "https://live2.zundrixmediapipeline.com/",
    "domainkqt.cc":             "https://xl365.domainkqt.cc/",
    "domaincdn.cc":             "https://live2.domaincdn.cc/",
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
# GOTO
# ==========================================
def goto_with_redirect(page, url, timeout=DOMAIN_TIMEOUT):
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        for _ in range(32):
            page.wait_for_timeout(250)
            cur = page.url
            if cur and cur != url and cur != "about:blank":
                page.wait_for_timeout(1000)
                return page.url, True
        return page.url, True
    except Exception as e:
        print(f"     ⚠️ goto fail: {str(e)[:80]}", flush=True)
        return None, False


# ==========================================
# MAIN
# ==========================================
def san_full_server_qua_proxy():
    print("🚀 BẮT ĐẦU QUÉT XOILAC v11", flush=True)

    danh_sach_phat = []
    server_da_thanh_cong = set()

    for lan_thu in range(1, MAX_RETRIES + 1):
        print(f"\n==========================================", flush=True)
        print(f"🔄 VÒNG {lan_thu}/{MAX_RETRIES}", flush=True)
        print(f"==========================================", flush=True)

        server_can_quet = [s for s in TAT_CA_SERVER if s[0] not in server_da_thanh_cong]
        if not server_can_quet:
            print("✅ Xong!", flush=True)
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
                # LỌC (v10.5: gọi should_keep trước)
                # ==========================================
                def _loc_trung(danh_sach_raw, url_goc):
                    result = {}
                    stats = {"total": 0, "other_sport": 0, "excluded": 0,
                             "not_whitelisted": 0, "time_out": 0,
                             "kept": 0, "tennis": 0}
                    rej_shown = 0
                    kept_shown = 0

                    for item in danh_sach_raw:
                        stats["total"] += 1
                        url = item.get('url', '')
                        ten = item.get('ten', '').strip()
                        sport = item.get('sport', '')
                        container_text = item.get('container', '')

                        if not url or url == url_goc or url == url_goc + "/":
                            continue

                        combined = f"{ten} {container_text}"
                        sport_detected = detect_sport(ten, sport, container_text)

                        # ⭐⭐ TENNIS: LUÔN GIỮ ⭐⭐
                        if sport_detected == "tennis":
                            stats["tennis"] += 1
                            stats["kept"] += 1
                            if url not in result or len(ten) > len(result.get(url, {}).get('ten', '')):
                                result[url] = {
                                    'ten': format_match_name(ten) if ten else "Trận tennis",
                                    'thumb': item.get('thumb',
                                                      'https://img.icons8.com/color/512/tennis.png'),
                                    'sport': 'tennis',
                                }
                                if DEBUG_SHOW_KEPT and kept_shown < DEBUG_KEPT_LIMIT:
                                    kept_shown += 1
                                    print(f"     🎾 [TENNIS] {ten[:60]}", flush=True)
                                    print(f"        └─ container: {container_text[:180]}", flush=True)
                            continue

                        # ⭐ OTHER SPORT
                        if sport_detected == "other" or is_other_sport(combined):
                            stats["other_sport"] += 1
                            continue

                        # ⭐ FOOTBALL: gọi should_keep TRƯỚC
                        reason = None
                        if not should_keep(ten, sport, container_text):
                            # Chỉ dùng hard-exclude để log lý do
                            if is_hard_excluded(combined) or is_hard_excluded(ten):
                                reason = "excluded"; stats["excluded"] += 1
                            else:
                                reason = "not_whitelisted"; stats["not_whitelisted"] += 1
                        elif not is_within_24h(container_text):
                            reason = "time_out"; stats["time_out"] += 1

                        if reason is None:
                            stats["kept"] += 1
                            if url not in result or len(ten) > len(result.get(url, {}).get('ten', '')):
                                result[url] = {
                                    'ten': format_match_name(ten) if ten else "Trận đấu",
                                    'thumb': item.get('thumb',
                                                      'https://img.icons8.com/color/512/football2.png'),
                                    'sport': 'football',
                                }
                                if DEBUG_SHOW_KEPT and kept_shown < DEBUG_KEPT_LIMIT:
                                    kept_shown += 1
                                    print(f"     ⚽ [KEPT] {ten[:60]}", flush=True)
                                    print(f"        └─ container: {container_text[:180]}", flush=True)
                        elif DEBUG_SHOW_REJECTED and rej_shown < DEBUG_REJECTED_LIMIT:
                            rej_shown += 1
                            print(f"     ❌ [{reason}] {ten[:55]}", flush=True)

                    print(f"     🔎 Lọc: {stats['total']} → "
                          f"môn khác={stats['other_sport']} | "
                          f"cấm={stats['excluded']} | "
                          f"ko-white={stats['not_whitelisted']} | "
                          f"quá 24h={stats['time_out']} | "
                          f"**giữ={stats['kept']}** (🎾 {stats['tennis']})", flush=True)
                    return result

                # ==========================================
                # CAPTURE ITEMS
                # ==========================================
                def lay_phong_xoilac(page, url_goc, keyword_link):
                    raw = page.evaluate(f"""
                        (() => {{
                            const results = [];

                            const getLeagueContext = (item) => {{
                                const parts = [];
                                parts.push(item.innerText || '');
                                parts.push(item.textContent || '');
                                const leagueEl = item.querySelector(
                                    '.grid-match__league, .grid-matches__league, ' +
                                    '[class*="league-name"], [class*="League__"], ' +
                                    '[class*="tournament"]');
                                if (leagueEl && leagueEl.innerText) parts.push(leagueEl.innerText);

                                let cur = item.parentElement;
                                let depth = 0;
                                while (cur && depth < 6) {{
                                    const header = cur.querySelector(
                                        '.grid-matches__header, .matches__header, ' +
                                        '.matches-header, .matches__group-title, ' +
                                        '.grid-matches__title, .grid-matches__group-title, ' +
                                        '[class*="group-title"], [class*="league-header"], ' +
                                        '[class*="LeagueHeader"], [class*="tournament-header"]'
                                    );
                                    if (header && header.innerText) {{
                                        const t = header.innerText.trim();
                                        if (t.length < 250) parts.push(t);
                                    }}
                                    const cls = (typeof cur.className === 'string') ? cur.className : '';
                                    if (/group|league|tournament|section/i.test(cls)) {{
                                        const t = cur.innerText || '';
                                        if (t.length < 2500) parts.push(t);
                                    }}
                                    cur = cur.parentElement;
                                    depth++;
                                }}
                                return parts.join(' | ');
                            }};

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
                                    container: getLeagueContext(item)
                                }});
                            }});

                            document.querySelectorAll('.match-horizontals-item[href*="{keyword_link}"]').forEach(a => {{
                                if (results.some(r => r.url === a.href)) return;
                                const img = a.querySelector('img');
                                const selfText = [
                                    a.innerText || '',
                                    a.textContent || '',
                                    a.getAttribute('title') || '',
                                    a.getAttribute('data-title') || ''
                                ].join(' | ');
                                results.push({{
                                    url: a.href,
                                    ten: a.innerText.trim().replace(/\\n/g, ' - '),
                                    thumb: img ? img.src : "",
                                    sport: 'football',
                                    container: selfText
                                }});
                            }});
                            return results;
                        }})()
                    """)
                    return _loc_trung(raw, url_goc)

                # ==========================================
                # CLICK XEM THÊM
                # ==========================================
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
                        print(f"     🔽 Click #{clicked}: {count_before} → {count_after}", flush=True)
                        if count_after <= count_before:
                            break
                        try:
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            page.wait_for_timeout(500)
                        except Exception:
                            pass
                    return clicked

                # ==========================================
                # SERVER CON
                # ==========================================
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
                        print(f"     📺 {len(buttons)}: {[b['label'] for b in buttons]}", flush=True)

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
                            except Exception:
                                pass
                            finally:
                                page.remove_listener("request", handle)

                            if target_url[0] and target_url[0] not in seen_urls:
                                seen_urls.add(target_url[0])
                                streams.append({"label": btn["label"], "url": target_url[0]})
                                print(f"        ✅ [{btn['label']}] {target_url[0][:75]}", flush=True)
                            else:
                                print(f"        ⛔ [{btn['label']}] no stream", flush=True)
                    except Exception as e:
                        print(f"     ⚠️ {str(e)[:80]}", flush=True)
                    return streams

                # ==========================================
                # QUÉT
                # ==========================================
                def quet_trang(ten_nhom, url_trang_chu, keyword_link, kieu_quet=""):
                    nonlocal so_tram_loi_vong_nay, so_tram_ok_vong_nay
                    page = context.new_page()
                    print(f"\n📥 QUÉT: {ten_nhom.upper()}", flush=True)
                    ket_qua_tram = []

                    try:
                        url_dung = None
                        for domain in XOILAC_DOMAINS:
                            print(f"   🔗 {domain}", flush=True)
                            final_url, ok = goto_with_redirect(page, domain)
                            if not ok or not final_url:
                                continue
                            if final_url != domain:
                                print(f"     🔄 Redirect → {final_url}", flush=True)

                            title = (page.title() or "").lower()
                            if "just a moment" in title or "checking your browser" in title:
                                print(f"     🛡️ Cloudflare", flush=True)
                                continue

                            try:
                                page.wait_for_function(
                                    f"document.querySelectorAll('a[href*=\"{keyword_link}\"]').length > 0",
                                    timeout=15000)
                                url_dung = final_url
                                print(f"   ✅ Sống", flush=True)
                                break
                            except Exception:
                                continue

                        if not url_dung:
                            raise Exception("Tất cả domain chết!")

                        page.wait_for_timeout(2000)
                        print(f"   🔽 Click XEM THÊM...", flush=True)
                        n_clicks = click_xem_them_loop(page)
                        print(f"   ✅ Đã click {n_clicks} lần", flush=True)

                        danh_sach_phong = lay_phong_xoilac(page, url_dung, keyword_link)
                        print(f"🎯 {ten_nhom}: {len(danh_sach_phong)} phòng", flush=True)

                        for stt, (link_phong, data_phong) in enumerate(danh_sach_phong.items(), 1):
                            ten_tran = data_phong['ten']
                            anh_thumb = data_phong['thumb']
                            sport_key = data_phong.get('sport', '')
                            mon_vn = "Tennis" if sport_key == "tennis" else "Bóng đá"
                            nhom_m3u = f"{ten_nhom} - {mon_vn}"

                            print(f"\n   [{stt}/{len(danh_sach_phong)}] {ten_tran[:70]}", flush=True)

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

        print(f"\n📊 Vòng {lan_thu}: ✅ {so_tram_ok_vong_nay} OK, ❌ {so_tram_loi_vong_nay} fail", flush=True)
        print(f"📊 Tích lũy: {len(danh_sach_phat)} luồng", flush=True)

        if so_tram_ok_vong_nay == 0 and so_tram_loi_vong_nay > 0 and lan_thu < MAX_RETRIES:
            print("⚠️ Ngủ 30s...", flush=True); time.sleep(30); continue

        if len(server_da_thanh_cong) < len(TAT_CA_SERVER) and lan_thu < MAX_RETRIES:
            print(f"🔄 Ngủ 30s...", flush=True); time.sleep(30); continue

        break

    # ==========================================
    # XUẤT M3U — v10.1: KHÔNG lọc trùng link giữa các trận
    # ==========================================
    seen_pairs = set()
    danh_sach_sach = []
    for luong in danh_sach_phat:
        pair = (luong.get('tran', ''), luong['link'])
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            danh_sach_sach.append(luong)

    if danh_sach_sach:
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
    else:
        print(f"❌ Không có luồng!", flush=True)
        with open("tong_hop_bong_da.m3u", "w", encoding="utf-8") as file:
            file.write("#EXTM3U\n")


if __name__ == "__main__":
    san_full_server_qua_proxy()
