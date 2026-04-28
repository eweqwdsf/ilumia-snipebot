import logging
import re
import time

log = logging.getLogger("SnipeBot.Filter")

# ==========================================
# CONFIG
# ==========================================
MAX_ITEM_AGE_SECONDS = 120  # Ignoriere alles älter als 2 Minuten
FILTER_MIN_PRICE = 5.0
FILTER_MAX_PRICE = 100.00

# Wir akzeptieren nur explizite Herrengrößen aus dieser Liste
PERMITTED_SIZES = [
    "s", "m", "l", "xl",
    "small", "medium", "large", "extra large",
    "44", "46", "48", "50", "52", "54"
]

BLACKLIST = [
    "zara", "h&m", "shein", "asos", "defacto", "pull&bear", "primark",
    "damen", "frau", "women", "kids", "kinder", "mädchen", "junge",
    "basic", "skinny", "regular fit", "slim fit", "shorts", "short",
    "Nike Tech Fleece", "Nike Tech", "Vintage Shorts", "Icono", "Homme",
    "Trench", "Coat", "Nike tech", "Puma", "Fila", "Champion"
]

CORE_BRANDS = [
    "nike", "adidas", "lacoste", "ralph lauren", "polo", "bape",
    "corteiz", "chrome hearts", "arcteryx", "stussy", "carhartt",
    "fred perry", "levis", "true religion",
    "umbro", "ellesse", "sergio tacchini", "le coq sportif"
]

# ==========================================
# KEYWORD TIERS
# ==========================================

