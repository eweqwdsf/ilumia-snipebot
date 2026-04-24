"""
bridge.py — ILUMIA Python Backend
----------------------------------
SECURITY:
  - Supabase-Credentials (URL + KEY) NUR in deiner .env — niemals im Kunden-Bundle
  - BRIDGE_SECRET schützt alle HTTP-Endpunkte zwischen Electron und Bridge
  - Discord Token / Channel ID werden aus Supabase (bot_config) geladen — kein .env beim Kunden
  - HWID-Validierung gegen den License-Eintrag bei jedem Config-Zugriff

KUNDE-FLOW:
  App starten → License Key eingeben → Bridge lädt bot_config aus Supabase → Bot startet
  Der Kunde sieht niemals einen Token, eine URL oder einen API-Key.
"""
import os, sys, json, hashlib, uuid, re, threading, subprocess, traceback
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

from supabase import create_client, Client

# Lade .env Datei — suche in mehreren möglichen Pfaden
# Bei PyInstaller frozen .exe zeigt __file__ auf den Temp-Ordner (_MEIxxxxxx),
# deshalb nutzen wir sys.executable für den echten Pfad der .exe
if getattr(sys, "frozen", False):
    _exe_dir = os.path.dirname(sys.executable)  # z.B. resources/python/
else:
    _exe_dir = os.path.dirname(os.path.abspath(__file__))

_env_candidates = [
    os.path.join(_exe_dir, ".env"),                        # resources/python/.env  ← korrekt
    os.path.join(_exe_dir, "..", ".env"),                  # resources/.env
    os.path.join(_exe_dir, "..", "python", ".env"),        # resources/python/.env (alt)
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),  # Fallback __file__
]
for _ep in _env_candidates:
    _ep_abs = os.path.abspath(_ep)
    if os.path.exists(_ep_abs):
        load_dotenv(_ep_abs)
        print(f"[bridge] Loaded .env from: {_ep_abs}")
        break
else:
    print(f"[bridge] WARNING: .env nicht gefunden, gesucht in: {[os.path.abspath(p) for p in _env_candidates]}")

# ==========================================
# CONFIG — nur aus Umgebung, niemals hardcoded
# ==========================================
PORT        = int(os.environ.get("BRIDGE_PORT", 57421))

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()  # anon key, kein service_role!

# Geteiltes Secret zwischen Electron-Main und diesem Bridge-Server.
# Muss in .env gesetzt sein (z.B. zufälliger hex-String).
BRIDGE_SECRET = os.getenv("BRIDGE_SECRET", "").strip()

# ── Startup-Validierung ───────────────────────────────────────────────────────
_missing = [k for k, v in {
    "SUPABASE_URL":   SUPABASE_URL,
    "SUPABASE_KEY":   SUPABASE_KEY,
    "BRIDGE_SECRET":  BRIDGE_SECRET,
}.items() if not v]

if _missing:
    print(f"[bridge] FEHLER: Folgende .env-Variablen fehlen: {', '.join(_missing)}")
    print("[bridge] Erstelle eine .env Datei basierend auf .env.example")
    sys.exit(1)

if len(BRIDGE_SECRET) < 16:
    print("[bridge] WARNUNG: BRIDGE_SECRET ist zu kurz (min. 16 Zeichen empfohlen).")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Bot-Config Cache (aus Supabase bot_config Tabelle) ────────────────────────
_bot_config_cache: dict | None = None
_bot_config_lock  = threading.Lock()

def load_bot_config(force_refresh: bool = False) -> dict:
    """
    Lädt die globale Bot-Config aus Supabase (bot_config Tabelle).
    Cached nach erstem Aufruf — force_refresh=True holt neu.
    Gibt leeres dict zurück wenn nicht erreichbar (kein Crash).
    """
    global _bot_config_cache
    with _bot_config_lock:
        if _bot_config_cache is not None and not force_refresh:
            return _bot_config_cache
        try:
            res = supabase.table("bot_config").select("*").limit(1).execute()
            rows = res.data or []
            if rows:
                _bot_config_cache = rows[0]
                print(f"[bridge] bot_config geladen: discord_channel_id={rows[0].get('discord_channel_id','?')}")
            else:
                print("[bridge] WARNUNG: bot_config Tabelle ist leer! Bot kann nicht starten.")
                _bot_config_cache = {}
        except Exception as e:
            print(f"[bridge] FEHLER beim Laden von bot_config: {e}")
            _bot_config_cache = {}
        return _bot_config_cache
