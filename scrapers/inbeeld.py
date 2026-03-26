import re
import logging
import asyncio
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
BASE_URL = "https://www.inbeeldmakelaardij.nl/woningaanbod"
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
    Fetch details from an In Beeld detail page.
    Info is in .house-feature-label / .house-feature-value div pairs:
      Gebruiksoppervlakte woonfunctie (m2) -> surface
      Energieklasse                         -> energy
    Price is in the page header or a separate element.
    """
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        price_text = "onbekend"
        surface_text = "onbekend"
        surface_int = 0
        energy = "onbekend"

        # Parse label/value div pairs
        for wrapper in soup.select(".house-feature-wrapper"):
            label_el = wrapper.find(class_="house-feature-label")
            value_el = wrapper.find(class_="house-feature-value")
            if not label_el or not value_el:
                continue
            label = label_el.get_text(strip=True).lower()
            value = value_el.get_text(strip=True)

            if any(w in label for w in ["vraagprijs", "koopsom", "prijs"]):
                price_text = value
            elif "woonfunctie" in label or "woonoppervlakt" in label:
                surface_int = parse_surface(value)
                surface_text = f"{value} m²"
            elif "energieklasse" in label or "energielabel" in label:
                energy = value

        # Price may also be in a dedicated price element in the header
        if price_text == "onbekend":
            for el in soup.find_all(string=re.compile(r"€\s*[\d\.]+")):
                t = el.strip()
                if "€" in t and re.search(r"\d{3}", t):
                    price_text = t
                    break

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
        log.debug(f"In Beeld detail fetch failed for {url}: {e}")
        return {"price_text": "onbekend", "price_raw": 0, "surface": "onbekend",
                "energy": "onbekend", "price_per_m2": "onbekend"}


async def scrape_inbeeld() -> list[dict]:
    """
    Step 1: fetch listing page, collect all /woningaanbod/straat-nr-stad URLs.
    Step 2: fetch each detail page concurrently.
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(BASE_URL, headers=HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen = set()
        items = []
        for a in soup.find_all("a", href=re.compile(r"/woningaanbod/[^/]+")):
            href = a["href"]
            url = href if href.startswith("http") else f"https://www.inbeeldmakelaardij.nl{href}"
            # Skip the listing page itself
            if url.rstrip("/") == BASE_URL.rstrip("/"):
                continue
            if url in seen:
                continue
            seen.add(url)

            # Extract address from slug: henk-van-tienhovenstraat-12-nijmegen
            slug = url.rstrip("/").split("/")[-1]
            parts = slug.split("-")
            # Last part is likely city, rest is street + number
            city = parts[-1].title() if parts else ""
            street = " ".join(parts[:-1]).title() if len(parts) > 1 else slug.title()
            address = f"{street}, {city}" if city else street

            items.append({"url": url, "address": address})

        log.info(f"In Beeld: found {len(items)} property URLs, fetching details...")

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
            "source": "In Beeld",
            "title": r["address"],
            "price_raw": r["price_raw"],
            "price": r["price_text"],
            "surface": r["surface"],
            "energy": r["energy"],
            "price_per_m2": r["price_per_m2"],
            "url": r["url"],
        })

    log.info(f"In Beeld: scraped {len(listings)} listings")
    return listings
