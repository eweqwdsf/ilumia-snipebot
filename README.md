# ILUMIA SnipeBot — Electron + Python

## Projektstruktur

```
ilumia-electron/
├── package.json          ← Electron-Konfiguration
├── src/
│   ├── main.js           ← Electron Hauptprozess (startet Python, verwaltet Fenster)
│   ├── preload.js        ← Sichere Brücke zwischen UI und Hauptprozess
│   ├── index.html        ← Komplettes UI (HTML + CSS: Sterne, Meteore, Sphere, Screens)
│   └── renderer.js       ← UI-Logik + Canvas-Animationen
└── python/
    ├── bridge.py         ← Python HTTP-Server (127.0.0.1:57421) — alle Backend-Funktionen
    ├── main_bot.py       ← Discord Bot (unverändert)
    ├── vinted_fetcher.py ← Vinted API (unverändert)
    ├── vinted_filter.py  ← Filter-Logik (unverändert)
    └── admin_keygen.py   ← Admin Key-Generator (unverändert)
```

## Wie es funktioniert

```
[Electron UI]  ←→  [main.js IPC]  ←→  [bridge.py HTTP :57421]  ←→  [Supabase / Vinted / Discord]
```

1. Electron startet → `main.js` spawnt `bridge.py` als Kindprozess
2. `main.js` wartet bis bridge erreichbar ist (`/ping`)
3. UI-Klicks → `renderer.js` → `window.api.xxx()` → `preload.js` → `main.js` IPC → HTTP POST an bridge
4. `bridge.py` macht die eigentliche Arbeit (Supabase, HWID, Bot starten) und antwortet JSON
5. Antwort geht zurück an UI → Screen-Wechsel

## Setup (Entwicklung)

### Voraussetzungen
- Node.js 18+
- Python 3.11+
- pip-Pakete: `supabase`, `discord.py`, `aiohttp`, `playwright`

### Schritte

```bash
# 1. Node-Abhängigkeiten installieren
cd ilumia-electron
npm install

# 2. Python-Abhängigkeiten installieren
pip install supabase discord.py aiohttp playwright
playwright install chromium

# 3. Starten
npm start
```

## Build (Windows .exe)

### Python Bridge als .exe packen (PyInstaller)

```bash
cd python
pip install pyinstaller
pyinstaller --onefile --name bridge bridge.py
# → python/dist/bridge.exe
```

### Electron App bauen

```bash
# bridge.exe muss in python/dist/ liegen
npm run build
# → dist/ILUMIA Setup 1.3.0.exe
```

> **Hinweis:** In `package.json` → `extraResources` wird `python/` ins App-Paket kopiert.
> Passe den Pfad zu `bridge.exe` in `main.js → getPythonPath()` ggf. an.

## API-Endpunkte (bridge.py)

| Endpoint          | Body                     | Antwort                              |
|-------------------|--------------------------|--------------------------------------|
| `POST /ping`      | —                        | `{ ok: true }`                       |
| `POST /hwid`      | —                        | `{ hwid: "ABC123..." }`              |
| `POST /check-license` | `{ key: "..." }`    | `{ valid, info, key }`               |
| `POST /check-update`  | —                   | `{ has_update, version, url? }`      |
| `POST /start-bot` | `{ key: "..." }`         | `{ ok, action }`                     |

## Admin Key-Generator

`admin_keygen.py` läuft weiterhin separat als CLI-Tool:

```bash
cd python
python admin_keygen.py
```

Oder über den Discord-Slash-Command `/genlicense` im Bot (unverändert).
