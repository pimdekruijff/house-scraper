import re
import logging
import asyncio
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
BASE_URL = "https://driessenmakelaardij.nl/woningaanbod/"
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
    Fetch details from a Driessen property page.
    Info is in <table class="realworks-features-list__list"> with <th>/<td> pairs:
      Vraagprijs        -> price
      Woonoppervlakte   -> surface
      Energielabel / Voorlopig energielabel -> energy
    """
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        price_text = "onbekend"
        surface_text = "onbekend"
        surface_int = 0
        energy = "onbekend"

        for row in soup.select("tr.realworks-features-list__item"):
            th = row.find("th")
            td = row.find("td")
            if not th or not td:
                continue
            label = th.get_text(strip=True).lower()
            value = td.get_text(strip=True)

            if "vraagprijs" in label:
                price_text = value
            elif "woonoppervlakte" in label:
                surface_text = value
                surface_int = parse_surface(value)
            elif "energielabel" in label:
                # Prefer definitive label over "voorlopig"
                if energy == "onbekend" or "voorlopig" not in label:
                    energy = value

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
        log.debug(f"Driessen detail fetch failed for {url}: {e}")
        return {"price_text": "onbekend", "price_raw": 0, "surface": "onbekend",
                "energy": "onbekend", "price_per_m2": "onbekend"}


async def scrape_driessen() -> list[dict]:
    """
    Step 1: fetch listing page, collect all /woning/ URLs.
    Step 2: fetch each detail page concurrently for price, surface, energy.
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(BASE_URL, headers=HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Collect property URLs: /woning/stad-straat-huisnummer/
        seen = set()
        items = []
        for a in soup.find_all("a", href=re.compile(r"/woning/")):
            href = a["href"]
            url = href if href.startswith("http") else f"https://driessenmakelaardij.nl{href}"
            if url in seen:
                continue
            seen.add(url)

            # Extract address from slug: wijchen-europaplein-11 -> Europaplein 11, Wijchen
            slug = url.rstrip("/").split("/")[-1]
            parts = slug.split("-")
            # First part is the city
            city = parts[0].title() if parts else ""
            street = " ".join(parts[1:]).title() if len(parts) > 1 else slug.title()
            address = f"{street}, {city}" if city else street

            items.append({"url": url, "address": address})

        log.info(f"Driessen: found {len(items)} property URLs, fetching details...")

        # Fetch details concurrently (max 5 at a time)
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
            "source": "Driessen",
            "title": r["address"],
            "price_raw": r["price_raw"],
            "price": r["price_text"],
            "surface": r["surface"],
            "energy": r["energy"],
            "price_per_m2": r["price_per_m2"],
            "url": r["url"],
        })

    log.info(f"Driessen: scraped {len(listings)} listings")
    return listings