# Tier S — allein ausreichend für einen Alert
TIER_S = [
    # ── Football Vereine + Hype-Ären ──────────────────────────────────────
    "brazil 2002", "brasilien 2002", "brazil 1998", "brasil 1998", "brasil 2002",
    "juventus 1999", "juventus 2001", "juventus 2002",
    "inter mailand 1998", "inter 2002",
    "ac milan 2002", "milan maldini",
    "real madrid 2002", "real madrid zidane", "real madrid figo",
    "manchester united 1999", "man utd beckham",
    "arsenal 2004", "arsenal invincibles", "arsenal henry",
    "barcelona 2009", "barca ronaldinho",
    "holland 1988", "niederlande oranje",
    "deutschland 1990", "germany 1990",
    "france 1998", "frankreich 1998",
    "argentinien maradona",
    "nigeria 1998",
    "kamerun 2002",
    # ── Nike Football / Trikot-Welt ───────────────────────────────────────
    "nike total 90", "total 90 jacke", "total 90 trikot", "t90",
    "nike mercurial jacke", "nike mercurial vintage",
    "nike anthem", "nike anthem jacket",
    "nike präsentationsjacke", "nike presentation jacket",
    "nike trikotjacke retro",
    "nike air football", "nike park vintage",
    "brazil nike", "brasil nike 2002", "brasilien trikotjacke",
    # ── Nike Tech & Hype-Kollabos ─────────────────────────────────────────
    "nike acg", "acg vintage", "nike acg goretex",
    "nike ispa",
    "nike sportswear tech pack", "tech fleece og",
    "nike nsw",
    "nike x stussy", "nike x off white", "nike x travis scott",
    "nike x supreme", "nike x sacai", "nike x patta",
    "nike x drake", "nike x nocta", "nocta",
    "nike x fragment", "nike x comme des garcons", "nike cdg",
    "nike lab", "nikelab",
    # ── Nike Vintage Sportswear ───────────────────────────────────────────
    "nike challenge court",
    "nike agassi", "nike sampras",
    "nike big swoosh", "nike center swoosh",
    "nike mini swoosh vintage",
    "nike travis scott",
    "nike air vintage crewneck", "nike air pullover 90s",
    # ── Adidas / Sonstige Football Marken ────────────────────────────────
    "adidas originals trefoil retro",
    "umbro drillbody",
    "kappa kombat",
    "lotto 90s",
    "diadora 90s",
    "le coq sportif retro",
    # ── Y2K Hype-Pieces ───────────────────────────────────────────────────
    "nike big swoosh",
    "cp company",
    "arc'teryx", "arcteryx",
    "patagonia synchilla", "patagonia snap-t",
    "north face steep tech",
    "supreme box logo",
    # ── Ralph Lauren / Polo ───────────────────────────────────────────────
    "polo sport", "polo 1992", "polo 1993",
    "polo stadium", "polo stadium 1992",
    "polo snow beach", "snow beach pullover", "snow beach jacke",
    "polo hi tech", "hi tech anorak",
    "polo ski", "polo ski 92",
    "polo cookie", "p-wing", "pwing", "p wing",
    "polo bear", "bear sweater", "polo bear pullover",
    "rl2000", "rl-2000",
    "rlx",
    "polo country", "polo sportsman", "polo suicide ski",
    "aztec ralph lauren", "indian head ralph lauren",
    "ralph lauren beach",
    "rrl double rl", "double rl",
    "purple label",
    "polo cp-93", "cp93", "p-wing stadium",
    "stadium pullover", "stadium jacke",
    "ralph lauren snow beach",
    "iceberg history",
    "versace jeans couture 90s",
    "d&g 2000s",
    "ed hardy",
    "affliction",
    "true religion",
    "evisu",
    "bape", "a bathing ape",
    # ── Adidas Hype-Linien & Kollabos ─────────────────────────────────────
    "adidas x wales bonner", "wales bonner",
    "adidas x gucci", "adidas x prada", "adidas x balenciaga",
    "adidas x yeezy apparel", "yeezy gap", "yeezy season",
    "adidas x bape", "adidas x pharrell",
    "adidas x raf simons",
    "adidas x y-3", "y-3", "yohji yamamoto adidas",
    "adidas spezial", "adidas spzl",
    "adidas originals by",
    "adidas consortium",
    # ── Adidas Football ───────────────────────────────────────────────────
    "adidas equipment",
    "adidas etrusco",
    "adidas real madrid 2002",
    "adidas bayern 2001",
    "adidas deutschland 1990", "adidas dfb 1990",
    "adidas france 1998",
    "adidas argentinien maradona",
    # ── Adidas Vintage Tracksuits & Klassiker ─────────────────────────────
    "adidas firebird",
    "adidas beckenbauer",
    "adidas challenger",
    "adidas lazer",
    "adidas atp",
    "adidas ivan lendl",
    "adidas stefan edberg",
    "adidas trefoil vintage",
    "adidas originals 80s",
    "adidas schwahn",
    # ── Arc'teryx Hardshells ──────────────────────────────────────────────
    "beta ar jacket", "beta ar",
    "alpha sv jacket", "alpha sv",
    "alpha ar",
    "beta lt", "beta sl",
    "theta ar", "theta svx",
    "arc'teryx sidewinder", "arcteryx sidewinder",
    "arcteryx stinger",
    "arc'teryx macai", "macai jacket",
    "arc'teryx therme", "arcteryx therme",
    "arcteryx camosun",
    "arc'teryx sentinel", "arcteryx sentinel",
    "arc'teryx sabre", "arcteryx sabre",
    "arcteryx rush",
    "arc'teryx procline",
    # ── Arc'teryx Insulation ──────────────────────────────────────────────
    "arc'teryx atom lt", "atom lt",
    "atom ar", "atom sl",
    "arcteryx cerium lt", "cerium lt", "cerium sl",
    "arc'teryx thorium ar", "thorium ar",
    "arc'teryx proton", "arcteryx proton",
    "arc'teryx nuclei", "arcteryx nuclei",
    # ── Veilance ──────────────────────────────────────────────────────────
    "veilance", "arcteryx veilance",
    "veilance monitor", "veilance field", "veilance mionn",
    "veilance isogon", "veilance align", "veilance apparat",
    "veilance convex", "veilance anneal",
    # ── Arc'teryx Kollabos ────────────────────────────────────────────────
    "arc'teryx x beams", "arcteryx beams",
    "arc'teryx x palace", "arcteryx palace",
    "arc'teryx x jil sander", "jil sander arcteryx",
    "arc'teryx x system a", "system a arcteryx",
    # ── CP Company Ikonische Pieces ───────────────────────────────────────
    "cp company goggle jacket", "goggle jacket cp",
    "cp goggle hoodie", "cp goggle sweatshirt",
    "cp mille miglia", "mille miglia cp",
    "cp company mille miglia jacket",
    "cp company urban protection", "urban protection series", "ups cp company",
    "cp company metropolis series", "metropolis cp",
    "cmassacritica", "massa critica",
    # ── CP Company Material-Linien ────────────────────────────────────────
    "cp company chrome-r", "chrome r cp",
    "cp company nycra", "cp nycra-r",
    "cp company d.d. shell", "dd shell cp",
    "cp company dyneema",
    "cp company gd shell",
    "cp company 50 fili",
    "cp company metropolis",
    "cp company pro-tek",
    "cp company gore g-type",
    "cp company kan-dye",
    # ── CP Company Vintage-Hype ───────────────────────────────────────────
    "cp company massimo osti", "massimo osti cp",
    "cp company og",
    "cp company made in italy 90s",
    "cp company 80s",
    "cp vintage goggle",
    # ── CP Company Kollabos ───────────────────────────────────────────────
    "cp company x aitor throup", "aitor throup cp",
    "cp company x adidas",
    "cp company x cabinet noir",
    # ── Stüssy Hype-Kollabos ──────────────────────────────────────────────
    "stüssy x nike", "stussy nike",
    "stüssy x dior", "stussy dior",
    "stüssy x birkenstock",
    "stüssy x our legacy", "stussy our legacy",
    "stüssy x martine rose",
    "stüssy x cdg", "stüssy x comme des garcons",
    "stüssy x bape",
    "stüssy x denim tears",
    "stüssy x levi's", "stussy levis",
    "stüssy x converse",
    "stüssy x patta",
    "stüssy x rassvet",
    "stüssy x oakley",
    "stüssy x mitchell & ness",
    "stüssy x tekla",
    "stüssy x mike hill",
    # ── Stüssy Vintage-Hype ───────────────────────────────────────────────
    "stüssy international tribe", "stussy international tribe",
    "stüssy tribe", "stussy tribe",
    "ist stussy",
    "og stussy",
    "stussy old stock",
    "stüssy chapter", "stussy chapter",
    "stüssy made in usa vintage", "stussy made in usa",
    "stussy skull",
    "stussy crown",
    "stussy number 4", "stussy no. 4",
    "shawn stussy",
    "stussy sole",
    # ── Seltene Drops / Status ────────────────────────────────────────────
    "deadstock", "ds unworn", "sample", "player issue", "match worn",
]

