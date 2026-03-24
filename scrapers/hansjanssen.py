import re
import logging
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)
BASE_URL = "https://www.hansjanssen.nl/wonen/"


def parse_price(text: str) -> int:
    """Extract integer price from strings like '€ 285.000 k.k.'"""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


async def scrape_hansjanssen() -> list[dict]:
    listings = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ))
        await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)

        # Wait for property cards to load
        await page.wait_for_selector("article, .property, .woning, .listing", timeout=15000)

        cards = await page.query_selector_all("article")
        for card in cards:
            try:
                # Title / address
                title_el = await card.query_selector("h2, h3, .title, .address")
                title = (await title_el.inner_text()).strip() if title_el else ""

                # Price
                price_el = await card.query_selector(".price, [class*='price'], [class*='prijs']")
                price_text = (await price_el.inner_text()).strip() if price_el else ""
                price_raw = parse_price(price_text)

                # Link
                link_el = await card.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else ""
                url = href if href.startswith("http") else f"https://www.hansjanssen.nl{href}"

                # Surface area
                surface_el = await card.query_selector("[class*='surface'], [class*='opper'], [class*='m2']")
                surface = (await surface_el.inner_text()).strip() if surface_el else "onbekend"

                # Energy label
                energy_el = await card.query_selector("[class*='energy'], [class*='label'], [class*='energie']")
                energy = (await energy_el.inner_text()).strip() if energy_el else "onbekend"

                if title and url:
                    listings.append({
                        "source": "Hans Janssen",
                        "title": title,
                        "price_raw": price_raw,
                        "price": price_text or "onbekend",
                        "surface": surface,
                        "energy": energy,
                        "url": url,
                    })
            except Exception as e:
                log.debug(f"Hans Janssen card parse error: {e}")

        await browser.close()
    return listings
