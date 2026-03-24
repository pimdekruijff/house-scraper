import re
import logging
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)
BASE_URL = "https://stmakelaars.nl/wonen/aanbod"


def parse_price(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


async def scrape_stmakelaars() -> list[dict]:
    """
    ST Makelaars loads listings via JS. We wait for the page to settle,
    then dump the full page content and parse all property links.
    """
    listings = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ))
        await page.goto(BASE_URL, wait_until="networkidle", timeout=40000)

        # Wait a bit extra for JS to render
        await page.wait_for_timeout(3000)

        content = await page.content()
        await browser.close()

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, "html.parser")

    # ST Makelaars links to individual properties via /wonen/object/ or /aanbod/
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Property links contain /wonen/ followed by a slug (not just /wonen/aanbod)
        if not re.search(r"/wonen/[^/]+/[^/]+", href):
            continue
        url = href if href.startswith("http") else f"https://stmakelaars.nl{href}"
        if url in seen:
            continue
        seen.add(url)

        texts = [t.strip() for t in a.stripped_strings if t.strip()]
        if not texts:
            continue

        price_text = next((t for t in texts if "€" in t or "euro" in t.lower()), "onbekend")
        price_raw = parse_price(price_text)

        title = texts[0]

        location = next(
            (t for t in texts if re.match(r"\d{4}\s*[a-z]{2}", t, re.I)),
            title
        )

        listings.append({
            "source": "ST Makelaars",
            "title": f"{title}, {location}",
            "price_raw": price_raw,
            "price": price_text,
            "surface": "zie woning",
            "energy": "zie woning",
            "url": url,
        })

    log.info(f"ST Makelaars: scraped {len(listings)} listings")
    return listings
