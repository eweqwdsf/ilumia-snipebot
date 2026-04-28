import asyncio
import logging
import sys
import time
import os
import re
import secrets
import string
from datetime import datetime, timezone
# ==========================================
# UNBUFFERED STDOUT — prevents pipe-buffer deadlock when running as subprocess
# ==========================================
# When main_bot.py is spawned by bridge.py via subprocess.PIPE, stdout is fully
# buffered. If the bridge's stdout-reader thread doesn't drain fast enough (e.g.
# because it's busy serving /poll-status from the UI), writes block the entire
# asyncio loop — including discord.py's sender. Flushing every print fixes this.
try:
    sys.stdout.reconfigure(line_buffering=True, write_through=True)
    sys.stderr.reconfigure(line_buffering=True, write_through=True)
except Exception:
    pass
os.environ["PYTHONUNBUFFERED"] = "1"

import discord
from discord.ext import commands
from discord import app_commands

from supabase import create_client, Client

from vinted_fetcher import VintedFetcher
from vinted_filter import FilterEngine, PERMITTED_SIZES

# ==========================================
# CONFIG — kommt alles von bridge.py via Env-Variablen (kein .env beim Kunden!)
# ==========================================
DISCORD_BOT_TOKEN  = os.getenv("DISCORD_BOT_TOKEN", "").strip()
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0") or "0")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

# Admin User IDs (komma-getrennt)
admin_ids_str = os.getenv("ADMIN_USER_IDS", "").strip()
ADMIN_USER_IDS = [int(uid.strip()) for uid in admin_ids_str.split(",") if uid.strip().isdigit()]

# ── Startup-Validierung — früh crashen mit klarer Fehlermeldung ──────────────
if not DISCORD_BOT_TOKEN:
    print("[main_bot] FEHLER: DISCORD_BOT_TOKEN nicht gesetzt — bridge hat bot_config nicht geladen!")
    sys.exit(1)
if not DISCORD_CHANNEL_ID:
    print("[main_bot] FEHLER: DISCORD_CHANNEL_ID nicht gesetzt oder 0!")
    sys.exit(1)
if not SUPABASE_URL or not SUPABASE_KEY:
    print("[main_bot] FEHLER: SUPABASE_URL / SUPABASE_KEY fehlen!")
    sys.exit(1)

POLL_INTERVAL = 8.0

# ==========================================
# BRAND CHANNEL ROUTING
# Ein Channel pro Marke.
# 0 = nicht konfiguriert → fällt auf den default DISCORD_CHANNEL_ID zurück
# ==========================================
BRAND_CHANNELS: dict[str, int] = {
    "nike":         1498060717511938208,
    "adidas":       1498060986832388249,
    "stussy":       1498061783007629572,
    "arcteryx":     1498061999236714496,
    "cp_company":   1498062177695699054,
    "ralph_lauren": 1498061115261845659,
    "lacoste":      1498062992942829630,
    "carhartt":     1498063223478423684,
    "burberry":     1498759766057419047,
}

SEARCH_QUERIES = [
    # ── Tier B Kontext (breite Abdeckung) ────────────────────────────────
    {"search_text": "vintage"},
    {"search_text": "y2k"},
    {"search_text": "90s"},
    {"search_text": "2000s"},
    {"search_text": "retro"},
    {"search_text": "dachboden"},
    {"search_text": "omas keller"},
    # ── Core Brands ───────────────────────────────────────────────────────
    {"search_text": "nike"},
    {"search_text": "adidas"},
    {"search_text": "stussy"},
    {"search_text": "carhartt"},
    {"search_text": "arcteryx"},
    {"search_text": "cp company"},
    {"search_text": "ralph lauren"},
    {"search_text": "polo sport"},
    {"search_text": "lacoste"},
    {"search_text": "burberry"},
    # ── Tier A Kleidung ───────────────────────────────────────────────────
    {"search_text": "trainingsjacke"},
    {"search_text": "trainingsanzug"},
    {"search_text": "tracksuit"},
    {"search_text": "windbreaker"},
    {"search_text": "track jacket"},
    # ── Tier S Spezifisch ─────────────────────────────────────────────────
    {"search_text": "firebird"},
    {"search_text": "beckenbauer"},
    {"search_text": "wales bonner"},
    {"search_text": "veilance"},
    {"search_text": "goggle jacket"},
    {"search_text": "polo stadium"},
    {"search_text": "snow beach"},
]

