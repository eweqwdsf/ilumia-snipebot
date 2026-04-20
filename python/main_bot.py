import asyncio
import logging
import time
import os
import re
import secrets
import string
from datetime import datetime, timezone
from dotenv import load_dotenv

import discord
from discord.ext import commands
from discord import app_commands

from supabase import create_client, Client

from vinted_fetcher import VintedFetcher
from vinted_filter import FilterEngine, PERMITTED_SIZES

# Lade .env Datei
load_dotenv()

# ==========================================
# CONFIG
# ==========================================
DISCORD_BOT_TOKEN  = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Admin User IDs aus Umgebung (komma-getrennt)
admin_ids_str = os.getenv("ADMIN_USER_IDS", "")
ADMIN_USER_IDS = [int(uid.strip()) for uid in admin_ids_str.split(",") if uid.strip().isdigit()]

POLL_INTERVAL = 20.0

SEARCH_QUERIES = [
    {"search_text": "vintage"},
    {"search_text": "vintedstyle"},
    {"search_text": "2000s"},
    {"search_text": "pasha-style"},
    {"search_text": "90s"},
    {"search_text": "y2k"},
    {"search_text": "jersey"},
    {"search_text": "tracksuit"},
    {"search_text": "windbreaker"},
    {"search_text": "carhartt"},
    {"search_text": "stussy"},
    {"search_text": "chrome hearts"},
    {"search_text": "nike"},
    {"search_text": "ralph lauren"},
    {"search_text": "lacoste"},
    {"search_text": "stone island"},
    {"search_text": "fred perry"},
    {"search_text": "backprint jeans"},
    {"search_text": "levis"},
    {"search_text": "bershka"},
    {"search_text": "true religion"},
    {"search_text": ""},
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
# DEDUPLICATION
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
        req = _ur.Request(
            f"http://127.0.0.1:{os.environ.get('BRIDGE_PORT', 57421)}/item-found",
            data=b"{}",
            headers={"Content-Type": "application/json"}
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
        GUILD = discord.Object(id=1491820581790679244)
        self.tree.copy_global_to(guild=GUILD)
        await self.tree.sync(guild=GUILD)
        log.info("✅ Slash Commands synchronisiert!")
        self.loop.create_task(self._sender())

    async def on_ready(self):
        log.info(f"🤖 Discord Bot bereit: {self.user}")
        # Notify bridge that bot is online
        await notify_bot_ready()

    async def _sender(self):
        await self.wait_until_ready()
        ch = self.get_channel(DISCORD_CHANNEL_ID)
        if not ch:
            log.error(f"❌ Discord Channel {DISCORD_CHANNEL_ID} nicht gefunden!")
            return
        while True:
            payload = await self._queue.get()
            try:
                await ch.send(embed=payload["embed"], view=payload["view"])
                await asyncio.sleep(7)
            except Exception as e:
                log.error(f"Discord Fehler: {e}")

    async def alert(self, embed: discord.Embed, view: discord.ui.View):
        await self._queue.put({"embed": embed, "view": view})

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
async def query_task(q: dict, fetcher: VintedFetcher, filter_engine: FilterEngine, dedup: Dedup, bot: SnipeBot, stagger_delay: float):
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
                    log.info(f"⏭️  [{reason}] – {item.get('title', '?')[:50]}")
                    continue
                ts = filter_engine._get_photo_timestamp(item)
                age = (time.time() - ts) if ts > 0 else -1.0
                log.info(f"🚨 ALERT! {item.get('title', '?')} ({reason})")
                embed, view = await build_embed(item, age, fetcher)
                await bot.alert(embed, view)
                await notify_first_item()
        except Exception as e:
            log.error(f"Task Error ({search}): {e}")

        elapsed = time.monotonic() - cycle_start
        await asyncio.sleep(max(0.1, POLL_INTERVAL - elapsed))


async def heartbeat(dedup: Dedup):
    while True:
        await asyncio.sleep(60)
        log.info(f"📡 Bot aktiv... ({len(dedup._seen)} Items markiert)")

async def auto_notify_after_delay():
    """Sends notification after 10s even if no item found (fallback)."""
    await asyncio.sleep(10)
    await notify_bot_ready()

# ==========================================
# MAIN
# ==========================================
async def main():
    log.info("=" * 55)
    log.info("  VINTED SNIPE BOT  -  REWORK EDITION V11")
    log.info(f"  Akzeptierte Groessen: {', '.join(PERMITTED_SIZES)}")
    log.info("=" * 55)

    bot = SnipeBot()
    fetcher = VintedFetcher()
    await fetcher.start()

    start_ts = time.time()
    filter_engine = FilterEngine(start_ts=start_ts, test_mode=False)
    dedup = Dedup()

    log.info("🌱 Seede aktuelle Items (schnelle Version)...")
    seed_count = 0
    for q in SEARCH_QUERIES:
        if seed_count >= 3:  # Nur 3 Queries für super schnellen Start
            log.info(f"⚡ Seeding limitiert auf 3 Queries → schneller Start!")
            break
        try:
            items = await fetcher.fetch_newest(q["search_text"])
            for it in items:
                await dedup.check_and_mark(str(it.get("id")))
            await asyncio.sleep(0.1)  # Sehr kurze Pause
            seed_count += 1
        except Exception as e:
            log.debug(f"Seed-Fehler: {e}")
    log.info(f"🌱 Seeding abgeschlossen ({len(dedup._seen)} Items). Starte Scan...")

    tasks = []
    for i, q in enumerate(SEARCH_QUERIES):
        stagger = i * (POLL_INTERVAL / len(SEARCH_QUERIES))
        tasks.append(asyncio.create_task(query_task(q, fetcher, filter_engine, dedup, bot, stagger)))
    tasks.append(asyncio.create_task(heartbeat(dedup)))
    tasks.append(asyncio.create_task(auto_notify_after_delay()))

    try:
        await bot.start(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await fetcher.close()
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())