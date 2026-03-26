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


async def fetch_detail(page, url: str) -> dict:
    """
    Fetch a Beaufort detail page using an existing Playwright page object.
    Reusing the page avoids the overhead of launching a new browser per property.
    """
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(1500)
        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")

        price_text = "onbekend"
        surface_text = "onbekend"
        surface_int = 0
        energy = "onbekend"
        full_text = soup.get_text(" ")

        # Price: standalone € amount
        for el in soup.find_all(string=re.compile(r"€\s*[\d\.]+")):
            t = el.strip()
            if re.search(r"€\s*\d{3}", t) and ",-" in t:
                price_text = t
                break

        # Structured label/value pairs
        def process(label: str, value: str):
            nonlocal price_text, surface_text, surface_int, energy
            label = label.lower()
            if any(w in label for w in ["vraagprijs", "koopsom"]):
                price_text = value
            elif "woonoppervlak" in label or "oppervlak" in label:
                surface_int = parse_surface(value)
                surface_text = f"{value} m²" if "m" not in value.lower() else value
            elif "energielabel" in label or "energieklasse" in label:
                energy = value

        for wrapper in soup.select(".property-feature, .kenmerk, [class*='feature']"):
            lbl = wrapper.find(class_=re.compile(r"label|title|key"))
            val = wrapper.find(class_=re.compile(r"value|val"))
            if lbl and val:
                process(lbl.get_text(strip=True), val.get_text(strip=True))

        # Fallback: scan full text
        if surface_text == "onbekend":
            m = re.search(r"(\d+)\s*m²?\s*(woon|gebruiks)", full_text, re.I)
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
        return {"price_text": price_text, "price_raw": price_raw,
                "surface": surface_text, "energy": energy, "price_per_m2": price_per_m2}
    except Exception as e:
        log.debug(f"Beaufort detail fetch failed for {url}: {e}")
        return {"price_text": "onbekend", "price_raw": 0, "surface": "onbekend",
                "energy": "onbekend", "price_per_m2": "onbekend"}


async def scrape_beaufort() -> list[dict]:
    """
    Optimized: één browser, één page object hergebruikt voor alle detailpagina's.
    Listing page via httpx, details via Playwright.
    """
    # Step 1: get listing page with httpx
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
        slug = url.rstrip("/").split("/")[-1]
        parts = slug.split("-")
        city = parts[0].title()
        street = " ".join(parts[1:]).title()
        items.append({"url": url, "address": f"{street}, {city}"})

    log.info(f"Beaufort: found {len(items)} property URLs, fetching details...")

    # Step 2: reuse ONE browser + ONE page for all detail fetches
    listings = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=HEADERS["User-Agent"])

        for item in items:
            detail = await fetch_detail(page, item["url"])
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

        await browser.close()

    log.info(f"Beaufort: scraped {len(listings)} listings")
    return listings