# ==========================================
# LOGGING
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)-12s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SnipeBot.Main")

# ==========================================
# SUPABASE CLIENT
# ==========================================
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# LICENSE KEY GENERATOR
# ==========================================
def parse_duration(duration_str: str) -> int | None:
    m = re.fullmatch(r"(\d+)d", duration_str.strip().lower())
    if not m:
        return None
    days = int(m.group(1))
    if days < 1 or days > 3650:
        return None
    return days

def generate_license_key(duration_str: str) -> str:
    chars = string.ascii_uppercase + string.digits
    blocks = ["".join(secrets.choice(chars) for _ in range(4)) for _ in range(5)]
    return f"{duration_str.upper()}-" + "-".join(blocks)

def insert_license_to_supabase(key: str, duration_days: int) -> bool:
    try:
        supabase.table("licenses").insert({
            "key": key,
            "duration_days": duration_days,
            "activated_at": None,
            "hwid_locked": None,
        }).execute()
        return True
    except Exception as e:
        log.error(f"Supabase Insert Fehler: {e}")
        return False

# ==========================================
# DEDUPLICATION + STATS
# ==========================================
class Dedup:
    def __init__(self):
        self._seen: set[str] = set()
        self._lock = asyncio.Lock()

    async def check_and_mark(self, item_id: str) -> bool:
        async with self._lock:
            if item_id in self._seen:
                return False
            self._seen.add(item_id)
            return True


class Stats:
    """Tracking für den Heartbeat — zeigt was der Bot wirklich tut."""
    def __init__(self):
        self.drop_reasons: dict[str, int] = {}
        self.alerts_sent: int = 0
        self._lock = asyncio.Lock()

    async def add_drop(self, reason: str):
        async with self._lock:
            # Reason-Normalisierung — nur den Typ behalten, nicht die Details
            key = reason.split("(")[0].split(":")[0].strip()
            self.drop_reasons[key] = self.drop_reasons.get(key, 0) + 1

    async def add_alert(self):
        async with self._lock:
            self.alerts_sent += 1

# Notify bridge when first item found
_first_item_notified = False
_bot_ready_notified = False

async def notify_first_item():
    global _first_item_notified
    if _first_item_notified:
        return
    _first_item_notified = True
    try:
        import urllib.request as _ur
        bridge_port   = os.environ.get("BRIDGE_PORT", "57421")
        bridge_secret = os.environ.get("BRIDGE_SECRET", "")
        req = _ur.Request(
            f"http://127.0.0.1:{bridge_port}/item-found",
            data=b"{}",
            headers={
                "Content-Type":    "application/json",
                "X-Bridge-Secret": bridge_secret,
            }
        )
        _ur.urlopen(req, timeout=2)
    except Exception:
        pass

async def notify_bot_ready():
    """Sendet Notification wenn Bot ready ist (nur einmal)."""
    global _bot_ready_notified
    if _bot_ready_notified:
        return
    _bot_ready_notified = True
    await notify_first_item()  # Reuse existing endpoint

# ==========================================
# ROUTING HELPERS
# ==========================================
def get_item_price(item: dict) -> float:
    price_val = item.get("price")
    if isinstance(price_val, dict):
        return float(price_val.get("amount", 0))
    try:
        return float(price_val or 0)
    except (ValueError, TypeError):
        return 0.0


def detect_brand(item: dict) -> str:
    """Erkennt die Marke eines Items für Channel-Routing (nutzt brand_title + Titel)."""
    brand_title = (item.get("brand_title") or "").lower()
    title       = (item.get("title") or "").lower()
    text = f"{brand_title} {title}"

    if any(k in text for k in ["nike", "jordan", "nocta", "swoosh", "nikelab"]):
        return "nike"
    if any(k in text for k in ["adidas", "wales bonner", "y-3", "yeezy", "trefoil", "three stripes"]):
        return "adidas"
    if any(k in text for k in ["stussy", "stüssy"]):
        return "stussy"
    if any(k in text for k in ["arcteryx", "arc'teryx", "veilance"]):
        return "arcteryx"
    if any(k in text for k in ["cp company", "cp-company", "cp goggle", "mille miglia"]):
        return "cp_company"
    if any(k in text for k in ["ralph lauren", "polo sport", "polo bear", "polo stadium", "polo ski", "polo snow"]):
        return "ralph_lauren"
    if "lacoste" in text:
        return "lacoste"
    if "carhartt" in text:
        return "carhartt"
    if "burberry" in text:
        return "burberry"
    return "other"


