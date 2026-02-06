# Nastavení Slack bota (Socket Mode)

## 1. Vytvoření Slack aplikace

1. Otevři [Slack API Apps](https://api.slack.com/apps)
2. Klikni **Create New App** → **From scratch**
3. Zadej název (např. "Aide") a vyber workspace

## 2. Zapnutí Socket Mode

Socket Mode = bot komunikuje přes WebSocket, nepotřebuješ veřejnou URL.

1. V levém menu jdi do **Socket Mode**
2. Zapni **Enable Socket Mode**
3. Vytvoř App-Level Token — pojmenuj ho (např. "socket") a přidej scope `connections:write`
4. Zkopíruj token (začíná na `xapp-...`) — budeš ho potřebovat do `.env`

## 3. Nastavení oprávnění (OAuth Scopes)

1. V levém menu jdi do **OAuth & Permissions**
2. V sekci **Bot Token Scopes** přidej:

| Scope | K čemu |
|-------|--------|
| `app_mentions:read` | Bot vidí když ho někdo @zmíní |
| `chat:write` | Bot může psát zprávy |
| `im:history` | Bot čte historii DM |
| `im:write` | Bot může psát DM |
| `files:read` | Bot vidí nahrané soubory (přílohy) |

### Volitelné scopes pro auto-thread

Pokud chceš aby bot automaticky odpovídal ve vláknech bez @zmínky:

| Scope | K čemu |
|-------|--------|
| `channels:history` | Čtení historie veřejných kanálů |
| `groups:history` | Čtení historie privátních kanálů |

## 4. Nastavení Event Subscriptions

1. V levém menu jdi do **Event Subscriptions**
2. Zapni **Enable Events**
3. V sekci **Subscribe to bot events** přidej:

| Event | K čemu |
|-------|--------|
| `app_mention` | Reakce na @zmínku |
| `message.im` | Reakce na DM |

### Volitelné eventy pro auto-thread

| Event | K čemu |
|-------|--------|
| `message.channels` | Zprávy ve veřejných kanálech |
| `message.groups` | Zprávy v privátních kanálech |

> Slack UI může požadovat Request URL — při Socket Mode to ignoruj, eventy jdou přes WebSocket.

## 5. Instalace do workspace

1. Jdi zpět do **OAuth & Permissions**
2. Klikni **Install to Workspace** a potvrď
3. Zkopíruj **Bot User OAuth Token** (začíná na `xoxb-...`)

## 6. Přidání bota do kanálu

V kanálu kde chceš bota používat napiš:
```
/invite @jmeno-bota
```

## 7. Zjištění svého Slack user ID

1. Klikni na svůj profil (vpravo nahoře)
2. Zvol **Profil**
3. Klikni na **tři tečky** (⋮) a vyber **Copy member ID**

## 8. Konfigurace `.env`

Otevři soubor `.env` ve svém workspace a vyplň:

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
AIDE_SLACK_ENABLED=1
AIDE_SLACK_ALLOWED_USERS=UXXXXXXX
AIDE_SLACK_DEFAULT_TARGET=UXXXXXXX
AIDE_NOTIFY_PROVIDER=slack
```

| Proměnná | Co to je |
|----------|----------|
| `SLACK_BOT_TOKEN` | Bot token z kroku 5 (`xoxb-...`) |
| `SLACK_APP_TOKEN` | App-Level token z kroku 2 (`xapp-...`) |
| `AIDE_SLACK_ENABLED` | `1` = zapnuto |
| `AIDE_SLACK_ALLOWED_USERS` | Povolená user ID, oddělená čárkou |
| `AIDE_SLACK_DEFAULT_TARGET` | Kam chodit notifikace — `U...` pro DM, `C...` pro kanál |
| `AIDE_NOTIFY_PROVIDER` | `slack` = notifikace přes Slack (jinak jdou přes Telegram) |

### Volitelné proměnné

| Proměnná | Výchozí | Popis |
|----------|---------|-------|
| `AIDE_SLACK_DEFAULT_TARGET_TYPE` | `auto` | `dm` nebo `channel` pro vynucení cíle |
| `AIDE_SLACK_AUTO_THREAD` | `0` | `1` = bot odpovídá ve vláknech bez @zmínky |
| `AIDE_SLACK_PROGRESS` | `1` | Ukazovat průběh (jaký tool agent používá) |
| `AIDE_SLACK_MAX_FILE_MB` | `10` | Max velikost příloh v MB |

## 9. Spuštění

```bash
./scripts/run.sh /cesta/k/workspace
```

## Řešení problémů

- **Bot neodpovídá na @zmínku:** Zkontroluj že je bot přidaný v kanálu (`/invite`)
- **DM nefungují:** Po restartu pošli @zmínku do kanálu — Socket Mode bug, DM se aktivují až po první channel interakci
- **Chybná oprávnění:** Po změně scopes je potřeba app znovu nainstalovat do workspace (krok 5)
- **Logy:** `data/logs/slack.log` ve workspace