first_item_found: bool = False
bot_process = None
bot_last_error: str = ""
_state_lock = threading.Lock()


# ==========================================
# WINDOWS JOB OBJECT — alle Kindprozesse sterben mit der Bridge
# ==========================================
_job_handle = None

def _setup_job_object():
    """
    Erstellt ein Windows Job Object mit JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
    Alle Prozesse die wir spawnen werden dem Job hinzugefügt.
    Wenn bridge.py stirbt (egal wie), killt Windows automatisch alle Kinder.
    """
    global _job_handle
    try:
        import ctypes, ctypes.wintypes
        kernel32 = ctypes.windll.kernel32

        # Job Object erstellen
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return

        # JOBOBJECT_BASIC_LIMIT_INFORMATION + JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [("ReadOperationCount",  ctypes.c_uint64),
                        ("WriteOperationCount", ctypes.c_uint64),
                        ("OtherOperationCount", ctypes.c_uint64),
                        ("ReadTransferCount",   ctypes.c_uint64),
                        ("WriteTransferCount",  ctypes.c_uint64),
                        ("OtherTransferCount",  ctypes.c_uint64)]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit",      ctypes.c_int64),
                        ("LimitFlags",              ctypes.wintypes.DWORD),
                        ("MinimumWorkingSetSize",   ctypes.c_size_t),
                        ("MaximumWorkingSetSize",   ctypes.c_size_t),
                        ("ActiveProcessLimit",      ctypes.wintypes.DWORD),
                        ("Affinity",                ctypes.POINTER(ctypes.c_ulong)),
                        ("PriorityClass",           ctypes.wintypes.DWORD),
                        ("SchedulingClass",         ctypes.wintypes.DWORD)]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                        ("IoInfo",                IO_COUNTERS),
                        ("ProcessMemoryLimit",    ctypes.c_size_t),
                        ("JobMemoryLimit",        ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed",     ctypes.c_size_t)]

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE

        JobObjectExtendedLimitInformation = 9
        kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info)
        )

        # Bridge selbst dem Job hinzufügen
        current = kernel32.GetCurrentProcess()
        kernel32.AssignProcessToJobObject(job, current)

        _job_handle = job
        print("[bridge] Job Object erstellt — Kindprozesse sterben automatisch mit.")
    except Exception as e:
        print(f"[bridge] Job Object nicht verfügbar: {e} — nutze taskkill-Fallback.")

_setup_job_object()


def _add_to_job(proc):
    """Fügt einen Subprozess zum Job Object hinzu."""
    global _job_handle
    if not _job_handle or not proc:
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        import msvcrt
        handle = kernel32.OpenProcess(0x001F0FFF, False, proc.pid)  # PROCESS_ALL_ACCESS
        if handle:
            kernel32.AssignProcessToJobObject(_job_handle, handle)
            kernel32.CloseHandle(handle)
    except Exception:
        pass


def kill_process_tree(proc):
    """Kill a process and all its children — 3-layer approach."""
    if proc is None:
        return
    pid = proc.pid
    if not pid:
        return

    # Layer 1: taskkill /T /F — killt den Prozessbaum
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
        )
    except Exception:
        pass

    # Layer 2: direkt via proc.kill()
    try:
        proc.kill()
    except Exception:
        pass


