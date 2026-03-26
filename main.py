import asyncio
import logging
from scrapers.hansjanssen import scrape_hansjanssen
from scrapers.stmakelaars import scrape_stmakelaars
from scrapers.kolmeijer import scrape_kolmeijer
from scrapers.hestia import scrape_hestia
from scrapers.verbeek import scrape_verbeek
from scrapers.driessen import scrape_driessen
from scrapers.inbeeld import scrape_inbeeld
from scrapers.pulles import scrape_pulles
from notifier import send_telegram
from storage import load_seen, save_seen

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PRICE_MIN = 200_000
PRICE_MAX = 350_000
LOCATION_KEYWORDS = ["nijmegen", "nymegen"]


def is_in_nijmegen(listing: dict) -> bool:
    title = listing.get("title", "").lower()
    url = listing.get("url", "").lower()
    return any(kw in title or kw in url for kw in LOCATION_KEYWORDS)


async def run():
    log.info("Starting house scrape run...")
    seen = load_seen()
    new_listings = []

    scrapers = [
        scrape_hansjanssen,
        scrape_stmakelaars,
        scrape_kolmeijer,
        scrape_hestia,
        scrape_verbeek,
        scrape_driessen,
        scrape_inbeeld,
        scrape_pulles,
    ]

    for scraper in scrapers:
        try:
            listings = await scraper()
            log.info(f"{scraper.__name__}: found {len(listings)} listings")
            for listing in listings:
                price = listing.get("price_raw", 0)
                in_range = PRICE_MIN <= price <= PRICE_MAX
                in_nijmegen = is_in_nijmegen(listing)
                is_new = listing["url"] not in seen

                if in_range and in_nijmegen and is_new:
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
        log.info("No new listings in price range in Nijmegen.")

if __name__ == "__main__":
    asyncio.run(run())
