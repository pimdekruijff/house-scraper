import re
import logging
import asyncio
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
BASE_URL = "https://www.hansjanssen.nl/wonen/"
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
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        surface_text = "onbekend"
        surface_int = 0
        energy = "onbekend"

        for li in soup.find_all("li"):
            i_tag = li.find("i")
            if not i_tag:
                continue
            classes = i_tag.get("class", [])
            text = li.get_text(strip=True)
            if "icon-surface" in classes:
                surface_text = text
                surface_int = parse_surface(text)
            elif "icon-label" in classes:
                energy = text

        return {"surface": surface_text, "surface_int": surface_int, "energy": energy}
    except Exception as e:
        log.debug(f"Hans Janssen detail fetch failed for {url}: {e}")
        return {"surface": "onbekend", "surface_int": 0, "energy": "onbekend"}


async def scrape_hansjanssen() -> list[dict]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(BASE_URL, headers=HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        items = []
        for a in soup.find_all("a", href=re.compile(r"/wonen/object/")):
            href = a["href"]
            url = href if href.startswith("http") else f"https://www.hansjanssen.nl{href}"

            h6 = a.find("h6")
            if not h6:
                continue
            street = h6.get_text(strip=True)

            texts = [t.strip() for t in a.stripped_strings if t.strip()]
            price_text = next((t for t in texts if "€" in t), "onbekend")
            price_raw = parse_price(price_text)

            location = next(
                (t for t in texts if re.match(r"\d{4}\s+[a-z]{2}\s+\w", t, re.I)), ""
            )
            title = f"{street}, {location}" if location else street

            items.append({
                "source": "Hans Janssen",
                "title": title,
                "price_raw": price_raw,
                "price": price_text,
                "url": url,
            })

        semaphore = asyncio.Semaphore(5)

        async def fetch_with_semaphore(item):
            async with semaphore:
                detail = await fetch_detail(client, item["url"])
                price_per_m2 = calc_price_per_m2(item["price_raw"], detail["surface_int"])
                return {**item, "surface": detail["surface"], "energy": detail["energy"], "price_per_m2": price_per_m2}

        listings = await asyncio.gather(*[fetch_with_semaphore(item) for item in items])

    log.info(f"Hans Janssen: scraped {len(listings)} listings")
    return list(listings)
