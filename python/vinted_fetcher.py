import asyncio
import aiohttp
import json
import logging
import os
import glob
import random
import subprocess
import sys
import tempfile
import time
from playwright.sync_api import sync_playwright

log = logging.getLogger("SnipeBot.Fetcher")

# ==========================================
# CONFIG
# ==========================================
VINTED_DOMAIN    = "www.vinted.de"
CATALOG_ENDPOINT = f"https://{VINTED_DOMAIN}/api/v2/catalog/items"
USER_ENDPOINT    = f"https://{VINTED_DOMAIN}/api/v2/users/{{}}"

# Session nach X Minuten zwangsweise erneuern
SESSION_REFRESH_INTERVAL = 20 * 60  # 20 Minuten

# Vinted hat 2024/25 von Session-Cookie auf JWT umgestellt.
# Neue Variante: access_token_web + refresh_token_web (JWT Bearer)
# Alte Variante: _vinted_fr_session (Legacy, Fallback)
AUTH_COOKIES_NEW = ("access_token_web",)
AUTH_COOKIES_OLD = ("_vinted_fr_session",)


def _has_auth(cookies) -> bool:
    """True wenn mindestens eine der Auth-Varianten vorhanden ist."""
    if isinstance(cookies, dict):
        names = set(cookies.keys())
    else:
        # Liste von Playwright-Cookie-Dicts
        names = {c["name"] for c in cookies}
    return any(c in names for c in AUTH_COOKIES_NEW) or \
           any(c in names for c in AUTH_COOKIES_OLD)

# ==========================================
# COOKIE CACHE (on-disk) — für schnellen Startup
# ==========================================
def _cache_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = os.path.join(base, "ILUMIA")
    os.makedirs(d, exist_ok=True)
    return d

COOKIE_CACHE_FILE    = os.path.join(_cache_dir(), "vinted_cookies.json")
COOKIE_CACHE_MAX_AGE = 30 * 60  # 30 Minuten — danach sowieso Session-Rotation


def _load_cached_cookies() -> dict:
    """Lädt Cookies aus Disk-Cache. Leer wenn abgelaufen/fehlend/unvollständig."""
    try:
        if not os.path.exists(COOKIE_CACHE_FILE):
            return {}
        with open(COOKIE_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        age = time.time() - float(data.get("ts", 0))
        if age > COOKIE_CACHE_MAX_AGE:
            log.info(f"🗑️  Cache-Cookies zu alt ({int(age)}s) – werden ignoriert")
            return {}
        cookies = data.get("cookies") or {}
        if not _has_auth(cookies):
            return {}
        log.info(f"⚡ Cache-Cookies verwendet ({int(age)}s alt, {len(cookies)} Cookies)")
        return cookies
    except Exception as e:
        log.debug(f"Cookie-Cache Load-Fehler: {e}")
        return {}


def _save_cached_cookies(cookies: dict) -> None:
    try:
        with open(COOKIE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "cookies": cookies}, f)
    except Exception as e:
        log.debug(f"Cookie-Cache Save-Fehler: {e}")


def _invalidate_cache() -> None:
    try:
        if os.path.exists(COOKIE_CACHE_FILE):
            os.remove(COOKIE_CACHE_FILE)
            log.info("🗑️  Cookie-Cache invalidiert")
    except Exception:
        pass


def fetch_cookies_from_browsers() -> dict:
    """Fallback: liest Vinted-Cookies direkt aus installierten Browsern (Edge, Firefox, Chrome, Brave)."""
    try:
        import browser_cookie3
    except ImportError:
        log.debug("browser_cookie3 nicht installiert — Browser-Fallback nicht verfügbar")
        return {}

    candidates = [
        ("Edge",    browser_cookie3.edge),
        ("Firefox", browser_cookie3.firefox),
        ("Chrome",  browser_cookie3.chrome),
        ("Brave",   browser_cookie3.brave),
    ]

    for name, loader in candidates:
        try:
            jar = loader(domain_name=".vinted.de")
            cookies = {c.name: c.value for c in jar}
            if _has_auth(cookies):
                log.info(f"🍪 Browser-Fallback ({name}): {len(cookies)} Cookies, Auth vorhanden")
                return cookies
            if cookies:
                log.debug(f"  {name}: {len(cookies)} Cookies aber kein Auth-Cookie")
        except Exception as e:
            log.debug(f"  Browser-Fallback {name} fehlgeschlagen: {e}")

    log.warning("⚠️  Browser-Fallback: kein Auth-Cookie in Edge/Firefox/Chrome/Brave gefunden")
    return {}