# Tier A — starkes Signal (Cut-Indikatoren — greifen wenn Core Brand vorhanden)
TIER_A_CUT = [
    "baggy", "oversized", "wide leg", "boxy", "loose fit", "relaxed fit",
]

# Tier A — explizite Phrasen (gelten immer als Tier A, ohne extra Brand-Check)
TIER_A_EXPLICIT = [
    "track jacket", "windbreaker", "windjacke", "trainingsjacke", "trainingsanzug",
    "tracksuit", "half zip", "halfzip", "full zip", "nylon jacket", "sportjacke",
    "trainingshose", "vintage jersey", "football shirt", "soccer shirt",
    "vintage windbreaker", "vintage zip hoodie", "vintage tracksuit",
    "jogginghose", "jogger", "jogging",
    # ── CP Company Tier A ─────────────────────────────────────────────────
    "cp company lens", "cp lens jacket",
    "cp company lens hoodie", "cp lens pullover",
    "cp company lens cardigan",
    "cp company watchviewer",
    "cp company soft shell",
    "cp company shell-r",
    "cp company re-coloured",
    "cp company garment dyed",
    "cp company overshirt",
    "cp company tactical",
    "cp company cargo",
    "cp company sweatshirt mit linse",
    "cp company crewneck lens",
    # ── Arc'teryx Tier A ──────────────────────────────────────────────────
    "arc'teryx goretex", "arcteryx gore-tex pro", "arcteryx gore tex",
    "arc'teryx hardshell", "arcteryx softshell",
    "arc'teryx fleece", "arcteryx fleece",
    "arc'teryx covert cardigan", "arcteryx covert cardigan",
    "arc'teryx kyanite", "arcteryx kyanite",
    "arc'teryx delta", "arcteryx delta",
    "arc'teryx squamish", "arcteryx squamish",
    "arcteryx windbreaker",
    "arc'teryx trino",
    "dead bird",
    "arc'teryx pant", "arcteryx pant",
    "arc'teryx gamma", "arcteryx gamma",
    "arc'teryx sigma", "arcteryx sigma",
    "arc'teryx lefroy", "arcteryx lefroy",
    "arc'teryx zeta", "arcteryx zeta",
    # ── Stüssy Tier A ────────────────────────────────────────────────────
    "stüssy 8 ball", "stussy 8 ball", "stussy 8 ball hoodie",
    "stüssy world tour", "stussy world tour", "stussy world tour tee",
    "stüssy stock logo hoodie", "stussy stock logo",
    "stussy basic logo",
    "stüssy big stock", "stussy big stock",
    "stüssy cardigan", "stussy cardigan",
    "stüssy strickjacke", "stussy strickjacke",
    "stüssy pigment dyed", "stussy pigment dyed",
    "stüssy heavyweight", "stussy heavyweight",
    "stüssy fleece", "stussy fleece",
    "stüssy workgear", "stussy workgear",
    "stüssy workshirt", "stussy workshirt",
    "stüssy beach pant", "stussy beach pant",
    "stüssy italic", "stussy italic",
    "stüssy sport", "stussy sport",
    "stüssy designs", "stussy designs",
    # ── Adidas Tier A ────────────────────────────────────────────────────
    "adidas originals trefoil trackjacket",
    "adidas trainingsjacke 80er", "adidas trainingsjacke 90er",
    "adidas trainingsanzug vintage",
    "adidas windbreaker vintage",
    "adidas spellout hoodie",
    "adidas equipment crewneck",
    "adidas three stripes vintage",
    "adidas half zip vintage",
    "adidas fleece vintage",
    "adidas track pants vintage",
    "adidas popper pants", "adidas druckknopfhose",
    # ── Nike Tier A ───────────────────────────────────────────────────────
    "nike trackjacket vintage", "nike trainingsjacke 90er",
    "nike windbreaker vintage", "nike half zip vintage",
    "nike fleece vintage", "nike crewneck spellout",
    "nike spellout hoodie", "nike embroidered swoosh",
    "nike center swoosh hoodie", "nike mini swoosh crewneck",
    "nike travis",
    "nike storm fit", "nike stormfit",
    "nike clima fit", "nike therma fit vintage",
    # ── Ralph Lauren Tier A ───────────────────────────────────────────────
    "polo ralph lauren sweatshirt", "polo ralph lauren spellout",
    "ralph lauren big pony", "big pony polo",
    "ralph lauren rugby", "rugby ralph lauren",
    "polo crest", "cookie logo",
    "polo pullover gestrickt vintage",
    "polo fleece", "polo half zip vintage",
    "polo windbreaker vintage",
    "polo harrington",
    "polo chaps vintage",
]

