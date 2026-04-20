import os
import sys
import re
import secrets
import string

from supabase import create_client, Client

# ==========================================
# HARDCODED CONFIG
# ==========================================
SUPABASE_URL = "https://ikshnlooivixiembblqw.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlrc2hubG9vaXZpeGllbWJibHF3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTgzNDM5MiwiZXhwIjoyMDkxNDEwMzkyfQ.BHFwopTwmAoboIn-QliIOpnw4HVQLd_tW-gBD0vCh6w"  # <- hier deinen service_role key eintragen

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# KEY GENERATOR
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

def insert_license(key: str, duration_days: int) -> bool:
    try:
        supabase.table("licenses").insert({
            "key": key,
            "duration_days": duration_days,
            "activated_at": None,
            "hwid_locked": None,
        }).execute()
        return True
    except Exception as e:
        print(f"\n[-] Datenbankfehler: {e}")
        return False

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

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
                # Automatisch in Zwischenablage kopieren
                if os.name == 'nt':
                    try:
                        import subprocess
                        subprocess.run('clip', text=True, input=key, check=True)
                        print("[+] Key wurde automatisch kopiert! (STRG+V zum Einfuegen)")
                    except Exception:
                        pass
            else:
                print("[-] Fehler beim Speichern!")

            input("\n[Enter] druecken um weiterzumachen...")

if __name__ == "__main__":
    main()