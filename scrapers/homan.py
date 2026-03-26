import re
import logging
import asyncio
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
BASE_URL = "https://www.homanmakelaardij.nl/woningen/"
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


async def fetch_detail(client: httpx.AsyncClient, url: str) -> dict:
    """
    Homan detail page:
    - Price in <h2>Koopprijs: € 375.000,- k.k.</h2>
    - Surface + energy in description text:
        "Woonoppervlak 100 m2"
        "Energielabel B"
    """
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        price_text = "onbekend"
        surface_text = "onbekend"
        surface_int = 0
        energy = "onbekend"

        # Price: <h2>Koopprijs: € 375.000,- k.k.</h2>
        for h2 in soup.find_all("h2"):
            t = h2.get_text(strip=True)
            if "koopprijs" in t.lower() and "€" in t:
                price_text = re.sub(r"koopprijs\s*:?\s*", "", t, flags=re.I).strip()
                break

        # Surface + energy: scan all text nodes for known patterns
        full_text = soup.get_text(" ", strip=True)

        m = re.search(r"[Ww]oonoppervlak\w*\s+(\d+)\s*m", full_text)
        if m:
            surface_int = int(m.group(1))
            surface_text = f"{surface_int} m²"

        m = re.search(r"[Ee]nergielabel\s+([A-G]\+{0,4})", full_text)
        if m:
            energy = m.group(1)

        price_raw = parse_price(price_text)
        price_per_m2 = calc_price_per_m2(price_raw, surface_int)

        return {
            "price_text": price_text,
            "price_raw": price_raw,
            "surface": surface_text,
            "energy": energy,
            "price_per_m2": price_per_m2,
        }
    except Exception as e:
        log.debug(f"Homan detail fetch failed for {url}: {e}")
        return {"price_text": "onbekend", "price_raw": 0, "surface": "onbekend",
                "energy": "onbekend", "price_per_m2": "onbekend"}


async def scrape_homan() -> list[dict]:
    """
    Listing page has /woning/stad/straat-nr/ links.
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(BASE_URL, headers=HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen = set()
        items = []
        for a in soup.find_all("a", href=re.compile(r"/woning/")):
            href = a["href"]
            url = href if href.startswith("http") else f"https://www.homanmakelaardij.nl{href}"
            if url in seen:
                continue
            seen.add(url)

            # /woning/nijmegen/spijkerhofplein-43/ -> Spijkerhofplein 43, Nijmegen
            parts = url.rstrip("/").split("/")
            city = parts[-2].title() if len(parts) >= 2 else ""
            street = parts[-1].replace("-", " ").title() if parts else ""
            address = f"{street}, {city}" if city else street

            items.append({"url": url, "address": address})

        log.info(f"Homan: found {len(items)} property URLs, fetching details...")

        semaphore = asyncio.Semaphore(5)

        async def fetch_with_semaphore(item):
            async with semaphore:
                detail = await fetch_detail(client, item["url"])
                return {**item, **detail}

        results = await asyncio.gather(*[fetch_with_semaphore(item) for item in items])

    listings = []
    for r in results:
        if r["price_raw"] == 0:
            continue
        listings.append({
            "source": "Homan",
            "title": r["address"],
            "price_raw": r["price_raw"],
            "price": r["price_text"],
            "surface": r["surface"],
            "energy": r["energy"],
            "price_per_m2": r["price_per_m2"],
            "url": r["url"],
        })

    log.info(f"Homan: scraped {len(listings)} listings")
    return listings