def kill_all_python_children():
    """
    Nuklearer Fallback: killt ALLE python.exe / main_bot.exe Prozesse
    die von unserem Prozess abstammen — via wmic.
    """
    our_pid = os.getpid()
    try:
        # Alle Kindprozesse des aktuellen Prozesses finden und killen
        subprocess.run(
            ["wmic", "process", "where",
             f"(name='python.exe' or name='main_bot.exe' or name='chrome.exe')",
             "delete"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
        )
    except Exception:
        pass
    # Zusätzlich: alle Prozesse die BRIDGE_SECRET als Env-Var haben
    # (das sind garantiert unsere Kinder) — via taskkill auf bekannte Namen
    for name in ("main_bot.exe", "chrome.exe"):
        try:
            subprocess.run(
                ["taskkill", "/IM", name, "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3
            )
        except Exception:
            pass


def reset_bot_state():
    global first_item_found, bot_last_error
    with _state_lock:
        first_item_found = False
        bot_last_error   = ""


# ==========================================
# PATHS
# ==========================================
if getattr(sys, "frozen", False):
    BASE_DIR     = os.path.dirname(sys.executable)
    INTERNAL_DIR = BASE_DIR
else:
    BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    INTERNAL_DIR = os.path.join(BASE_DIR, "python")

LICENSE_FILE = os.path.join(BASE_DIR, "license.txt")

print(f"[bridge] BASE_DIR:     {BASE_DIR}")
print(f"[bridge] INTERNAL_DIR: {INTERNAL_DIR}")
sys.stdout.flush()


def _read_version() -> str:
    HARDCODED_VERSION = "1.8.0"
    try:
        pkg = os.path.join(BASE_DIR, "package.json")
        if os.path.exists(pkg):
            with open(pkg, encoding="utf-8") as f:
                return "v" + json.load(f).get("version", HARDCODED_VERSION)
    except Exception:
        pass
    return "v" + HARDCODED_VERSION


CURRENT_VERSION = _read_version()
print(f"[bridge] Version: {CURRENT_VERSION}")
sys.stdout.flush()


# ==========================================
# CORE LOGIC
# ==========================================
_hwid_cache: str | None = None

def get_hwid() -> str:
    global _hwid_cache
    if _hwid_cache is not None:
        return _hwid_cache

    NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

    # Junk-Werte die Hersteller eintragen wenn sie nichts sinnvolles haben
    JUNK = {
        "to be filled by o.e.m.", "default string", "none", "n/a",
        "0", "", "unknown", "not applicable", "system serial number",
        "base board serial number", "serial number", "ffffffff-ffff-ffff-ffff-ffffffffffff",
        "00000000-0000-0000-0000-000000000000",
    }

    def ps(cmd: str) -> str:
        """PowerShell-Aufruf — gibt leeren String bei Fehler zurück."""
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW
            )
            return r.stdout.replace('\r', '').replace('\n', '').strip()
        except Exception:
            return ""

    def clean(val: str) -> str:
        """Gibt leeren String zurück wenn der Wert Junk ist."""
        return "" if val.lower() in JUNK else val

    # ── Methode 1: WMI Win32_ComputerSystemProduct (Standard) ────────────────
    bios_uuid = clean(ps("(Get-WmiObject Win32_ComputerSystemProduct).UUID"))

    # ── Methode 2: WMI Win32_BaseBoard SerialNumber ───────────────────────────
    baseboard = clean(ps("(Get-WmiObject Win32_BaseBoard).SerialNumber"))

    # ── Methode 3: WMIC Fallback (ältere Windows-Versionen) ──────────────────
    if not bios_uuid:
        bios_uuid = clean(ps("(wmic csproduct get UUID /value) -replace '.*=',''"))
    if not baseboard:
        baseboard = clean(ps("(wmic baseboard get SerialNumber /value) -replace '.*=',''"))

    # ── Methode 4: CIM als letzter Fallback (PowerShell 5+) ──────────────────
    if not bios_uuid:
        bios_uuid = clean(ps("(Get-CimInstance Win32_ComputerSystemProduct).UUID"))
    if not baseboard:
        baseboard = clean(ps("(Get-CimInstance Win32_BaseBoard).SerialNumber"))

    # ── Methode 5: Disk Serial als Notfall-Fallback ───────────────────────────
    # Wenn weder UUID noch Baseboard verfügbar → Disk-Seriennummer nehmen.
    # Das ist stabiler als ein zufälliger Hash und bleibt beim selben PC gleich.
    disk_serial = ""
    if not bios_uuid and not baseboard:
        disk_serial = clean(ps(
            "(Get-WmiObject Win32_DiskDrive | Select-Object -First 1).SerialNumber"
        ))
        if not disk_serial:
            disk_serial = clean(ps(
                "(Get-CimInstance Win32_DiskDrive | Select-Object -First 1).SerialNumber"
            ))

    # ── Ergebnis zusammenbauen ────────────────────────────────────────────────
    if bios_uuid and baseboard:
        result = f"{bios_uuid} | {baseboard}"
    elif bios_uuid:
        result = bios_uuid
    elif baseboard:
        result = baseboard
    elif disk_serial:
        result = f"DISK-{disk_serial}"
    else:
        # Absoluter Notfall: MAC-Adresse (bleibt beim selben PC konstant)
        mac = ':'.join(
            f"{(uuid.getnode() >> (i * 8)) & 0xFF:02X}"
            for i in reversed(range(6))
        )
        result = f"MAC-{mac}"

    print(f"[bridge] HWID: {result}")
    _hwid_cache = result
    return result


def load_saved_key() -> str | None:
    if os.path.exists(LICENSE_FILE):
        with open(LICENSE_FILE) as f:
            v = f.read().strip()
            return v or None
    return None


def save_key(key: str):
    with open(LICENSE_FILE, "w") as f:
        f.write(key)


def check_license(key: str, hwid: str) -> tuple[bool, str]:
    if key == "__load_saved__":
        key = load_saved_key()
        if not key:
            return False, "No saved key."
    try:
        result = supabase.table("licenses").select("*").eq("key", key).execute()
    except Exception as e:
        return False, f"Database error: {e}"
    rows = result.data
    if not rows:
        return False, "Key not found."
    row = rows[0]
    locked = row.get("hwid_locked")
    if locked and locked != hwid:
        return False, "Key registered to another HWID."
    activated_at  = row.get("activated_at")
    duration_days = row.get("duration_days", 0)
    if activated_at:
        activated_dt = datetime.fromisoformat(activated_at)
        expires_dt   = activated_dt + timedelta(days=duration_days)
        now          = datetime.now(timezone.utc)
        if now > expires_dt:
            return False, f"Key expired on {expires_dt.strftime('%d.%m.%Y')}."
        days_left = (expires_dt - now).days
        suffix = "day" if days_left == 1 else "days"
        return True, f"Valid for {days_left} more {suffix}"
    else:
        now_iso    = datetime.now(timezone.utc).isoformat()
        expires_dt = datetime.now(timezone.utc) + timedelta(days=duration_days)
        try:
            supabase.table("licenses").update({
                "activated_at": now_iso,
                "hwid_locked":  hwid,
            }).eq("key", key).execute()
        except Exception as e:
            return False, f"Activation error: {e}"
        save_key(key)
        return True, f"Activated — expires on {expires_dt.strftime('%d.%m.%Y')}"


# ==========================================
# USER CONFIG STORE (Supabase)
# ==========================================
MAX_CONFIGS_PER_USER = 3

DEFAULT_CONFIG = {
    "hype_keywords": [
        "vintage", "y2k", "90s", "2000s", "jersey", "trikot",
        "tracksuit", "windbreaker", "baggy", "jeans", "puffer",
    ],
    "core_brands": [
        "nike", "adidas", "lacoste", "ralph lauren", "polo",
        "corteiz", "chrome hearts", "stussy", "carhartt",
        "stone island", "fred perry", "levis", "true religion",
    ],
    "blacklist": [
        "zara", "h&m", "shein", "asos", "primark",
        "damen", "frau", "women", "kids", "kinder",
    ],
    "permitted_sizes": ["s", "m", "l", "xl", "44", "46", "48", "50", "52"],
    "price_min": 5.0,
    "price_max": 65.0,
}


def _verify_config_owner(hwid: str, config_id: str) -> bool:
    """Sicherstellen, dass config_id wirklich dieser HWID gehört."""
    try:
        res = (
            supabase.table("user_configs")
            .select("id")
            .eq("id", config_id)
            .eq("hwid", hwid)
            .execute()
        )
        return bool(res.data)
    except Exception:
        return False


def list_configs(hwid: str) -> list:
    try:
        res = (
            supabase.table("user_configs")
            .select("*")
            .eq("hwid", hwid)
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        print(f"[bridge] list_configs error: {e}")
        return []


def get_active_config(hwid: str) -> dict | None:
    try:
        res = (
            supabase.table("user_configs")
            .select("*")
            .eq("hwid", hwid)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:
        print(f"[bridge] get_active_config error: {e}")
        return None


def save_config(hwid: str, config_id: str | None, name: str, data: dict) -> tuple[bool, str, dict | None]:
    name = (name or "").strip()
    if not name:
        return False, "Name cannot be empty.", None
    if len(name) > 40:
        return False, "Name too long (max 40 chars).", None

    payload = {
        "hwid":            hwid,
        "name":            name,
        "hype_keywords":   _clean_list(data.get("hype_keywords")),
        "core_brands":     _clean_list(data.get("core_brands")),
        "blacklist":       _clean_list(data.get("blacklist")),
        "permitted_sizes": _clean_list(data.get("permitted_sizes")),
        "price_min":       _clean_price(data.get("price_min"), DEFAULT_CONFIG["price_min"]),
        "price_max":       _clean_price(data.get("price_max"), DEFAULT_CONFIG["price_max"]),
    }

    if payload["price_min"] > payload["price_max"]:
        return False, "Min price cannot exceed max price.", None

    try:
        if config_id:
            # Ownership prüfen bevor Update
            if not _verify_config_owner(hwid, config_id):
                return False, "Config not found.", None
            res = (
                supabase.table("user_configs")
                .update(payload)
                .eq("id", config_id)
                .eq("hwid", hwid)
                .execute()
            )
            rows = res.data or []
            if not rows:
                return False, "Config not found.", None
            return True, "Config updated.", rows[0]
        else:
            existing = list_configs(hwid)
            if len(existing) >= MAX_CONFIGS_PER_USER:
                return False, f"Limit reached (max {MAX_CONFIGS_PER_USER} configs).", None
            payload["is_active"] = (len(existing) == 0)
            res = supabase.table("user_configs").insert(payload).execute()
            rows = res.data or []
            if not rows:
                return False, "Failed to create config.", None
            return True, "Config created.", rows[0]
    except Exception as e:
        return False, f"Database error: {e}", None


def delete_config(hwid: str, config_id: str) -> tuple[bool, str]:
    if not _verify_config_owner(hwid, config_id):
        return False, "Config not found."
    try:
        res = (
            supabase.table("user_configs")
            .delete()
            .eq("id", config_id)
            .eq("hwid", hwid)
            .execute()
        )
        if not (res.data or []):
            return False, "Config not found."
        return True, "Config deleted."
    except Exception as e:
        return False, f"Database error: {e}"


def activate_config(hwid: str, config_id: str) -> tuple[bool, str]:
    if not _verify_config_owner(hwid, config_id):
        return False, "Config not found."
    try:
        supabase.table("user_configs").update({"is_active": False}).eq("hwid", hwid).execute()
        res = (
            supabase.table("user_configs")
            .update({"is_active": True})
            .eq("id", config_id)
            .eq("hwid", hwid)
            .execute()
        )
        if not (res.data or []):
            return False, "Config not found."
        return True, "Config activated."
    except Exception as e:
        return False, f"Database error: {e}"


def _clean_list(v) -> list:
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        s = str(x).strip().lower()
        if s and s not in out:
            out.append(s)
    return out[:200]


def _clean_price(v, fallback: float) -> float:
    try:
        return max(0.0, min(99999.0, float(v)))
    except (TypeError, ValueError):
        return float(fallback)


def _pack_config(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id":              row.get("id"),
        "name":            row.get("name", ""),
        "is_active":       bool(row.get("is_active")),
        "hype_keywords":   row.get("hype_keywords") or [],
        "core_brands":     row.get("core_brands") or [],
        "blacklist":       row.get("blacklist") or [],
        "permitted_sizes": row.get("permitted_sizes") or [],
        "price_min":       float(row.get("price_min") or DEFAULT_CONFIG["price_min"]),
        "price_max":       float(row.get("price_max") or DEFAULT_CONFIG["price_max"]),
    }


# ==========================================
# BOT LAUNCHER
# ==========================================
def find_python() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable
    import shutil as _sh
    found = _sh.which("python") or _sh.which("python3")
    if found:
        return found
    candidates = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        import glob
        candidates += glob.glob(os.path.join(local, "Programs", "Python", "Python3*", "python.exe"))
        candidates += glob.glob(os.path.join(local, "Programs", "Python", "Python*",  "python.exe"))
    prog = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    candidates += [
        os.path.join(prog, "Python311", "python.exe"),
        os.path.join(prog, "Python310", "python.exe"),
        os.path.join(prog, "Python312", "python.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "python"


def start_bot():
    global bot_process

    if bot_process and bot_process.poll() is None:
        print("[bridge] Killing old bot instance")
        kill_process_tree(bot_process)

    bot_path = os.path.join(INTERNAL_DIR, "main_bot.py")
    bot_exe  = os.path.join(INTERNAL_DIR, "main_bot.exe")

    # Prüfe ob Bot-Executable vorhanden
    if not os.path.exists(bot_exe) and not os.path.exists(bot_path):
        print("[bridge] ERROR: main_bot.exe / main_bot.py nicht gefunden!")
        sys.stdout.flush()
        return

    # ── Bot-Config aus Supabase laden ────────────────────────────────────────
    cfg = load_bot_config(force_refresh=True)
    discord_token      = str(cfg.get("discord_bot_token",  "") or "").strip()
    discord_channel_id = str(cfg.get("discord_channel_id", "") or "").strip()
    admin_user_ids     = str(cfg.get("admin_user_ids",     "") or "").strip()
    discord_guild_id   = str(cfg.get("discord_guild_id",  "") or "").strip()
    twocaptcha_key     = str(cfg.get("twocaptcha_api_key", "") or "").strip()

    if not discord_token:
        print("[bridge] FEHLER: discord_bot_token fehlt in bot_config! Bot startet nicht.")
        sys.stdout.flush()
        return
    if not discord_channel_id:
        print("[bridge] FEHLER: discord_channel_id fehlt in bot_config! Bot startet nicht.")
        sys.stdout.flush()
        return

    print(f"[bridge] Bot path:   {bot_exe if os.path.exists(bot_exe) else bot_path}")
    sys.stdout.flush()

    reset_bot_state()

    try:
        if os.path.exists(bot_exe):
            cmd = [bot_exe]
        else:
            python_exe = find_python()
            cmd = [python_exe, "-u", bot_path]

        # ── Chromium Pfad finden ──────────────────────────────────────────────
        # Im gepackten Electron-Bundle liegt chromium/ im resources/ Ordner
        # Wir prüfen mehrere mögliche Pfade
        chromium_candidates = [
            os.path.join(BASE_DIR, "..", "chromium", "chrome.exe"),          # Electron resources/
            os.path.join(BASE_DIR, "chromium", "chrome.exe"),                # Direkt neben bridge.exe
            os.path.join(BASE_DIR, "..", "..", "chromium", "chrome.exe"),    # Einen Level höher
        ]
        bundled_chromium = None
        for _cp in chromium_candidates:
            _cp_abs = os.path.abspath(_cp)
            if os.path.exists(_cp_abs):
                bundled_chromium = _cp_abs
                print(f"[bridge] Chromium gefunden: {bundled_chromium}")
                break

        if not bundled_chromium:
            print(f"[bridge] WARNUNG: Chromium nicht gefunden! Gesucht in: {[os.path.abspath(c) for c in chromium_candidates]}")
        extra_env = {
            # Bridge-Kommunikation
            "BRIDGE_PORT":         str(PORT),
            "BRIDGE_SECRET":       BRIDGE_SECRET,
            "PYTHONUNBUFFERED":    "1",
            # Discord-Config aus Supabase — Kunde sieht das nie
            "DISCORD_BOT_TOKEN":   discord_token,
            "DISCORD_CHANNEL_ID":  discord_channel_id,
            "ADMIN_USER_IDS":      admin_user_ids,
            "DISCORD_GUILD_ID":    discord_guild_id,
            "TWOCAPTCHA_API_KEY":  twocaptcha_key,
            # Supabase (für den Bot selbst — License-Checks etc.)
            "SUPABASE_URL":        SUPABASE_URL,
            "SUPABASE_KEY":        SUPABASE_KEY,
        }
        if bundled_chromium:
            extra_env["CHROMIUM_PATH"] = bundled_chromium

        bot_process = subprocess.Popen(
            cmd,
            cwd=INTERNAL_DIR,
            env={**os.environ, **extra_env},
            stdout=None,
            stderr=None,
        )

        print(f"[bridge] Bot PID: {bot_process.pid}")
        _add_to_job(bot_process)
        sys.stdout.flush()

    except Exception:
        print("[bridge] FAILED to start bot:")
        traceback.print_exc()
        sys.stdout.flush()


# ==========================================
# HTTP REQUEST HANDLER
# ==========================================
class BridgeHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # Kein HTTP-Logging im Terminal

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw    = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _send(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self) -> bool:
        """Prüft den X-Bridge-Secret Header."""
        return self.headers.get("X-Bridge-Secret", "") == BRIDGE_SECRET

    def do_POST(self):
        req_path = self.path

        # /ping und /item-found brauchen ebenfalls Auth
        if not self._auth_ok():
            self._send({"error": "Unauthorized"}, 401)
            return

        body = self._read_body()

        if req_path == "/ping":
            self._send({"ok": True})

        elif req_path == "/hwid":
            self._send({"hwid": get_hwid()})

        elif req_path == "/check-license":
            key  = body.get("key", "")
            hwid = get_hwid()
            valid, info = check_license(key, hwid)
            resolved_key = key if key != "__load_saved__" else (load_saved_key() or key)
            self._send({"valid": valid, "info": info, "key": resolved_key})

        elif req_path == "/start-bot":
            key = body.get("key", "")
            print(f"[bridge] /start-bot received, key={key[:8]}...")
            sys.stdout.flush()
            start_bot()
            self._send({"ok": True, "action": "bot_started"})

        elif req_path == "/item-found":
            global first_item_found
            with _state_lock:
                first_item_found = True
            self._send({"ok": True})

        elif req_path == "/poll-status":
            with _state_lock:
                found = first_item_found
            self._send({"first_item_found": found})

        elif req_path == "/get-filters":
            # Legacy-Endpunkt — weiterleiten auf active-config
            hwid = get_hwid()
            row  = get_active_config(hwid)
            self._send({"filters": _pack_config(row)})

        elif req_path == "/bot-error":
            bot_path = os.path.join(INTERNAL_DIR, "main_bot.py")
            bot_exe  = os.path.join(INTERNAL_DIR, "main_bot.exe")
            # Chromium suchen
            chromium_candidates = [
                os.path.abspath(os.path.join(BASE_DIR, "..", "chromium", "chrome.exe")),
                os.path.abspath(os.path.join(BASE_DIR, "chromium", "chrome.exe")),
                os.path.abspath(os.path.join(BASE_DIR, "..", "..", "chromium", "chrome.exe")),
            ]
            chromium_found = next((p for p in chromium_candidates if os.path.exists(p)), None)
            with _state_lock:
                err = bot_last_error
            self._send({
                "error":             err,
                "running":           bot_process is not None and bot_process.poll() is None,
                "internal_dir":      INTERNAL_DIR,
                "base_dir":          BASE_DIR,
                "bot_path":          bot_path,
                "bot_exe":           bot_exe,
                "bot_exists":        os.path.exists(bot_exe) or os.path.exists(bot_path),
                "python_exe":        find_python(),
                "chromium_path":     chromium_found or "NOT FOUND",
                "chromium_searched": chromium_candidates,
            })

        elif req_path == "/list-configs":
            hwid = get_hwid()
            rows = list_configs(hwid)
            self._send({
                "configs":  [_pack_config(r) for r in rows],
                "max":      MAX_CONFIGS_PER_USER,
                "defaults": DEFAULT_CONFIG,
            })

        elif req_path == "/save-config":
            hwid      = get_hwid()
            config_id = body.get("id")
            name      = body.get("name", "")
            data      = body.get("data", {}) or {}
            ok, msg, row = save_config(hwid, config_id, name, data)
            self._send({"ok": ok, "message": msg, "config": _pack_config(row)})

        elif req_path == "/delete-config":
            hwid      = get_hwid()
            config_id = body.get("id", "")
            ok, msg   = delete_config(hwid, config_id)
            self._send({"ok": ok, "message": msg})

        elif req_path == "/activate-config":
            hwid      = get_hwid()
            config_id = body.get("id", "")
            ok, msg   = activate_config(hwid, config_id)
            self._send({"ok": ok, "message": msg})

        elif req_path == "/active-config":
            hwid = get_hwid()
            row  = get_active_config(hwid)
            self._send({"config": _pack_config(row), "defaults": DEFAULT_CONFIG})

        elif req_path == "/shutdown":
            # Electron calls this before quitting — kill bot tree then self-exit
            kill_process_tree(bot_process)
            kill_all_python_children()
            self._send({"ok": True})
            threading.Thread(target=lambda: (
                __import__("time").sleep(0.3),
                os.kill(os.getpid(), 9)
            ), daemon=True).start()

        else:
            self._send({"error": "unknown endpoint"}, 404)


# ==========================================
# ENTRY POINT
# ==========================================
if __name__ == "__main__":
    # ThreadingHTTPServer: each request runs in its own thread so the UI's
    # /poll-status doesn't block the bot's /item-found or /active-config calls.
    server = ThreadingHTTPServer(("127.0.0.1", PORT), BridgeHandler)
    server.allow_reuse_address = True
    print(f"[bridge] Listening on 127.0.0.1:{PORT}")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[bridge] Shutting down.")
        if bot_process and bot_process.poll() is None:
            kill_process_tree(bot_process)
        kill_all_python_children()