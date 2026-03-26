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
from scrapers.homan import scrape_homan
from scrapers.beaufort import scrape_beaufort
from scrapers.level2 import scrape_level2
from scrapers.hermsen import scrape_hermsen
from scrapers.nmg import scrape_nmg
from scrapers.robdisbergen import scrape_robdisbergen
from scrapers.disveld import scrape_disveld
from scrapers.rotsvast import scrape_rotsvast
from scrapers.ooststede import scrape_ooststede
from notifier import send_telegram
from storage import load_seen, save_seen

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PRICE_MIN = 200_000
PRICE_MAX = 350_000
LOCATION_KEYWORDS = ["nijmegen", "nymegen"]

# Scrapers die Playwright gebruiken (browser overhead) — apart groeperen
PLAYWRIGHT_SCRAPERS = [
    scrape_kolmeijer,
    scrape_stmakelaars,
    scrape_verbeek,
    scrape_beaufort,
    scrape_level2,
    scrape_robdisbergen,
    scrape_disveld,
    scrape_rotsvast,
    scrape_ooststede,
]

# Scrapers die alleen httpx gebruiken (lichtgewicht, volledig parallel)
HTTPX_SCRAPERS = [
    scrape_hansjanssen,
    scrape_hestia,
    scrape_driessen,
    scrape_inbeeld,
    scrape_pulles,
    scrape_homan,
    scrape_hermsen,
    scrape_nmg,
]


def is_in_nijmegen(listing: dict) -> bool:
    title = listing.get("title", "").lower()
    url = listing.get("url", "").lower()
    return any(kw in title or kw in url for kw in LOCATION_KEYWORDS)


async def run_scraper(scraper) -> list[dict]:
    """Run a single scraper, catch errors gracefully."""
    try:
        results = await scraper()
        log.info(f"{scraper.__name__}: found {len(results)} listings")
        return results
    except Exception as e:
        log.error(f"{scraper.__name__} failed: {e}")
        return []


async def run():
    log.info("Starting house scrape run...")
    seen = load_seen()

    # Run httpx scrapers fully in parallel
    # Run Playwright scrapers with max 3 concurrent (each launches Chromium)
    playwright_semaphore = asyncio.Semaphore(3)

    async def run_playwright(scraper):
        async with playwright_semaphore:
            return await run_scraper(scraper)

    httpx_tasks = [run_scraper(s) for s in HTTPX_SCRAPERS]
    playwright_tasks = [run_playwright(s) for s in PLAYWRIGHT_SCRAPERS]

    all_results = await asyncio.gather(*httpx_tasks, *playwright_tasks)

    # Filter and collect new listings
    new_listings = []
    for listings in all_results:
        for listing in listings:
            price = listing.get("price_raw", 0)
            if (PRICE_MIN <= price <= PRICE_MAX
                    and is_in_nijmegen(listing)
                    and listing["url"] not in seen):
                new_listings.append(listing)
                seen.add(listing["url"])

    if new_listings:
        log.info(f"Sending {len(new_listings)} new listings via Telegram")
        for listing in new_listings:
            await send_telegram(listing)
        save_seen(seen)
    else:
        log.info("No new listings in price range in Nijmegen.")

if __name__ == "__main__":
    asyncio.run(run())
