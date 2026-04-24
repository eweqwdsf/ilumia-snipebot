# ILUMIA SnipeBot Setup Anleitung

## 🚀 Vorbereitung für Kunden

### Schritt 1: Discord Bot erstellen
1. Gehe zu [Discord Developer Portal](https://discord.com/developers/applications)
2. Klicke "New Application" → Gib einen Namen ein (z.B. "ILUMIA Bot")
3. Gehe zum Tab "Bot" → Klicke "Add Bot"
4. Unter "TOKEN" → Klicke "Copy" (das ist dein DISCORD_BOT_TOKEN)
5. Aktiviere diese Intents:
   - Message Content Intent
   - Privileged Gateway Intents → Schalte an

### Schritt 2: Discord Server Channel ID
1. Öffne Discord und aktiviere "Developer Mode" (Settings → Advanced)
2. Rechtsklick auf den Channel, wo der Bot posten soll
3. Klicke "Copy Channel ID" (das ist DISCORD_CHANNEL_ID)

### Schritt 3: Bot zu Server hinzufügen
1. Im Developer Portal → Gehe zu "OAuth2 → URL Generator"
2. Scopes wählen: `bot`
3. Permissions wählen:
   - Send Messages
   - Manage Messages
   - Embed Links
4. Kopiere die generierte URL und öffne sie
5. Wähle deinen Server aus → Bot wird hinzugefügt

### Schritt 4: Konfigurationsdatei ausfüllen
1. Öffne die `.env` Datei im Python-Ordner
2. Fülle folgende Werte aus:
   ```
   DISCORD_BOT_TOKEN=dein_token_hier
   DISCORD_CHANNEL_ID=deine_channel_id_hier
   ADMIN_USER_IDS=deine_user_id_hier,weitere_admin_ids
   ```
3. Speichern!

### Schritt 5: License Key kaufen
- Kontaktiere den Admin um einen License Key zu generieren
- Der Key wird via Discord `/genlicense 30d` erstellt

### Schritt 6: App starten
```bash
npm start
```

1. Gib den License Key ein
2. Der Bot startet automatisch
3. Überprüfe den Discord Channel - der Bot sollte Items posten!

---

## 🔒 Sicherheit
- **Niemals** die `.env` Datei teilen!
- **Niemals** deinen Discord Bot Token weitergeben!
- `.env` ist in `.gitignore` - wird nicht auf GitHub hochgeladen

---

## 📋 Checkliste für Admin
- [ ] Supabase Project vorbereitet
- [ ] Discord Bot Token und Channel ID getestet
- [ ] License Keys im System
- [ ] `.env` Template verteilt
- [ ] Installer gebaut und auf GitHub hochgeladen
- [ ] Kundenbetreuung bereit
