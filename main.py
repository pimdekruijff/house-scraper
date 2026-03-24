import asyncio
import logging
from scrapers.hansjanssen import scrape_hansjanssen
from scrapers.stmakelaars import scrape_stmakelaars
from scrapers.kolmeijer import scrape_kolmeijer
from notifier import send_telegram
from storage import load_seen, save_seen

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PRICE_MIN = 200_000
PRICE_MAX = 350_000

async def run():
    log.info("Starting house scrape run...")
    seen = load_seen()
    new_listings = []

    scrapers = [
        scrape_hansjanssen,
        scrape_stmakelaars,
        scrape_kolmeijer,
    ]

    for scraper in scrapers:
        try:
            listings = await scraper()
            log.info(f"{scraper.__name__}: found {len(listings)} listings")
            for listing in listings:
                price = listing.get("price_raw", 0)
                if PRICE_MIN <= price <= PRICE_MAX:
                    if listing["url"] not in seen:
                        new_listings.append(listing)
                        seen.add(listing["url"])
        except Exception as e:
            log.error(f"{scraper.__name__} failed: {e}")

    if new_listings:
        log.info(f"Sending {len(new_listings)} new listings via Telegram")
        for listing in new_listings:
            await send_telegram(listing)
        save_seen(seen)
    else:
        log.info("No new listings found in price range.")

if __name__ == "__main__":
    asyncio.run(run())