def extract_tier(reason: str) -> str:
    """Extrahiert das Tier aus dem Filter-Reason-String."""
    if reason.startswith("Tier S"):
        return "S"
    return "AB"


def determine_channel(brand: str) -> int:
    """Gibt die korrekte Channel-ID zurück. Fällt auf DISCORD_CHANNEL_ID zurück wenn 0."""
    ch_id = BRAND_CHANNELS.get(brand, 0)
    return ch_id if ch_id else DISCORD_CHANNEL_ID


# ==========================================
# DISCORD BOT
# ==========================================
class SnipeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self._queue: asyncio.Queue = asyncio.Queue()

    async def setup_hook(self):
        setup_commands(self)
        # Guild-ID aus .env — wenn nicht gesetzt, global sync (funktioniert bei allen Kunden)
        guild_id_str = os.getenv("DISCORD_GUILD_ID", "").strip()
        if guild_id_str.isdigit():
            GUILD = discord.Object(id=int(guild_id_str))
            self.tree.copy_global_to(guild=GUILD)
            await self.tree.sync(guild=GUILD)
            log.info(f"✅ Slash Commands synchronisiert (Guild {guild_id_str})!")
        else:
            await self.tree.sync()
            log.info("✅ Slash Commands global synchronisiert!")
        self.loop.create_task(self._sender())

    async def on_ready(self):
        log.info(f"🤖 Discord Bot bereit: {self.user}")
        # Notify bridge that bot is online
        await notify_bot_ready()

    async def _get_channel(self, channel_id: int):
        if channel_id not in self._channel_cache:
            try:
                self._channel_cache[channel_id] = await self.fetch_channel(channel_id)
                log.info(f"✅ Channel gecacht: #{self._channel_cache[channel_id].name} ({channel_id})")
            except Exception as e:
                log.error(f"❌ Channel {channel_id} nicht gefunden: {e}")
                self._channel_cache[channel_id] = None
        return self._channel_cache[channel_id]

    async def _sender(self):
        await self.wait_until_ready()
        self._channel_cache: dict[int, any] = {}
        while True:
            payload = await self._queue.get()
            channel_id = payload.get("channel_id", DISCORD_CHANNEL_ID)
            ch = await self._get_channel(channel_id)
            if not ch:
                log.error(f"❌ Channel {channel_id} nicht verfügbar — überspringe")
                continue
            log.info(f"📤 → #{ch.name} | Queue: {self._queue.qsize()}")
            try:
                await ch.send(embed=payload["embed"], view=payload["view"])
                log.info(f"✅ SEND OK")
                await asyncio.sleep(7)
            except discord.Forbidden:
                log.error(f"❌ Keine Sendeberechtigung in #{ch.name}!")
            except Exception as e:
                log.error(f"Discord Fehler: {e}")

    async def alert(self, embed: discord.Embed, view: discord.ui.View, channel_id: int):
        await self._queue.put({"embed": embed, "view": view, "channel_id": channel_id})
        log.info(f"📥 QUEUED (ch={channel_id}) — Queue: {self._queue.qsize()}")

