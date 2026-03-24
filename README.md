# House Scraper — Nijmegen

Scrapes woningaanbod van Hans Janssen, ST Makelaars en Kolmeijer.
Stuurt een Telegram bericht bij nieuwe woningen in het prijsbereik €200.000–€350.000.

## Lokaal draaien

```bash
pip install -r requirements.txt
playwright install chromium

export TELEGRAM_TOKEN="jouw_bot_token"
export TELEGRAM_CHAT_ID="jouw_chat_id"

python main.py
```

## Telegram bot instellen

1. Open Telegram, zoek [@BotFather](https://t.me/BotFather)
2. Stuur `/newbot` en volg de stappen → je krijgt een **token**
3. Stuur een bericht naar je nieuwe bot
4. Haal je **chat_id** op via:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   Zoek naar `"chat":{"id": ...}` in de response

## Railway deployment

1. Push deze repo naar GitHub
2. Maak een nieuw project aan op [railway.app](https://railway.app)
3. Koppel je GitHub repo
4. Ga naar **Variables** en voeg toe:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. Ga naar **Settings → Cron Schedule** en stel in: `0 */2 * * *` (elke 2 uur)

## Prijsbereik aanpassen

In `main.py`:
```python
PRICE_MIN = 200_000
PRICE_MAX = 350_000
```

## Nieuwe makelaar toevoegen

1. Maak `scrapers/nieuwemakelaar.py` aan (kopieer een bestaande als template)
2. Importeer en voeg toe in `main.py`:
   ```python
   from scrapers.nieuwemakelaar import scrape_nieuwemakelaar
   scrapers = [..., scrape_nieuwemakelaar]
   ```

## Notitie over scraping

De selectors in de scrapers zijn gebaseerd op gangbare HTML-patronen. 
Als een site zijn layout wijzigt, moet je mogelijk de selectors in de 
betreffende scraper aanpassen. Controleer met de browser DevTools welke
CSS classes er gebruikt worden voor prijzen, titels etc.
