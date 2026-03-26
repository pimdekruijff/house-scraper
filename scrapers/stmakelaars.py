import re
import logging
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
BASE_URL = "https://stmakelaars.nl/wonen/aanbod"


def parse_price(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def parse_surface(text: str) -> int:
    m = re.search(r"(\d+)", text.replace(".", ""))
    return int(m.group(1)) if m else 0


def calc_price_per_m2(price: int, surface: int) -> str:
    if price and surface:
        return f"€ {price // surface:,.0f}".replace(",", ".")
    return "onbekend"


async def scrape_stmakelaars() -> list[dict]:
    listings = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ))
        await page.goto(BASE_URL, wait_until="networkidle", timeout=40000)
        await page.wait_for_timeout(3000)
        content = await page.content()
        await browser.close()

    soup = BeautifulSoup(content, "html.parser")
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
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
        location = next((t for t in texts if re.match(r"\d{4}\s*[a-z]{2}", t, re.I)), title)
        surface_text = next((t for t in texts if "m²" in t or "m2" in t.lower()), "onbekend")
        surface_int = parse_surface(surface_text)
        price_per_m2 = calc_price_per_m2(price_raw, surface_int)

        listings.append({
            "source": "ST Makelaars",
            "title": f"{title}, {location}",
            "price_raw": price_raw,
            "price": price_text,
            "surface": surface_text,
            "energy": "zie woning",
            "price_per_m2": price_per_m2,
            "url": url,
        })

    log.info(f"ST Makelaars: scraped {len(listings)} listings")
    return listings
