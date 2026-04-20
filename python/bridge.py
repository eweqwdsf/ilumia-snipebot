"""
bridge.py — ILUMIA Python Backend
"""
import os, sys, json, hashlib, uuid, re, threading, subprocess, shutil, traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

from supabase import create_client, Client

# Lade .env Datei
load_dotenv()

# ==========================================
# CONFIG
# ==========================================
GITHUB_REPO = "eweqwdsf/ilumia-snipebot"
EXE_NAME    = "ILUMIA-Setup.exe"
PORT        = int(os.environ.get("BRIDGE_PORT", 57421))

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ikshnlooivixiembblqw.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlrc2hubG9vaXZpeGllbWJibHF3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTgzNDM5MiwiZXhwIjoyMDkxNDEwMzkyfQ.BHFwopTwmAoboIn-QliIOpnw4HVQLd_tW-gBD0vCh6w")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Shared state
first_item_found: bool = False
bot_process = None
bot_last_error: str = ""

def reset_bot_state():
    global first_item_found, bot_last_error
    first_item_found = False
    bot_last_error = ""

# ==========================================
# PATHS
# ==========================================
if getattr(sys, "frozen", False):
    BASE_DIR     = os.path.dirname(sys.executable)
    INTERNAL_DIR = sys._MEIPASS
else:
    BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    INTERNAL_DIR = os.path.join(BASE_DIR, "python")

LICENSE_FILE = os.path.join(BASE_DIR, "license.txt")

print(f"[bridge] BASE_DIR:     {BASE_DIR}")
print(f"[bridge] INTERNAL_DIR: {INTERNAL_DIR}")
sys.stdout.flush()

# Version lesen — Hardcoded als Fallback damit gepackte .exe die richtige Version kennt
# ⚠️  BEI JEDEM RELEASE: HARDCODED_VERSION synchron zu package.json halten!
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
def get_hwid() -> str:
    mac  = str(uuid.getnode())
    comp = os.getenv("COMPUTERNAME", "PC")
    return hashlib.sha256((mac + comp).encode()).hexdigest().upper()

def load_saved_key():
    if os.path.exists(LICENSE_FILE):
        with open(LICENSE_FILE) as f:
            v = f.read().strip()
            return v or None
    return None

def save_key(key: str):
    with open(LICENSE_FILE, "w") as f:
        f.write(key)

def check_license(key: str, hwid: str):
    if key == "__load_saved__":
        key = load_saved_key()
        if not key:
            return False, "Kein gespeicherter Key."
    try:
        result = supabase.table("licenses").select("*").eq("key", key).execute()
    except Exception as e:
        return False, f"Datenbankfehler: {e}"
    rows = result.data
    if not rows:
        return False, "Key nicht gefunden."
    row = rows[0]
    locked = row.get("hwid_locked")
    if locked and locked != hwid:
        return False, "Key ist auf ein anderes Geraet gesperrt."
    activated_at  = row.get("activated_at")
    duration_days = row.get("duration_days", 0)
    if activated_at:
        activated_dt = datetime.fromisoformat(activated_at)
        expires_dt   = activated_dt + timedelta(days=duration_days)
        now          = datetime.now(timezone.utc)
        if now > expires_dt:
            return False, f"Key abgelaufen am {expires_dt.strftime('%d.%m.%Y')}."
        return True, f"Gueltig noch {(expires_dt - now).days} Tag(e)"
    else:
        now_iso    = datetime.now(timezone.utc).isoformat()
        expires_dt = datetime.now(timezone.utc) + timedelta(days=duration_days)
        try:
            supabase.table("licenses").update({
                "activated_at": now_iso,
                "hwid_locked":  hwid,
            }).eq("key", key).execute()
        except Exception as e:
            return False, f"Aktivierungsfehler: {e}"
        save_key(key)
        return True, f"Aktiviert — laeuft ab am {expires_dt.strftime('%d.%m.%Y')}"

def _parse_version(v: str):
    try:
        parts = v.strip().lstrip("v").split(".")
        return tuple(int(x) for x in parts if x.strip().isdigit())
    except Exception:
        return (0, 0, 0)

def check_for_update() -> dict:
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "ILUMIA-SnipeBot"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
        latest = data.get("tag_name", "")
        if latest and _parse_version(latest) > _parse_version(CURRENT_VERSION):
            for asset in data.get("assets", []):
                if asset["name"] == EXE_NAME:
                    return {"has_update": True, "version": latest,
                            "url": asset["browser_download_url"]}
        return {"has_update": False, "version": CURRENT_VERSION}
    except Exception:
        return {"has_update": False, "version": CURRENT_VERSION}

