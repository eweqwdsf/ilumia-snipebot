"""
admin_keygen.py — ILUMIA+ Admin Key Generator
----------------------------------------------
SICHERHEIT:
  - Credentials werden NUR aus .env gelesen, NIEMALS hardcoded.
  - Dieses Tool wird NIEMALS mit dem Endnutzer-Bundle ausgeliefert.
  - Nur der service_role Key hat INSERT-Rechte auf die licenses-Tabelle.
  - .env muss SUPABASE_URL + SUPABASE_KEY (service_role) enthalten.
"""
import os
import sys
import re
import secrets
import string

from dotenv import load_dotenv
from supabase import create_client, Client

# ── Credentials aus .env laden ────────────────────────────────
# Suche .env im selben Verzeichnis wie dieses Script
_here = os.path.dirname(os.path.abspath(__file__))
# .env.admin enthält den service_role Key — niemals in die .exe packen!
_env_path = os.path.join(_here, ".env.admin")
if not os.path.exists(_env_path):
    print(f"[-] FEHLER: .env.admin nicht gefunden unter: {_env_path}")
    print("    Erstelle eine .env.admin mit SUPABASE_URL und SUPABASE_KEY (service_role).")
    sys.exit(1)

load_dotenv(_env_path)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[-] FEHLER: SUPABASE_URL oder SUPABASE_KEY fehlen in .env")
    sys.exit(1)

# Sicherheitswarnung: anon-key hat keine INSERT-Rechte → früh abfangen
if '"role":"anon"' in SUPABASE_KEY or (
    # JWT-Payload dekodieren ohne Bibliothek
    len(SUPABASE_KEY.split(".")) == 3 and
    __import__("base64").b64decode(
        SUPABASE_KEY.split(".")[1] + "=="
    ).decode(errors="ignore").find('"anon"') != -1
):
    print("[-] FEHLER: SUPABASE_KEY ist ein anon-Key.")
    print("    Das admin_keygen benötigt den service_role Key in der .env.")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Key-Generator ─────────────────────────────────────────────
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


def insert_license(key: str, duration_days: int) -> bool:
    try:
        supabase.table("licenses").insert({
            "key":          key,
            "duration_days": duration_days,
            "activated_at": None,
            "hwid_locked":  None,
        }).execute()
        return True
    except Exception as e:
        print(f"\n[-] Datenbankfehler: {e}")
        return False


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def main():
    while True:
        clear_screen()
        print("====================================")
        print("    ILUMIA+ ADMIN KEY GENERATOR     ")
        print("====================================")
        print()
        print("[1] Key generieren")
        print("[0] Beenden")
        print()
        print("====================================")

        choice = input("\nWaehle eine Option: ").strip()

        if choice == "0":
            break

        elif choice == "1":
            dauer = input("\nDauer eingeben (z.B. 7d, 30d, 365d): ").strip()
            duration_days = parse_duration(dauer)

            if duration_days is None:
                print(f"\n[-] Ungueltige Dauer '{dauer}'. Beispiele: 1d, 7d, 30d, 365d")
                input("\n[Enter] druecken...")
                continue

            key = generate_license_key(dauer)
            print(f"\n[+] Generierter Key:")
            print(f"\n    {key}\n")

            print("[+] Speichere in Datenbank...")
            success = insert_license(key, duration_days)

            if success:
                print(f"[+] Erfolgreich gespeichert! ({duration_days} Tage)")
                if os.name == "nt":
                    try:
                        import subprocess
                        subprocess.run("clip", text=True, input=key, check=True)
                        print("[+] Key wurde automatisch kopiert! (STRG+V zum Einfuegen)")
                    except Exception:
                        pass
            else:
                print("[-] Fehler beim Speichern!")

            input("\n[Enter] druecken um weiterzumachen...")


if __name__ == "__main__":
    main()