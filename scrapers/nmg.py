import re
import logging
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
BASE_URL = "https://nmgwonen.nl/koop/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "nl-NL,nl;q=0.9",
}


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


async def scrape_nmg() -> list[dict]:
    """
    NMG listing page is fully server-side rendered.
    Each listing card (article/div) contains:
      - <h2> or heading with street + city
      - € price
      - surface in m2
    Energy label not shown on listing page — skipped.
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(BASE_URL, headers=HEADERS)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    listings = []
    seen = set()

    # Each property is linked from the listing page
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # NMG property URLs: /woning/straat-stad/ or /koop/straat/
        if not re.search(r"/(woning|koop)/[^/]+/", href):
            continue
        # Skip filter/pagination links
        if any(x in href for x in ["?", "page", "filter", "#"]):
            continue
        url = href if href.startswith("http") else f"https://nmgwonen.nl{href}"
        if url in seen or url.rstrip("/") == BASE_URL.rstrip("/"):
            continue
        seen.add(url)

        texts = [t.strip() for t in a.stripped_strings if t.strip()]
        if not texts:
            continue

        # Heading is first substantial text
        title = texts[0] if texts else "onbekend"

        price_text = next((t for t in texts if "€" in t), "onbekend")
        price_raw = parse_price(price_text)

        surface_text = next((t for t in texts if re.search(r"\d+\s*m2", t, re.I)), "onbekend")
        surface_int = parse_surface(surface_text)
        price_per_m2 = calc_price_per_m2(price_raw, surface_int)

        listings.append({
            "source": "NMG",
            "title": title,
            "price_raw": price_raw,
            "price": price_text,
            "surface": surface_text,
            "energy": "zie woning",
            "price_per_m2": price_per_m2,
            "url": url,
        })

    log.info(f"NMG: scraped {len(listings)} listings")
    return listings