def do_update(download_url: str, new_version: str):
    """Download new installer and launch it."""
    try:
        import tempfile
        tmp_dir     = tempfile.gettempdir()
        installer   = os.path.join(tmp_dir, "ILUMIA-Setup.exe")

        print(f"[bridge] Downloading update to {installer}...")
        sys.stdout.flush()

        req = urllib.request.Request(download_url, headers={"User-Agent": "ILUMIA-SnipeBot"})
        with urllib.request.urlopen(req, timeout=120) as r, open(installer, "wb") as f:
            shutil.copyfileobj(r, f)

        print(f"[bridge] Download complete — launching installer")
        sys.stdout.flush()

        # Create batch script: run installer, wait, then restart app
        batch_file = os.path.join(tmp_dir, "ilumia_installer.bat")
        app_dir = BASE_DIR
        
        batch_content = f'''@echo off
setlocal enabledelayedexpansion

REM Warte dass alte App sich schließt (max 30s)
set /a count=0
:wait_old_app
if !count! equ 30 goto :continue
tasklist /FI "IMAGENAME eq electron.exe" 2>nul | find /I "electron.exe" >nul
if errorlevel 1 (
    echo Old app closed
    goto :continue
)
timeout /t 1 /nobreak
set /a count=!count!+1
goto :wait_old_app

:continue
REM Starte Installer
start /wait "" "{installer}"
echo Installation complete

REM Warte bevor neue App startet
timeout /t 2 /nobreak

REM Starte neue App
cd /d "{app_dir}"
start "" npm start
'''
        
        with open(batch_file, "w") as f:
            f.write(batch_content)
        
        # Run batch file in background
        subprocess.Popen(
            batch_file,
            shell=True,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    except Exception as e:
        print(f"[bridge] Update error: {e}")
        traceback.print_exc()
        sys.stdout.flush()

def find_python() -> str:
    """Findet den richtigen Python-Interpreter, auch wenn bridge als .exe läuft."""
    # Wenn nicht frozen: sys.executable ist python.exe → direkt nutzbar
    if not getattr(sys, "frozen", False):
        return sys.executable

    # Wenn frozen (bridge.exe): sys.executable ist bridge.exe → nutzlos
    # Suche python.exe im PATH und üblichen Installationspfaden
    import shutil
    found = shutil.which("python") or shutil.which("python3")
    if found:
        return found

    # Fallback: übliche Windows Python-Pfade
    candidates = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        import glob
        candidates += glob.glob(os.path.join(local, "Programs", "Python", "Python3*", "python.exe"))
        candidates += glob.glob(os.path.join(local, "Programs", "Python", "Python*", "python.exe"))
    prog = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    candidates += [
        os.path.join(prog, "Python311", "python.exe"),
        os.path.join(prog, "Python310", "python.exe"),
        os.path.join(prog, "Python312", "python.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    return "python"  # letzter Fallback


def start_bot():
    global bot_process

    if bot_process and bot_process.poll() is None:
        print("[bridge] Killing old bot instance")
        bot_process.kill()

    bot_path = os.path.join(INTERNAL_DIR, "main_bot.py")
    print(f"[bridge] Bot path:   {bot_path}")
    print(f"[bridge] Bot exists: {os.path.exists(bot_path)}")
    sys.stdout.flush()

    if not os.path.exists(bot_path):
        print("[bridge] ERROR: main_bot.py not found!")
        sys.stdout.flush()
        return

    reset_bot_state()

    try:
        python_exe = find_python()
        print(f"[bridge] Python exe: {python_exe}")
        print(f"[bridge] Launching bot...")
        sys.stdout.flush()

        bot_process = subprocess.Popen(
            [python_exe, bot_path],
            cwd=INTERNAL_DIR,
            env={**os.environ, "BRIDGE_PORT": str(PORT)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        print(f"[bridge] Bot PID: {bot_process.pid}")
        sys.stdout.flush()

        def _stream():
            global bot_last_error
            try:
                for line in bot_process.stdout:
                    txt = line.decode(errors="replace").rstrip()
                    print(f"[bot] {txt}")
                    sys.stdout.flush()
            except Exception as e:
                print(f"[bridge] Stream error: {e}")
            print(f"[bot] exited code={bot_process.returncode}")
            sys.stdout.flush()

        def _stream_err():
            global bot_last_error
            lines = []
            try:
                for line in bot_process.stderr:
                    txt = line.decode(errors="replace").rstrip()
                    print(f"[bot:err] {txt}")
                    sys.stdout.flush()
                    lines.append(txt)
            except Exception:
                pass
            bot_last_error = "\n".join(lines[-20:])

        threading.Thread(target=_stream,     daemon=True, name="BotStream").start()
        threading.Thread(target=_stream_err, daemon=True, name="BotStreamErr").start()

    except Exception:
        print("[bridge] FAILED to start bot:")
        traceback.print_exc()
        sys.stdout.flush()

# ==========================================
# HTTP REQUEST HANDLER
# ==========================================
class BridgeHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

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

    def do_POST(self):
        body      = self._read_body()
        req_path  = self.path

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

        elif req_path == "/check-update":
            self._send(check_for_update())

        elif req_path == "/start-bot":
            key = body.get("key", "")
            print(f"[bridge] /start-bot received, key={key[:8]}...")
            sys.stdout.flush()
            if key == "__update__":
                url = body.get("url", "")
                ver = body.get("version", "")
                threading.Thread(target=do_update, args=(url, ver), daemon=True).start()
                self._send({"ok": True, "action": "update"})
            else:
                start_bot()
                self._send({"ok": True, "action": "bot_started"})

        elif req_path == "/item-found":
            global first_item_found
            first_item_found = True
            self._send({"ok": True})

        elif req_path == "/poll-status":
            self._send({"first_item_found": first_item_found})

        elif req_path == "/bot-error":
            bot_path = os.path.join(INTERNAL_DIR, "main_bot.py")
            self._send({
                "error": bot_last_error,
                "running": bot_process is not None and bot_process.poll() is None,
                "internal_dir": INTERNAL_DIR,
                "bot_path": bot_path,
                "bot_exists": os.path.exists(bot_path),
                "python_exe": find_python(),
            })

        else:
            self._send({"error": "unknown endpoint"}, 404)

# ==========================================
# ENTRY POINT
# ==========================================
if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), BridgeHandler)
    server.allow_reuse_address = True  # Ermöglicht Port-Reuse nach Neustart
    print(f"[bridge] Listening on 127.0.0.1:{PORT}")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[bridge] Shutting down.")
        if bot_process and bot_process.poll() is None:
            bot_process.kill()
