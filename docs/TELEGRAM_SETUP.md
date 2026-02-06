# Nastavení Telegram bota

## 1. Vytvoření bota

1. Otevři v Telegramu `@BotFather`
2. Pošli příkaz `/newbot`
3. Zadej **název** bota (zobrazuje se v chatu) a **username** (unikátní, musí končit na `bot`)
4. BotFather ti vrátí **token** — ulož si ho, budeš ho potřebovat do `.env`

## 2. Zjištění svého user ID

Aide potřebuje vědět, kdo s ním smí komunikovat.

1. Napiš v Telegramu botovi `@userinfobot`
2. Vrátí ti tvoje **user ID** (číslo) — zapiš si ho

> Pokud má Aide odpovídat více lidem, zjisti ID každého z nich stejným způsobem.

## 3. Zjištění chat ID pro notifikace

Chat ID určuje, kam Aide posílá připomínky, heartbeat a další automatické zprávy.

1. Pošli svému novému botovi **libovolnou zprávu**
2. Zavolej Telegram API:
   ```
   curl "https://api.telegram.org/bot<TVŮJ_TOKEN>/getUpdates"
   ```
3. V odpovědi najdi hodnotu `message.chat.id` — to je tvoje **chat ID**

> Pro soukromou konverzaci je chat ID stejné jako user ID. Pro skupinu bude jiné.

## 4. Konfigurace `.env`

Otevři soubor `.env` ve svém workspace a vyplň:

```
TELEGRAM_TOKEN=123456:ABCDEFghijklmnop...
ALLOWED_USERS=123456789
AIDE_DEFAULT_CHAT_ID=123456789
AIDE_TELEGRAM_ENABLED=1
```

| Proměnná | Co to je |
|----------|----------|
| `TELEGRAM_TOKEN` | Token od BotFathera |
| `ALLOWED_USERS` | Povolená user ID, oddělená čárkou |
| `AIDE_DEFAULT_CHAT_ID` | Kam chodit notifikace (DM nebo skupina) |
| `AIDE_TELEGRAM_ENABLED` | `1` = zapnuto, `0` = vypnuto |

### Volitelné proměnné

| Proměnná | Výchozí | Popis |
|----------|---------|-------|
| `AIDE_TELEGRAM_PARSE_MODE` | `plain` | `markdown_v2` pro formátování zpráv |
| `AIDE_TELEGRAM_ESCAPE` | `none` | `aggressive` pro escapování speciálních znaků |
| `AIDE_TELEGRAM_PROGRESS` | `1` | Ukazovat průběh (jaký tool agent zrovna používá) |
| `AIDE_TELEGRAM_MAX_FILE_MB` | `10` | Max velikost příloh v MB |

## 5. Spuštění

```bash
./scripts/run.sh /cesta/k/workspace
```

## Řešení problémů

- **Bot neodpovídá:** Zkontroluj `TELEGRAM_TOKEN` a `ALLOWED_USERS` v `.env`
- **Notifikace nechodí:** Ověř `AIDE_DEFAULT_CHAT_ID`
- **Logy:** `data/logs/bot.log` ve workspace