# ==========================================
# SLASH COMMAND: /genlicense
# ==========================================
def setup_commands(bot: SnipeBot):

    @bot.tree.command(name="genlicense", description="Generiert einen neuen License-Key (nur fuer Admins)")
    @app_commands.describe(dauer="Laufzeit des Keys, z.B. 7d, 30d, 90d, 365d")
    async def genlicense(interaction: discord.Interaction, dauer: str):
        if ADMIN_USER_IDS and interaction.user.id not in ADMIN_USER_IDS:
            await interaction.response.send_message(
                "❌ Du hast keine Berechtigung fuer diesen Befehl.",
                ephemeral=True
            )
            return

        duration_days = parse_duration(dauer)
        if duration_days is None:
            await interaction.response.send_message(
                f"❌ Ungueltige Dauer `{dauer}`.\nBeispiele: `1d`, `7d`, `30d`, `90d`, `365d`",
                ephemeral=True
            )
            return

        key = generate_license_key(dauer)
        success = insert_license_to_supabase(key, duration_days)

        if not success:
            await interaction.response.send_message(
                "❌ Fehler beim Speichern in der Datenbank!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🔑 License-Key generiert",
            color=0x00C853,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Key", value=f"```{key}```", inline=False)
        embed.add_field(name="Laufzeit", value=f"`{duration_days} Tage`", inline=True)
        embed.add_field(name="Status", value="`Nicht aktiviert`", inline=True)
        embed.set_footer(text=f"Generiert von {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)
        log.info(f"🔑 License-Key generiert: {key} ({duration_days}d) von {interaction.user}")

# ==========================================
# EMBED BUILDER
# ==========================================
class ItemView(discord.ui.View):
    def __init__(self, url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="➡️ Zum Angebot", style=discord.ButtonStyle.link, url=url))

def _stars(rating) -> str:
    try:
        r = float(rating)
    except (TypeError, ValueError):
        return "—"
    if r <= 1.0:
        r = r * 4 + 1
    r = max(1.0, min(5.0, r))
    full = int(round(r))
    return "⭐" * full + "☆" * (5 - full) + f" ({r:.1f})"

async def build_embed(item: dict, age_seconds: float, fetcher) -> tuple[discord.Embed, discord.ui.View]:
    title = item.get("title", "?")
    item_id = item.get("id", "")
    path = item.get("path", f"/items/{item_id}")
    url = f"https://www.vinted.de{path}"

    photo = item.get("photo") or {}
    image_url = photo.get("full_size_url") or photo.get("url")

    brand = item.get("brand_title") or "—"
    size = item.get("size_title") or "—"
    condition = item.get("status") or "—"

    user = item.get("user") or {}
    seller = user.get("login", "?")
    user_id = user.get("id")
    user_data = await fetcher.fetch_user(user_id) if user_id else {}
    rating = user_data.get("avg_review_rating") or user_data.get("feedback_reputation")
    rev_count = user_data.get("feedback_count") or user_data.get("positive_feedback_count", 0)
    stars = _stars(rating) if rating is not None else "—"

    price_val = item.get("price")
    if isinstance(price_val, dict):
        price = float(price_val.get("amount", 0))
    else:
        price = float(price_val or 0)

    age_str = f"{int(age_seconds)}s" if age_seconds < 60 else f"{int(age_seconds / 60)}m"
    if age_seconds < 0:
        age_str = "Neu"

    SHIPPING_COST = 4.0
    TARGET_PROFIT = 0.40
    VINTED_FEE = 0.05
    total_cost = price + SHIPPING_COST
    resell = (total_cost * (1 + TARGET_PROFIT)) / (1 - VINTED_FEE)

    profit_block = (
        "```diff\n"
        f"- Kaufen (inkl. Versand):  {total_cost:.2f}€\n"
        f"+ Verkaufen fuer:          {resell:.2f}€\n"
        "```"
    )

    embed = discord.Embed(title=title, description=profit_block, color=0x00C853)

    if image_url:
        embed.set_image(url=image_url)

    embed.add_field(name="Marke",       value=brand,                   inline=True)
    embed.add_field(name="Groesse",     value=size,                    inline=True)
    embed.add_field(name="Zustand",     value=condition,               inline=True)
    embed.add_field(name="Alter",       value=age_str,                 inline=True)
    embed.add_field(name="Verkaeufer",  value=f"@{seller}",            inline=True)
    embed.add_field(name="Bewertungen", value=f"{stars} ({rev_count})", inline=True)
    embed.set_footer(text=f"Vinted Snipe Bot v11 • {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

    return embed, ItemView(url)

# ==========================================
# TASK LOOP
# ==========================================
async def query_task(q: dict, fetcher: VintedFetcher, filter_engine: FilterEngine, dedup: Dedup, stats: Stats, bot: SnipeBot, stagger_delay: float):
    search = q["search_text"]
    await asyncio.sleep(stagger_delay)

    while True:
        cycle_start = time.monotonic()
        try:
            items = await fetcher.fetch_newest(search)
            for item in items:
                item_id = str(item.get("id", ""))
                if not item_id:
                    continue
                if not await dedup.check_and_mark(item_id):
                    continue
                is_valid, reason = filter_engine.evaluate_item(item)
                if not is_valid:
                    await stats.add_drop(reason)
                    log.info(f"⏭️  [{reason}] – {item.get('title', '?')[:50]}")
                    continue
                ts = filter_engine._get_photo_timestamp(item)
                age = (time.time() - ts) if ts > 0 else -1.0
                price = get_item_price(item)
                brand = detect_brand(item)
                tier  = extract_tier(reason)
                brand_ch = determine_channel(brand)
                target_channels = list(dict.fromkeys([brand_ch, DISCORD_CHANNEL_ID]))
                log.info(f"🚨 ALERT! [{brand}|{tier}|{price:.0f}€] → {target_channels} | {item.get('title', '?')}")
                await stats.add_alert()
                embed, view = await build_embed(item, age, fetcher)
                for ch_id in target_channels:
                    await bot.alert(embed, view, ch_id)
                await notify_first_item()
        except Exception as e:
            log.error(f"Task Error ({search}): {e}")

        elapsed = time.monotonic() - cycle_start
        await asyncio.sleep(max(0.1, POLL_INTERVAL - elapsed))


async def heartbeat(dedup: Dedup, fetcher: VintedFetcher, stats: Stats):
    while True:
        await asyncio.sleep(60)
        # API-Status
        api_line = (
            f"API: ok={fetcher.stat_ok} "
            f"leer={fetcher.stat_empty} "
            f"403={fetcher.stat_403} "
            f"429={fetcher.stat_429} "
            f"err={fetcher.stat_err}"
        )
        # Top-5 Drop-Reasons
        top_drops = sorted(stats.drop_reasons.items(), key=lambda x: -x[1])[:5]
        drops_line = " | ".join(f"{k}={v}" for k, v in top_drops) if top_drops else "—"

        log.info(
            f"📡 Bot aktiv | "
            f"gesehen={len(dedup._seen)} | "
            f"items fetched={fetcher.stat_items} | "
            f"🚨 alerts={stats.alerts_sent}"
        )
        log.info(f"   {api_line}")
        log.info(f"   Drops: {drops_line}")

async def auto_notify_after_delay():
    """Sends notification after 10s even if no item found (fallback)."""
    await asyncio.sleep(10)
    await notify_bot_ready()

async def fetch_active_config() -> dict | None:
    """Hole aktive Filter-Config vom Bridge-HTTP-Server. Returns None bei Fehler → Defaults."""
    try:
        import urllib.request as _ur
        port   = os.environ.get("BRIDGE_PORT", "57421")
        secret = os.environ.get("BRIDGE_SECRET", "")
        req = _ur.Request(
            f"http://127.0.0.1:{port}/active-config",
            data=b"{}",
            headers={
                "Content-Type":    "application/json",
                "X-Bridge-Secret": secret,
            }
        )
        # Run in executor so we don't block the event loop
        loop = asyncio.get_event_loop()
        def _do():
            with _ur.urlopen(req, timeout=20) as r:
                import json as _j
                return _j.loads(r.read().decode())
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _do),
            timeout=22
        )
        cfg = data.get("config")
        if cfg:
            log.info(f"✅ Loaded active filter config: {cfg.get('name', '?')}")
            return cfg
        log.info("ℹ️  No active config — using hardcoded defaults.")
        return None
    except Exception as e:
        log.warning(f"⚠️  Couldn't fetch active config ({e}) — using hardcoded defaults.")
        return None


