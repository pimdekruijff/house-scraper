import os
import httpx
import logging

log = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


async def send_telegram(listing: dict):
    price_per_m2 = listing.get("price_per_m2", "onbekend")

    text = (
        f"🏠 *Nieuwe woning — {listing['source']}*\n"
        f"\n"
        f"📍 *Locatie:* {listing['title']}\n"
        f"💶 *Prijs:* {listing['price']}\n"
        f"📐 *Oppervlakte:* {listing['surface']}\n"
        f"💰 *Prijs per m²:* {price_per_m2}\n"
        f"⚡ *Energielabel:* {listing['energy']}\n"
        f"\n"
        f"🔗 [Bekijk woning]({listing['url']})"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            log.error(f"Telegram error {resp.status_code}: {resp.text}")
        else:
            log.info(f"Telegram: sent listing '{listing['title']}'")
