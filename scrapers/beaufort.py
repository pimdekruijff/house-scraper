import re
import logging
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)
BASE_URL = "https://www.beaufortmakelaars.nl/woningen/"
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


async def fetch_detail_playwright(url: str) -> dict:
    """
    Beaufort loads kenmerken via JS — use Playwright to render the page.
    Price: "€ 685.000,- k.k." near "Te Koop"
    Surface + energy: in kenmerken section rendered after JS load.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=HEADERS["User-Agent"])
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            content = await page.content()
            await browser.close()

        soup = BeautifulSoup(content, "html.parser")

        price_text = "onbekend"
        surface_text = "onbekend"
        surface_int = 0
        energy = "onbekend"

        # Price: standalone € amount on page
        for el in soup.find_all(string=re.compile(r"€\s*[\d\.]+")):
            t = el.strip()
            if re.search(r"€\s*\d{3}", t) and ",-" in t:
                price_text = t
                break

        # Scan all label/value pairs — Beaufort uses various CMS structures
        full_text = soup.get_text(" ")

        # Try structured kenmerken divs first
        for wrapper in soup.select(".property-feature, .kenmerk, [class*='feature']"):
            label_el = wrapper.find(class_=re.compile(r"label|title|key"))
            value_el = wrapper.find(class_=re.compile(r"value|val"))
            if not label_el or not value_el:
                continue
            label = label_el.get_text(strip=True).lower()
            value = value_el.get_text(strip=True)
            if "woonoppervlak" in label or "oppervlak" in label:
                surface_int = parse_surface(value)
                surface_text = f"{value} m²" if "m" not in value.lower() else value
            elif "energielabel" in label or "energieklasse" in label:
                energy = value

        # Fallback: scan text for patterns
        if surface_text == "onbekend":
            m = re.search(r"(\d+)\s*m²?\s*(woon|gebruiks|woonopp)", full_text, re.I)
            if not m:
                m = re.search(r"[Ww]oon\w*\s+(\d+)\s*m", full_text)
            if m:
                surface_int = int(m.group(1))
                surface_text = f"{surface_int} m²"

        if energy == "onbekend":
            m = re.search(r"[Ee]nergielabel\s*:?\s*([A-G]\+{0,4})", full_text)
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
        log.debug(f"Beaufort detail fetch failed for {url}: {e}")
        return {"price_text": "onbekend", "price_raw": 0, "surface": "onbekend",
                "energy": "onbekend", "price_per_m2": "onbekend"}


async def scrape_beaufort() -> list[dict]:
    """
    Listing page: use httpx, collect /woning/stad-straat-nr/ links.
    Detail pages: use Playwright (JS rendered).
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            resp = await client.get(BASE_URL, headers=HEADERS)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.error(f"Beaufort listing page failed: {e}")
        return []

    seen = set()
    items = []
    for a in soup.find_all("a", href=re.compile(r"/woning/")):
        href = a["href"]
        url = href if href.startswith("http") else f"https://www.beaufortmakelaars.nl{href}"
        if url in seen:
            continue
        seen.add(url)

        # /woning/nijmegen-van-peltlaan-222/ -> Van Peltlaan 222, Nijmegen
        slug = url.rstrip("/").split("/")[-1]
        # First word is city
        parts = slug.split("-")
        city = parts[0].title()
        street = " ".join(parts[1:]).title()
        address = f"{street}, {city}"

        items.append({"url": url, "address": address})

    log.info(f"Beaufort: found {len(items)} property URLs, fetching details...")

    listings = []
    for item in items:
        detail = await fetch_detail_playwright(item["url"])
        if detail["price_raw"] == 0:
            continue
        listings.append({
            "source": "Beaufort",
            "title": item["address"],
            "price_raw": detail["price_raw"],
            "price": detail["price_text"],
            "surface": detail["surface"],
            "energy": detail["energy"],
            "price_per_m2": detail["price_per_m2"],
            "url": item["url"],
        })

    log.info(f"Beaufort: scraped {len(listings)} listings")
    return listings