# ==========================================
# MAIN
# ==========================================
async def main():
    log.info("=" * 55)
    log.info("  VINTED SNIPE BOT  -  REWORK EDITION V11")
    log.info("=" * 55)

    log.info("🔧 STEP 1: Creating SnipeBot instance...")
    bot = SnipeBot()
    log.info("🔧 STEP 2: Creating VintedFetcher...")
    fetcher = VintedFetcher()
    log.info("🔧 STEP 3: Starting fetcher (cookie fetch)...")
    await fetcher.start()
    log.info("🔧 STEP 4: Fetcher started, skipping active-config fetch (using defaults)...")

    # Hole aktive User-Config (Supabase via Bridge) — oder Fallback auf Defaults
    # Läuft im Hintergrund, blockiert nicht den Start
    active_config = None
    async def _try_load_config():
        nonlocal active_config
        try:
            cfg = await asyncio.wait_for(fetch_active_config(), timeout=10)
            if cfg:
                active_config = cfg
                # Live-Update des Filter-Engines wenn Config später ankommt
                filter_engine.hype_keywords   = [s.lower() for s in (cfg.get("hype_keywords")   or filter_engine.hype_keywords)]
                filter_engine.core_brands     = [s.lower() for s in (cfg.get("core_brands")     or filter_engine.core_brands)]
                filter_engine.blacklist       = [s.lower() for s in (cfg.get("blacklist")       or filter_engine.blacklist)]
                filter_engine.permitted_sizes = [s.lower() for s in (cfg.get("permitted_sizes") or filter_engine.permitted_sizes)]
                try: filter_engine.price_min = float(cfg.get("price_min", filter_engine.price_min))
                except (TypeError, ValueError): pass
                try: filter_engine.price_max = float(cfg.get("price_max", filter_engine.price_max))
                except (TypeError, ValueError): pass
                log.info(f"✅ Active config loaded in background: {cfg.get('name', '?')}")
        except asyncio.TimeoutError:
            log.warning("⚠️  active-config fetch timed out — using defaults")
        except Exception as e:
            log.warning(f"⚠️  active-config fetch failed ({e}) — using defaults")

    log.info(f"🔧 STEP 5: Creating FilterEngine with defaults...")

    start_ts = time.time()
    filter_engine = FilterEngine(start_ts=start_ts, test_mode=False, config=active_config)

    log.info(f"  Accepted sizes: {', '.join(filter_engine.permitted_sizes)}")
    log.info(f"  Price range:    {filter_engine.price_min}€ – {filter_engine.price_max}€")
    log.info("=" * 55)
    sys.stdout.flush()
    sys.stderr.flush()
    log.info("🔧 STEP 5b: FilterEngine ready, starting Dedup + Stats...")

    dedup = Dedup()
    stats = Stats()

    log.info("🌱 STEP 6: Seede aktuelle Items (schnelle Version)...")
    seed_count = 0
    for q in SEARCH_QUERIES:
        if seed_count >= 3:  # Nur 3 Queries für super schnellen Start
            log.info(f"⚡ Seeding limitiert auf 3 Queries → schneller Start!")
            break
        try:
            items = await asyncio.wait_for(
                fetcher.fetch_newest(q["search_text"]),
                timeout=15
            )
            for it in items:
                await dedup.check_and_mark(str(it.get("id")))
            await asyncio.sleep(0.1)  # Sehr kurze Pause
            seed_count += 1
        except asyncio.TimeoutError:
            log.warning(f"⚠️  Seed-Timeout bei '{q['search_text']}' — überspringe")
        except Exception as e:
            log.debug(f"Seed-Fehler: {e}")
    log.info(f"🌱 STEP 7: Seeding abgeschlossen ({len(dedup._seen)} Items). Starte Scan...")

    tasks = []
    for i, q in enumerate(SEARCH_QUERIES):
        stagger = i * (POLL_INTERVAL / len(SEARCH_QUERIES))
        tasks.append(asyncio.create_task(query_task(q, fetcher, filter_engine, dedup, stats, bot, stagger)))
    tasks.append(asyncio.create_task(heartbeat(dedup, fetcher, stats)))
    tasks.append(asyncio.create_task(auto_notify_after_delay()))
    # Config-Load im Hintergrund — blockiert den Start nicht
    tasks.append(asyncio.create_task(_try_load_config()))
    log.info(f"🔧 STEP 8: Created {len(tasks)} background tasks. Starting Discord bot...")

    try:
        await bot.start(DISCORD_BOT_TOKEN)
    except discord.LoginFailure as e:
        log.error(f"❌ Discord Login fehlgeschlagen: {e}")
        log.error("❌ Prüfe ob der DISCORD_BOT_TOKEN in Supabase (bot_config) korrekt ist!")
        # Bridge informieren damit die UI eine Fehlermeldung zeigen kann
        try:
            import urllib.request as _ur
            port   = os.environ.get("BRIDGE_PORT", "57421")
            secret = os.environ.get("BRIDGE_SECRET", "")
            req = _ur.Request(
                f"http://127.0.0.1:{port}/item-found",
                data=b"{}",
                headers={"Content-Type": "application/json", "X-Bridge-Secret": secret}
            )
            _ur.urlopen(req, timeout=2)
        except Exception:
            pass
        sys.exit(1)
    except KeyboardInterrupt:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await fetcher.close()
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())