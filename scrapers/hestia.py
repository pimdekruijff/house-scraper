import re
import logging
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
BASE_URL = "https://hestia.nl/aanbod/"
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


async def scrape_hestia() -> list[dict]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(BASE_URL, headers=HEADERS)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    listings = []

    for a in soup.find_all("a", href=re.compile(r"/object/")):
        try:
            href = a["href"]
            url = href if href.startswith("http") else f"https://hestia.nl{href}"

            h5 = a.find("h5")
            if not h5:
                continue
            street = h5.get_text(strip=True)

            texts = [t.strip() for t in a.stripped_strings if t.strip()]

            status = next((t for t in texts if "verkocht" in t.lower()), "")
            if status:
                continue

            city = next((t for t in texts if t.isupper() and len(t) > 2), "")
            surface_text = next((t for t in texts if "m²" in t or "m2" in t.lower()), "onbekend")
            surface_int = parse_surface(surface_text)

            price_text = next((t for t in texts if re.search(r"\d+[\.\d]*,-", t)), "onbekend")
            price_raw = parse_price(price_text)
            price_per_m2 = calc_price_per_m2(price_raw, surface_int)

            title = f"{street}, {city.title()}" if city else street

            listings.append({
                "source": "Hestia",
                "title": title,
                "price_raw": price_raw,
                "price": price_text,
                "surface": surface_text,
                "energy": "zie woning",
                "price_per_m2": price_per_m2,
                "url": url,
            })
        except Exception as e:
            log.debug(f"Hestia parse error: {e}")

    log.info(f"Hestia: scraped {len(listings)} listings")
    return listings
