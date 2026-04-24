import logging
import re
import time

log = logging.getLogger("SnipeBot.Filter")

# ==========================================
# CONFIG
# ==========================================
MAX_ITEM_AGE_SECONDS = 600  # Ignoriere alles älter als 10 Minuten
FILTER_MIN_PRICE = 5.0
FILTER_MAX_PRICE = 65.0

# Wir akzeptieren nur explizite Herrengrößen aus dieser Liste
PERMITTED_SIZES = [
    "s", "m", "l", "xl", 
    "small", "medium", "large", "extra large",
    "44", "46", "48", "50", "52", "54"
]

BLACKLIST = [
    "zara", "h&m", "shein", "asos", "defacto", "pull&bear", "primark",
    "damen", "frau", "women", "kids", "kinder", "mädchen", "junge",
    "basic", "skinny", "regular fit", "slim fit"
]

# Hype Keywords representing Vintage/Streetwear
HYPE_KEYWORDS = [
    "vintage", "vintedstyle", "2000s", "pasha-style", "90s", "00s", "y2k", "jersey", "trikot", 
    "tracksuit", "windbreaker", "harley davidson", "nascar", 
    "baggy", "jeans", "puffer", "backprint jeans"
]

CORE_BRANDS = [
    "nike", "adidas", "lacoste", "ralph lauren", "polo", 
    "corteiz", "chrome hearts", "arcteryx", "stussy", "carhartt",
    "stone island", "fred perry", "levis", "bershka", "true religion"
]

class FilterEngine:
    def __init__(self, start_ts: float, test_mode: bool = False, config: dict | None = None):
        self.start_ts = start_ts
        self.test_mode = test_mode

        # Config override — if None/empty, fall back to hardcoded defaults above
        cfg = config or {}
        self.hype_keywords   = [s.lower() for s in (cfg.get("hype_keywords")   or HYPE_KEYWORDS)]
        self.core_brands     = [s.lower() for s in (cfg.get("core_brands")     or CORE_BRANDS)]
        self.blacklist       = [s.lower() for s in (cfg.get("blacklist")       or BLACKLIST)]
        self.permitted_sizes = [s.lower() for s in (cfg.get("permitted_sizes") or PERMITTED_SIZES)]
        try:
            self.price_min = float(cfg.get("price_min", FILTER_MIN_PRICE))
        except (TypeError, ValueError):
            self.price_min = FILTER_MIN_PRICE
        try:
            self.price_max = float(cfg.get("price_max", FILTER_MAX_PRICE))
        except (TypeError, ValueError):
            self.price_max = FILTER_MAX_PRICE

    def _get_photo_timestamp(self, item: dict) -> float:
        """Extrahiert den originalen Upload-Timestamp aus der URL oder den Metadaten des Bildes."""
        photo = item.get("photo") or {}
        
        # Methode 1: Vinted High-Resolution Timestamp
        ts_photo = (photo.get("high_resolution") or {}).get("timestamp")
        if ts_photo:
            return float(ts_photo)
            
        # Methode 2: Aus Dateinamen extrahieren
        url = photo.get("url") or ""
        m = re.search(r'/(\d{10})\.jpeg', url)
        if m:
            return float(m.group(1))
            
        return -1.0

    def _check_size(self, size_title: str) -> bool:
        if not size_title:
            return False
        # Normalize
        s = size_title.lower().strip()
        # Manche Vinted-Größen haben Zusätze wie "S / 36 / 8". Splitte sie auf:
        parts = [p.strip() for p in s.replace("/", " ").replace("|", " ").split()]
        for p in parts:
            if p in self.permitted_sizes:
                return True
        return False

    def evaluate_item(self, item: dict) -> tuple[bool, str]:
        """
        Gibt Tuple zurück: (is_approved: bool, reason: str)
        Der Reason ist gut fürs Debugging.
        """
        title = (item.get("title") or "").lower()
        brand = (item.get("brand_title") or "").lower()
        
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
                return False, f"Vor Bot-Start hochgeladen"
            
            age = time.time() - ts
            if age > MAX_ITEM_AGE_SECONDS:
                return False, f"Zu alt ({int(age)}s)"

        # 3. Size Check
        size = item.get("size_title")
        if not self._check_size(size):
            return False, f"Größe ({size}) nicht in Whitelist"

        # 4. Blacklist Check (Titel & Marke kombiniert)
        full_text = f"{title} {brand}"
        for b in self.blacklist:
            if b in full_text:
                return False, f"Blacklist Treffer: '{b}'"

        # 5. Hype/Whitelist Check
        # Item MUSS ein Hype-Keyword ODER eine Core-Brand haben.
        has_hype_brand = any(c in brand or c in title for c in self.core_brands)
        has_hype_keyword = any(k in title for k in self.hype_keywords)
        
        if not (has_hype_brand or has_hype_keyword):
            return False, "Generisches Item (Kein Hype-Wort, keine Core-Brand)"

        return True, "Geil! Hype Item gefunden."