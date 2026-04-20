import asyncio
import aiohttp
import logging
import os
import glob
import subprocess
import sys
from playwright.sync_api import sync_playwright

log = logging.getLogger("SnipeBot.Fetcher")

# ==========================================
# CONFIG
# ==========================================
VINTED_DOMAIN    = "www.vinted.de"
CATALOG_ENDPOINT = f"https://{VINTED_DOMAIN}/api/v2/catalog/items"
USER_ENDPOINT    = f"https://{VINTED_DOMAIN}/api/v2/users/{{}}"


def get_chromium_path() -> str | None:
    """Findet Chromium automatisch auf jedem PC."""
    base = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright")
    if not os.path.exists(base):
        return None
    matches = glob.glob(os.path.join(base, "chromium-*", "chrome-win64", "chrome.exe"))
    if matches:
        return matches[0]
    return None


def install_chromium() -> bool:
    """
    Versucht Chromium über den mitgelieferten Playwright-Installer zu installieren.
    Gibt True zurück wenn erfolgreich.
    """
    log.info("📦 Chromium nicht gefunden – starte automatische Installation...")
    print("\n[~] Chromium wird zum ersten Mal installiert, bitte warten (~100MB)...")

    try:
        # Wenn als .exe gefroren: playwright liegt im internen Bundle
        if getattr(sys, "frozen", False):
            playwright_cli = os.path.join(sys._MEIPASS, "playwright")
        else:
            playwright_cli = "playwright"

        result = subprocess.run(
            [playwright_cli, "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300  # 5 Minuten Timeout für langsame Verbindungen
        )

        if result.returncode == 0:
            log.info("✅ Chromium erfolgreich installiert!")
            print("[+] Chromium erfolgreich installiert!\n")
            return True
        else:
            log.error(f"❌ Playwright install fehlgeschlagen:\n{result.stderr}")
            print(f"[-] Installation fehlgeschlagen: {result.stderr}")
            return False

    except FileNotFoundError:
        # Fallback: über python -m playwright
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                log.info("✅ Chromium erfolgreich installiert (via python -m)!")
                print("[+] Chromium erfolgreich installiert!\n")
                return True
            else:
                log.error(f"❌ Installation fehlgeschlagen: {result.stderr}")
                return False
        except Exception as e:
            log.error(f"❌ Installation fehlgeschlagen: {e}")
            return False

    except subprocess.TimeoutExpired:
        log.error("❌ Installation Timeout (>5 Minuten)")
        print("[-] Timeout bei der Installation. Bitte manuell 'playwright install chromium' ausfuehren.")
        return False

    except Exception as e:
        log.error(f"❌ Unerwarteter Fehler bei Installation: {e}")
        return False


def ensure_chromium() -> str | None:
    """
    Stellt sicher dass Chromium verfügbar ist.
    Prüft zuerst ob es installiert ist, installiert es automatisch falls nicht.
    Gibt den Pfad zurück oder None bei Fehler.
    """
    path = get_chromium_path()
    if path:
        log.info(f"✅ Chromium gefunden: {path}")
        return path

    # Nicht gefunden → automatisch installieren (non-blocking)
    log.info("📦 Chromium nicht gefunden – starte automatische Installation...")
    success = install_chromium()
    if not success:
        log.warning("⚠️  Chromium-Installation fehlgeschlagen – fahre ohne Cookies fort")
        return None

    # Nach Installation erneut suchen
    path = get_chromium_path()
    if not path:
        log.error("❌ Chromium nach Installation immer noch nicht gefunden.")
        return None

    return path


def fetch_cookies_sync(domain: str) -> dict:
    """Lädt Cookies via Playwright mit Timeout-Schutz."""
    log.info("🍪 Hole Cookies via Playwright (max. 45s)...")
    
    def _do_fetch():
        try:
            chromium_path = ensure_chromium()
            if not chromium_path:
                log.warning("⚠️  Chromium nicht verfügbar – starte ohne Cookies.")
                return {}

            try:
                with sync_playwright() as pw:
                    log.debug("  → Starte Chromium...")
                    browser = pw.chromium.launch(
                        executable_path=chromium_path,
                        headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage"],
                        timeout=15_000  # 15s für Browser-Launch
                    )
                    try:
                        log.debug("  → Erstelle Context...")
                        ctx = browser.new_context(
                            user_agent=(
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36"
                            ),
                            locale="de-DE"
                        )
                        log.debug("  → Öffne Seite...")
                        page = ctx.new_page()
                        page.goto(f"https://{domain}/catalog", wait_until="domcontentloaded", timeout=20_000)
                        page.wait_for_timeout(2000)

                        result = {c["name"]: c["value"] for c in ctx.cookies()}
                        log.info(f"🍪 {len(result)} Cookies erhalten!")
                        return result
                    finally:
                        browser.close()
            except Exception as e:
                log.warning(f"⚠️  Browser-Fehler: {e} – starte ohne Cookies")
                return {}
        except Exception as e:
            log.error(f"Unerwarteter Fehler beim Cookie-Fetch: {e}")
            return {}
    
    # Wrapper mit Timeout-Schutz
    import threading
    import queue
    
    result_queue = queue.Queue()
    
    def worker():
        try:
            result = _do_fetch()
            result_queue.put(("success", result))
        except Exception as e:
            result_queue.put(("error", str(e)))
    
    thread = threading.Thread(target=worker, daemon=False)
    thread.start()
    thread.join(timeout=45)  # 45s Gesamttimeout
    
    try:
        status, data = result_queue.get_nowait()
        if status == "success":
            return data
        else:
            log.warning(f"⚠️  Cookie-Fetch Fehler: {data}")
            return {}
    except queue.Empty:
        log.error("❌ Cookie-Fetch Timeout (>45s) – fahre ohne Cookies fort")
        return {}


class VintedFetcher:
    def __init__(self):
        self._session = None
        self._lock = asyncio.Lock()
        self._req_count = 0
        self._cookies = {}

    async def _init_session(self):
        """Initialisiert die aiohttp-Session mit Timeout-Schutz."""
        log.info("Initialisiere Session...")
        try:
            # Cookie-Fetch mit Timeout über wait_for
            loop = asyncio.get_event_loop()
            self._cookies = await asyncio.wait_for(
                loop.run_in_executor(None, fetch_cookies_sync, VINTED_DOMAIN),
                timeout=50  # 50s Timeout für den gesamten Cookie-Fetch
            )
        except asyncio.TimeoutError:
            log.error("❌ Cookie-Fetch Timeout – fahre ohne Cookies fort")
            self._cookies = {}
        except Exception as e:
            log.error(f"Cookie-Fetch Fehler: {e} – fahre ohne Cookies fort")
            self._cookies = {}

        csrf = self._cookies.get("CSRF-TOKEN") or self._cookies.get("csrf_token", "")
        headers = {
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "de-DE,de;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer":         f"https://{VINTED_DOMAIN}/catalog",
            "X-CSRF-Token":    csrf,
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        if self._session:
            await self._session.close()

        self._session = aiohttp.ClientSession(
            cookies=self._cookies,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self._req_count = 0
        log.info("✅ Session initialisiert")

    async def start(self):
        await self._init_session()

    async def close(self):
        if self._session:
            await self._session.close()

    async def fetch_newest(self, search_text: str = "") -> list:
        params = {
            "order":         "newest_first",
            "per_page":      "8",
            "catalog_ids[]": "5",
        }
        if search_text:
            params["search_text"] = search_text

        async with self._lock:
            self._req_count += 1
            if self._req_count > 500:
                log.info("Rotiere Session nach 500 Requests...")
                await self._init_session()

            try:
                async with self._session.get(CATALOG_ENDPOINT, params=params, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 429:
                        wait = int(r.headers.get("Retry-After", 60))
                        log.warning(f"⏳ Rate limit – warte {min(wait, 5)}s (max 5s)")
                        await asyncio.sleep(min(wait, 5))  # Cap at 5 seconds
                        return []
                    if r.status not in (200, 201):
                        return []
                    data = await r.json()
                    return data.get("items") or []
            except asyncio.TimeoutError:
                return []
            except Exception as e:
                log.debug(f"HTTP Fehler: {e}")
                return []

    async def fetch_user(self, user_id) -> dict:
        try:
            url = USER_ENDPOINT.format(user_id)
            async with self._session.get(url) as r:
                if r.status not in (200, 201):
                    return {}
                data = await r.json()
                return data.get("user") or {}
        except Exception:
            return {}