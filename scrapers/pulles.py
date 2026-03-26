import re
import logging
import asyncio
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
BASE_URL = "https://www.pullesmakelaardij.nl/wonen/"
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
    Fetch details from a Pulles detail page.
    - Price: text containing "Vraagprijs" near an €-value
    - Surface + energy: <li> items in .house-media__list:
        "Woonruimte ca. 71 m²"
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

        # Price: look for "Vraagprijs" text followed by €-amount
        for el in soup.find_all(string=re.compile(r"Vraagprijs")):
            parent = el.parent
            full = parent.get_text(strip=True)
            m = re.search(r"€[\s\d\.,]+-", full)
            if m:
                price_text = full[full.index("€"):].strip()
                break

        # Fallback: any standalone € amount in the header area
        if price_text == "onbekend":
            for el in soup.find_all(string=re.compile(r"€\s*[\d\.]+")):
                t = el.strip()
                if re.search(r"\d{3}", t):
                    price_text = t
                    break

        # Kenmerken from .house-media__list li items
        for li in soup.select("ul.house-media__list li.is-active"):
            text = li.get_text(strip=True)
            # Surface: "Woonruimte ca. 71 m²"
            if re.search(r"woonruimte", text, re.I):
                surface_text = text
                surface_int = parse_surface(text)
            # Energy: "Energielabel B"
            elif re.search(r"energielabel", text, re.I):
                energy = re.sub(r"energielabel\s*", "", text, flags=re.I).strip()

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
        log.debug(f"Pulles detail fetch failed for {url}: {e}")
        return {"price_text": "onbekend", "price_raw": 0, "surface": "onbekend",
                "energy": "onbekend", "price_per_m2": "onbekend"}


async def scrape_pulles() -> list[dict]:
    """
    Step 1: fetch listing page (server-side rendered), collect /wonen/object/ URLs.
    Step 2: fetch each detail page concurrently.
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(BASE_URL, headers=HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen = set()
        items = []
        for a in soup.find_all("a", href=re.compile(r"/wonen/object/")):
            href = a["href"]
            url = href if href.startswith("http") else f"https://www.pullesmakelaardij.nl{href}"
            if url in seen:
                continue
            seen.add(url)

            # Extract address from slug: lage-markt-11-nijmegen -> Lage Markt 11, Nijmegen
            slug = url.rstrip("/").split("/")[-1]
            parts = slug.split("-")
            # Last part is city
            city = parts[-1].title() if parts else ""
            street = " ".join(parts[:-1]).title() if len(parts) > 1 else slug.title()
            address = f"{street}, {city}" if city else street

            items.append({"url": url, "address": address})

        log.info(f"Pulles: found {len(items)} property URLs, fetching details...")

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
            "source": "Pulles",
            "title": r["address"],
            "price_raw": r["price_raw"],
            "price": r["price_text"],
            "surface": r["surface"],
            "energy": r["energy"],
            "price_per_m2": r["price_per_m2"],
            "url": r["url"],
        })

    log.info(f"Pulles: scraped {len(listings)} listings")
    return listings
