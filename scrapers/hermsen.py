import re
import logging
import asyncio
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
BASE_URL = "https://hermsenmakelaarsnijmegen.nl/woningaanbod/"
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
    Hermsen detail page has clean structured sections:
    - Price: standalone € amount near title
    - "In het kort" section: Woonoppervlakte, Energie
    - "Kenmerken" section: Woonruimte, Perceeloppervlakte
    """
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Energy: in "In het kort" section as "Energie: D"
        energy = "onbekend"
        surface_text = "onbekend"
        surface_int = 0

        full_text = soup.get_text(" ")

        # Surface from "Woonruimte 121 m²" in Kenmerken
        m = re.search(r"Woonruimte\s+([\d]+)\s*m", full_text)
        if m:
            surface_int = int(m.group(1))
            surface_text = f"{surface_int} m²"

        # Fallback: "Woonoppervlakte Xm²" from "In het kort"
        if surface_text == "onbekend":
            m = re.search(r"Woonoppervlakte\s+([\d]+)\s*m", full_text)
            if m:
                surface_int = int(m.group(1))
                surface_text = f"{surface_int} m²"

        # Energy: "Energie D" or "Energielabel D"
        m = re.search(r"Energ(?:ie|ielabel)\s+([A-G]\+{0,4})", full_text)
        if m:
            energy = m.group(1)

        return {"surface": surface_text, "surface_int": surface_int, "energy": energy}
    except Exception as e:
        log.debug(f"Hermsen detail fetch failed for {url}: {e}")
        return {"surface": "onbekend", "surface_int": 0, "energy": "onbekend"}


async def scrape_hermsen() -> list[dict]:
    """
    Listing page is server-side rendered with price + surface already visible.
    Detail page fetched for energy label.
    URL pattern: /woningaanbod/koop/stad/straat-nr
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(BASE_URL, headers=HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        items = []
        seen = set()

        # Each listing card has address, price, surface visible
        for card in soup.select("a[href*='/woningaanbod/koop/']"):
            href = card.get("href", "")
            url = href if href.startswith("http") else f"https://hermsenmakelaarsnijmegen.nl{href}"
            if url in seen or url.rstrip("/") == BASE_URL.rstrip("/"):
                continue
            seen.add(url)

            texts = [t.strip() for t in card.stripped_strings if t.strip()]

            price_text = next((t for t in texts if "€" in t), "onbekend")
            price_raw = parse_price(price_text)

            surface_text = next((t for t in texts if "m2" in t.lower() or "woonoppervlakte" in t.lower()), "onbekend")
            surface_int = parse_surface(surface_text)

            # Address: first meaningful text
            address = next((t for t in texts if re.search(r"\d", t) and "€" not in t and "m2" not in t.lower()), "")
            # City from URL: /woningaanbod/koop/nijmegen/straat-nr
            parts = url.rstrip("/").split("/")
            try:
                city = parts[parts.index("koop") + 1].title()
            except (ValueError, IndexError):
                city = ""
            title = f"{address}, {city}" if city and city.lower() not in address.lower() else address

            items.append({
                "url": url,
                "title": title,
                "price_raw": price_raw,
                "price": price_text,
                "surface": surface_text,
                "surface_int": surface_int,
            })

        # Fetch energy labels concurrently
        semaphore = asyncio.Semaphore(5)

        async def fetch_with_semaphore(item):
            async with semaphore:
                detail = await fetch_detail(client, item["url"])
                surface_int = item["surface_int"] or detail["surface_int"]
                surface = item["surface"] if item["surface"] != "onbekend" else detail["surface"]
                price_per_m2 = calc_price_per_m2(item["price_raw"], surface_int)
                return {**item, "surface": surface, "energy": detail["energy"], "price_per_m2": price_per_m2}

        results = await asyncio.gather(*[fetch_with_semaphore(i) for i in items])

    listings = []
    for r in results:
        if r["price_raw"] == 0:
            continue
        listings.append({
            "source": "Hermsen",
            "title": r["title"],
            "price_raw": r["price_raw"],
            "price": r["price"],
            "surface": r["surface"],
            "energy": r["energy"],
            "price_per_m2": r["price_per_m2"],
            "url": r["url"],
        })

    log.info(f"Hermsen: scraped {len(listings)} listings")
    return listings