def get_chromium_path() -> str | None:
    env_path = os.environ.get("CHROMIUM_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    base = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright")
    if not os.path.exists(base):
        return None
    matches = glob.glob(os.path.join(base, "chromium-*", "chrome-win64", "chrome.exe"))
    if matches:
        return matches[0]
    return None


def install_chromium() -> bool:
    log.info("📦 Chromium nicht gefunden – starte automatische Installation...")
    print("\n[~] Chromium wird zum ersten Mal installiert, bitte warten (~100MB)...")
    try:
        if getattr(sys, "frozen", False):
            playwright_cli = os.path.join(sys._MEIPASS, "playwright")
        else:
            playwright_cli = "playwright"
        result = subprocess.run(
            [playwright_cli, "install", "chromium"],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            log.info("✅ Chromium erfolgreich installiert!")
            return True
        log.error(f"❌ Playwright install fehlgeschlagen:\n{result.stderr}")
        return False
    except FileNotFoundError:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, timeout=300
            )
            return result.returncode == 0
        except Exception as e:
            log.error(f"❌ Installation fehlgeschlagen: {e}")
            return False
    except Exception as e:
        log.error(f"❌ Unerwarteter Fehler: {e}")
        return False


def ensure_chromium() -> str | None:
    path = get_chromium_path()
    if path:
        return path
    success = install_chromium()
    if not success:
        return None
    return get_chromium_path()


# Cookies die wir mindestens brauchen, damit die API-Calls durchgehen.
# _vinted_fr_session ist die anon-Session; v_udt / anon_id sind Begleiter.