# Tier B — schwaches Kontext-Signal, nur in Kombination mit Tier A wertvoll
TIER_B = [
    "vintage", "retro", "y2k", "90s", "00s", "2000s", "oldschool", "old school",
    "opa", "omas keller", "dachboden", "papa", "opi", "omas schrank",
    "washed", "distressed", "faded", "worn in",
    "rare", "deadstock", "selten", "gefunden",
    "pasha", "ufo361", "pashanim",
]

# Tier C — Noise / Fakes → Negativsignal, blockiert den Alert
TIER_C = [
    "inspired", "inspired by", "style", "look", "ähnlich wie", "ähnlich",
    " like ", "replica", "replik", "fake", "dupe", "bootleg",
]


class FilterEngine:
    def __init__(self, start_ts: float, test_mode: bool = False, config: dict | None = None):
        self.start_ts = start_ts
        self.test_mode = test_mode

        cfg = config or {}
        self.core_brands      = [s.lower() for s in (cfg.get("core_brands")       or CORE_BRANDS)]
        self.blacklist        = [s.lower() for s in (cfg.get("blacklist")         or BLACKLIST)]
        self.permitted_sizes  = [s.lower() for s in (cfg.get("permitted_sizes")   or PERMITTED_SIZES)]
        self.tier_s           = [s.lower() for s in (cfg.get("tier_s")            or TIER_S)]
        self.tier_a_cut       = [s.lower() for s in (cfg.get("tier_a_cut")        or TIER_A_CUT)]
        self.tier_a_explicit  = [s.lower() for s in (cfg.get("tier_a_explicit")   or TIER_A_EXPLICIT)]
        self.tier_b           = [s.lower() for s in (cfg.get("tier_b")            or TIER_B)]
        self.tier_c           = [s.lower() for s in (cfg.get("tier_c")            or TIER_C)]
        try:
            self.price_min = float(cfg.get("price_min", FILTER_MIN_PRICE))
        except (TypeError, ValueError):
            self.price_min = FILTER_MIN_PRICE
        try:
            self.price_max = float(cfg.get("price_max", FILTER_MAX_PRICE))
        except (TypeError, ValueError):
            self.price_max = FILTER_MAX_PRICE

    def _get_photo_timestamp(self, item: dict) -> float:
        photo = item.get("photo") or {}

        ts_photo = (photo.get("high_resolution") or {}).get("timestamp")
        if ts_photo:
            return float(ts_photo)

        url = photo.get("url") or ""
        m = re.search(r'/(\d{10})\.jpeg', url)
        if m:
            return float(m.group(1))

        return -1.0

    def _check_size(self, size_title: str) -> bool:
        if not size_title:
            return False
        s = size_title.lower().strip()
        parts = [p.strip() for p in s.replace("/", " ").replace("|", " ").split()]
        for p in parts:
            if p in self.permitted_sizes:
                return True
        return False

    def evaluate_item(self, item: dict) -> tuple[bool, str]:
        """Gibt Tuple zurück: (is_approved: bool, reason: str)"""
        title       = (item.get("title") or "").lower()
        description = (item.get("description") or "").lower()

        price_val = item.get("price")
        if isinstance(price_val, dict):
            price = float(price_val.get("amount", 0))
        else:
            try:
                price = float(price_val or 0)
            except ValueError:
                price = 0.0

        # 1. Preis Check
        if not (self.price_min <= price <= self.price_max):
            return False, f"Preis ({price}€) außerhalb des Limits"

        # 2. Alter Check
        ts = self._get_photo_timestamp(item)
        if ts > 0:
            if ts < self.start_ts:
                return False, "Vor Bot-Start hochgeladen"
            age = time.time() - ts
            if age > MAX_ITEM_AGE_SECONDS:
                return False, f"Zu alt ({int(age)}s)"

        # 3. Size Check
        size = item.get("size_title")
        if not self._check_size(size):
            return False, f"Größe ({size}) nicht in Whitelist"

        full_text = f"{title} {description}"

        # 4. Tier S — vor Blacklist prüfen, diese Items sind immer Treffer wert
        for s in self.tier_s:
            if s in full_text:
                return True, f"Tier S: '{s}'"

        # 5. Blacklist Check
        for b in self.blacklist:
            if b in full_text:
                return False, f"Blacklist Treffer: '{b}'"

        # 6. Tier-basierter Signal-Check
        # Tier C: Noise/Fake-Wörter → sofort blocken
        for c in self.tier_c:
            if c in full_text:
                return False, f"Tier C Noise: '{c}'"

        # Tier A: explizite Phrasen ODER (Core Brand + Cut-Indikator)
        has_core_brand    = any(b in title or b in description for b in self.core_brands)
        has_cut_indicator = any(c in full_text for c in self.tier_a_cut)
        has_tier_a_explicit = any(a in full_text for a in self.tier_a_explicit)

        has_tier_a = has_tier_a_explicit or (has_core_brand and has_cut_indicator)

        # Tier B: Kontext-Signal
        matched_b = next((b for b in self.tier_b if b in full_text), None)
        has_tier_b = matched_b is not None

        if has_tier_a and has_tier_b:
            tier_a_match = next((a for a in self.tier_a_explicit if a in full_text), "brand+cut")
            return True, f"Tier A+B: '{tier_a_match}' + '{matched_b}'"

        if has_tier_a:
            return False, "Nur Tier A — kein Vintage/Kontext-Signal (Tier B fehlt)"

        return False, "Generisches Item — kein ausreichendes Signal"