def fetch_cookies_sync(domain: str) -> dict:
    """Holt frische Cookies via Playwright mit Cloudflare-Challenge-Handling."""
    for attempt in range(3):
        log.info(f"🍪 Hole Cookies via Playwright (Versuch {attempt + 1}/3)...")
        t_start = time.time()

        def _do_fetch():
            try:
                chromium_path = ensure_chromium()
                if not chromium_path:
                    log.warning("⚠️  Chromium nicht verfügbar.")
                    return {}
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(
                        executable_path=chromium_path,
                        headless=False,
                        args=[
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-blink-features=AutomationControlled",
                            "--disable-features=IsolateOrigins,site-per-process",
                            "--disable-gpu",
                            "--no-first-run",
                            "--no-default-browser-check",
                            "--disable-extensions",
                        ],
                        timeout=20_000,
                    )
                    try:
                        ctx = browser.new_context(
                            user_agent=(
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/147.0.0.0 Safari/537.36"
                            ),
                            locale="de-DE",
                            timezone_id="Europe/Berlin",
                            viewport={"width": 1920, "height": 1080},
                            device_scale_factor=1,
                            is_mobile=False,
                            has_touch=False,
                        )

                        # Aggressive Stealth-Patches gegen Cloudflare Bot-Detection
                        ctx.add_init_script("""
                            // webdriver komplett entfernen
                            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                            delete Object.getPrototypeOf(navigator).webdriver;

                            // Realistische Plugins
                            Object.defineProperty(navigator, 'plugins', {
                                get: () => [
                                    { name: 'PDF Viewer',        filename: 'internal-pdf-viewer' },
                                    { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer' },
                                    { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer' },
                                    { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer' },
                                    { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer' },
                                ]
                            });
                            Object.defineProperty(navigator, 'languages', {
                                get: () => ['de-DE', 'de', 'en-US', 'en']
                            });
                            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
                            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
                            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });

                            // window.chrome realistisch fälschen
                            window.chrome = {
                                runtime: {},
                                loadTimes: function(){},
                                csi: function(){},
                                app: { isInstalled: false }
                            };

                            // Permissions API realistisch
                            const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
                            if (originalQuery) {
                                window.navigator.permissions.query = (parameters) => (
                                    parameters.name === 'notifications'
                                        ? Promise.resolve({ state: Notification.permission })
                                        : originalQuery(parameters)
                                );
                            }

                            // WebGL Vendor-Fingerprint realistisch
                            const getParameter = WebGLRenderingContext.prototype.getParameter;
                            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                                if (parameter === 37445) return 'Intel Inc.';
                                if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                                return getParameter.apply(this, arguments);
                            };
                        """)

                        # Consent-Cookie vorsetzen
                        ctx.add_cookies([{
                            "name":   "OptanonAlertBoxClosed",
                            "value":  "2025-01-01T00:00:00.000Z",
                            "domain": f".{domain.replace('www.', '')}",
                            "path":   "/",
                        }])

                        page = ctx.new_page()

                        # KEIN Resource-Blocking — das ist selbst ein Bot-Signal
                        # für Cloudflare. Lieber 2s länger warten als geblockt werden.

                        # Navigation — domcontentloaded ist schnell und zuverlässig
                        try:
                            page.goto(
                                f"https://{domain}/catalog",
                                wait_until="domcontentloaded",
                                timeout=25_000,
                            )
                        except Exception as e:
                            log.warning(f"⚠️  goto /catalog fehlgeschlagen: {e} — versuche Homepage")
                            page.goto(
                                f"https://{domain}/",
                                wait_until="domcontentloaded",
                                timeout=20_000,
                            )

                        # Minimale "menschliche" Mausbewegung — hilft Turnstile
                        try:
                            page.mouse.move(300, 400)
                            page.wait_for_timeout(200)
                            page.mouse.move(600, 500, steps=10)
                            page.wait_for_timeout(300)
                        except Exception:
                            pass

                        # ─── Cookie-Polling mit Challenge-Handling ─────────────
                        # Max 30s warten. Wenn Cloudflare Challenge läuft, geben wir ihr Zeit.
                        POLL_BUDGET = 30
                        deadline = time.time() + POLL_BUDGET
                        challenge_logged = False
                        clearance_logged = False
                        reload_tried = False

                        while time.time() < deadline:
                            cookies_list = ctx.cookies()
                            names = {c["name"] for c in cookies_list}

                            # ✅ Auth da → fertig
                            if _has_auth(cookies_list):
                                elapsed = POLL_BUDGET - int(deadline - time.time())
                                auth_name = next(
                                    (c for c in AUTH_COOKIES_NEW + AUTH_COOKIES_OLD if c in names),
                                    "?"
                                )
                                log.info(f"🍪 Auth-Cookie '{auth_name}' nach {elapsed}s da")
                                break

                            # 🛡️ Cloudflare Challenge läuft
                            in_challenge = any(n.startswith("cf_chl") for n in names)
                            has_clearance = "cf_clearance" in names

                            if in_challenge and not challenge_logged:
                                log.info("🛡️  Cloudflare Challenge läuft — warte auf Turnstile-Lösung...")
                                challenge_logged = True

                            if has_clearance and not clearance_logged:
                                log.info("✅ cf_clearance gesetzt — Challenge bestanden, warte auf Auth...")
                                clearance_logged = True

                            # Wenn nach 15s immer noch in Challenge → Reload versuchen (einmal)
                            if in_challenge and not reload_tried and (POLL_BUDGET - int(deadline - time.time())) >= 15:
                                log.info("🔄 Challenge hängt — Reload...")
                                try:
                                    page.reload(wait_until="domcontentloaded", timeout=15_000)
                                except Exception:
                                    pass
                                reload_tried = True

                            page.wait_for_timeout(400)

                        # Final: Cookies einsammeln
                        cookies = {c["name"]: c["value"] for c in ctx.cookies()}

                        if not _has_auth(cookies):
                            log.warning(
                                f"⚠️  Auth-Cookie fehlt nach {POLL_BUDGET}s. "
                                f"Erhalten: {list(cookies.keys())}"
                            )
                            return cookies

                        log.info(f"🍪 {len(cookies)} Cookies erhalten: {list(cookies.keys())}")
                        return cookies
                    finally:
                        browser.close()
            except Exception as e:
                log.warning(f"⚠️  Browser-Fehler (Versuch {attempt+1}): {e}")
                return {}

        import threading, queue
        result_queue = queue.Queue()

        def worker():
            try:
                result_queue.put(("ok", _do_fetch()))
            except Exception as e:
                result_queue.put(("err", str(e)))

        t = threading.Thread(target=worker, daemon=False)
        t.start()
        # Max 70s pro Attempt (Launch 3s + goto 25s + polling 30s + close + puffer)
        t.join(timeout=45)

        try:
            status, data = result_queue.get_nowait()
            if status == "ok" and data and _has_auth(data):
                elapsed = time.time() - t_start
                log.info(f"✅ Cookies in {elapsed:.1f}s geholt")
                _save_cached_cookies(data)
                return data
            if status == "ok" and data:
                log.warning(f"⚠️  Cookies unvollständig (Versuch {attempt+1}) — retry...")
        except queue.Empty:
            log.error(f"❌ Cookie-Fetch Timeout (Versuch {attempt+1})")

        if attempt < 2:
            # Bei Challenges längerer Backoff — gibt Cloudflare Zeit dich zu "entspannen"
            backoff = 5 + attempt * 5  # 5s, 10s
            log.info(f"🔄 Warte {backoff}s vor erneutem Versuch...")
            time.sleep(backoff)

    log.error("❌ Alle Cookie-Fetch Versuche fehlgeschlagen – fahre ohne Cookies fort")
    return {}


REQUEST_INTERVAL_MIN = 1.5
REQUEST_INTERVAL_MAX = 4.0

USER_AGENTS = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
     '"Chromium";v="147", "Not(A:Brand";v="24", "Google Chrome";v="147"'),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
     '"Chromium";v="146", "Not(A:Brand";v="24", "Google Chrome";v="146"'),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
     '"Chromium";v="145", "Not(A:Brand";v="24", "Google Chrome";v="145"'),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
     '"Microsoft Edge";v="147", "Chromium";v="147", "Not(A:Brand";v="24"'),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
     '"Microsoft Edge";v="146", "Chromium";v="146", "Not(A:Brand";v="24"'),
]


class VintedFetcher:
    def __init__(self):
        self._session = None
        self._lock = asyncio.Lock()
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._req_count = 0
        self._cookies = {}
        self._session_created_at = 0
        self._consecutive_403 = 0
        # Stats für Heartbeat-Logging
        self.stat_ok       = 0
        self.stat_403      = 0
        self.stat_429      = 0
        self.stat_empty    = 0
        self.stat_err      = 0
        self.stat_items    = 0  # total items received

    async def _init_session(self, force_fresh: bool = False):
        """Initialisiert die aiohttp-Session.

        force_fresh=False: Cache probieren, sonst frisch holen (schneller Startup).
        force_fresh=True:  Cache invalidieren, immer frisch holen (z.B. nach 403).
        """
        log.info("🔄 Initialisiere neue Session...")

        cookies = {}

        if force_fresh:
            _invalidate_cache()

        # 1. Cache (schnellster Weg)
        if not force_fresh:
            cookies = _load_cached_cookies()

        # 2. Installierte Browser (Edge → Firefox → Chrome → Brave)
        if not _has_auth(cookies):
            log.info("🔍 Suche Cookies in installierten Browsern...")
            loop = asyncio.get_event_loop()
            browser_cookies = await loop.run_in_executor(None, fetch_cookies_from_browsers)
            if _has_auth(browser_cookies):
                cookies = browser_cookies
                _save_cached_cookies(cookies)

        # 5. Playwright-Fallback (öffnet Chromium-Fenster)
        if not _has_auth(cookies):
            log.info("🔄 Kein Auth-Cookie in Browsern — starte Playwright...")
            try:
                loop = asyncio.get_event_loop()
                cookies = await asyncio.wait_for(
                    loop.run_in_executor(None, fetch_cookies_sync, VINTED_DOMAIN),
                    timeout=180
                )
            except asyncio.TimeoutError:
                log.error("❌ Cookie-Fetch Timeout")
                cookies = {}
            except Exception as e:
                log.error(f"Cookie-Fetch Fehler: {e}")
                cookies = {}

        self._cookies = cookies or {}

        # CSRF (für Legacy-Auth)
        csrf = (
            self._cookies.get("CSRF-TOKEN")
            or self._cookies.get("csrf_token")
            or self._cookies.get("_vinted_fr_session", "")[:32]
            or ""
        )

        ua, sec_ch_ua = random.choice(USER_AGENTS)
        log.info(f"🌐 User-Agent: {ua[:60]}...")

        headers = {
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer":         f"https://{VINTED_DOMAIN}/catalog",
            "Origin":          f"https://{VINTED_DOMAIN}",
            "X-CSRF-Token":    csrf,
            "User-Agent":      ua,
            "Sec-Ch-Ua":          sec_ch_ua,
            "Sec-Ch-Ua-Mobile":   "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest":     "empty",
            "Sec-Fetch-Mode":     "cors",
            "Sec-Fetch-Site":     "same-origin",
        }

        # JWT Bearer Header — moderne Vinted-API-Authentifizierung
        access_token = self._cookies.get("access_token_web")
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        if self._session:
            await self._session.close()

        self._session = aiohttp.ClientSession(
            cookies=self._cookies,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self._req_count = 0
        self._session_created_at = time.time()
        self._consecutive_403 = 0
        log.info(f"✅ Session initialisiert ({len(self._cookies)} Cookies)")

    async def start(self):
        await self._init_session()

    async def close(self):
        if self._session:
            await self._session.close()

    def _session_expired(self) -> bool:
        return time.time() - self._session_created_at > SESSION_REFRESH_INTERVAL

    async def _rate_limit(self):
        """Erzwingt zufälligen Mindestabstand zwischen allen API-Calls."""
        async with self._rate_lock:
            now = time.time()
            wait = random.uniform(REQUEST_INTERVAL_MIN, REQUEST_INTERVAL_MAX) - (now - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.time()

    async def fetch_newest(self, search_text: str = "") -> list:
        params = {
            "order":         "newest_first",
            "per_page":      "30",
            "catalog_ids[]": "5",
        }
        if search_text:
            params["search_text"] = search_text

        await self._rate_limit()

        async with self._lock:
            # Session erneuern wenn abgelaufen oder zu viele Requests
            if self._req_count > 3000 or self._session_expired():
                log.info("🔄 Session-Rotation (planmäßig)...")
                await self._init_session(force_fresh=True)

            self._req_count += 1

            try:
                async with self._session.get(
                    CATALOG_ENDPOINT,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as r:

                    if r.status == 403:
                        self._consecutive_403 += 1
                        self.stat_403 += 1
                        log.warning(f"⚠️  403 Forbidden (#{self._consecutive_403}) – Session wird erneuert...")
                        # Cache invalidieren (Cookies sind verbrannt) + frisch holen
                        await self._init_session(force_fresh=True)
                        return []

                    if r.status == 429:
                        self.stat_429 += 1
                        wait = min(int(r.headers.get("Retry-After", 30)), 30)
                        log.warning(f"⏳ Rate limit – warte {wait}s")
                        await asyncio.sleep(wait)
                        return []

                    if r.status not in (200, 201):
                        self.stat_err += 1
                        log.debug(f"HTTP {r.status} für '{search_text}'")
                        return []

                    self._consecutive_403 = 0
                    data = await r.json()
                    items = data.get("items") or []
                    if items:
                        self.stat_ok += 1
                        self.stat_items += len(items)
                    else:
                        self.stat_empty += 1
                    return items

            except asyncio.TimeoutError:
                self.stat_err += 1
                return []
            except Exception as e:
                self.stat_err += 1
                log.debug(f"HTTP Fehler: {e}")
                return []

    async def fetch_user(self, user_id) -> dict:
        try:
            url = USER_ENDPOINT.format(user_id)
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status not in (200, 201):
                    return {}
                data = await r.json()
                return data.get("user") or {}
        except Exception:
            return {}