import re
import logging
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)
BASE_URL = "https://www.rotsvast.nl/woningaanbod/?type=2&city=Nijmegen"
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


async def fetch_detail(url: str) -> dict:
    """Fetch price, surface, energy from a Rotsvast property page."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        price_text = "onbekend"
        surface_text = "onbekend"
        surface_int = 0
        energy = "onbekend"

        full_text = soup.get_text(" ")

        # Price: € amount
        for el in soup.find_all(string=re.compile(r"€\s*[\d\.]+")):
            t = el.strip()
            if re.search(r"\d{3}", t) and "k.k" in t.lower():
                price_text = t
                break

        # Try structured label/value pairs
        def process(label: str, value: str):
            nonlocal price_text, surface_text, surface_int, energy
            label = label.lower()
            if any(w in label for w in ["vraagprijs", "koopsom", "prijs"]):
                if "€" in value or re.search(r"\d{3}", value):
                    price_text = value
            elif "woonoppervlakt" in label or "woonfunctie" in label:
                surface_int = parse_surface(value)
                surface_text = f"{value} m²" if "m" not in value.lower() else value
            elif "energielabel" in label or "energieklasse" in label:
                energy = value

        for lbl in soup.find_all(class_="kenmerkLabel"):
            val = lbl.find_next_sibling(class_="kenmerkValue")
            if val:
                process(lbl.get_text(strip=True), val.get_text(strip=True))

        for wrapper in soup.select(".house-feature-wrapper, .property-feature, [class*='feature']"):
            lbl = wrapper.find(class_=re.compile(r"label|key"))
            val = wrapper.find(class_=re.compile(r"value|val"))
            if lbl and val:
                process(lbl.get_text(strip=True), val.get_text(strip=True))

        if surface_text == "onbekend":
            m = re.search(r"(\d+)\s*m²?\s*(woon|gebruiks)", full_text, re.I)
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
        log.debug(f"Rotsvast detail failed for {url}: {e}")
        return {"price_text": "onbekend", "price_raw": 0, "surface": "onbekend",
                "energy": "onbekend", "price_per_m2": "onbekend"}


async def scrape_rotsvast() -> list[dict]:
    """
    Rotsvast listing filtered on Nijmegen koop.
    Listing page likely JS-rendered.
    """
    property_urls = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            locale="nl-NL",
        )
        page = await context.new_page()
        try:
            await page.goto(BASE_URL, wait_until="networkidle", timeout=40000)
            await page.wait_for_timeout(3000)
            content = await page.content()
        except Exception as e:
            log.error(f"Rotsvast listing page failed: {e}")
            content = ""
        finally:
            await browser.close()

    if not content:
        return []

    soup = BeautifulSoup(content, "html.parser")
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full_url = href if href.startswith("http") else f"https://www.rotsvast.nl{href}"
        # Property pages: /woningaanbod/rotsvast-.../object/
        if not re.search(r"/woningaanbod/.+/", full_url):
            continue
        if "rotsvast.nl/woningaanbod/" not in full_url:
            continue
        if any(x in full_url for x in ["?", "page=", "filter", "#"]):
            continue
        if full_url.rstrip("/") == "https://www.rotsvast.nl/woningaanbod":
            continue
        if full_url not in seen:
            seen.add(full_url)
            property_urls.append(full_url)

    log.info(f"Rotsvast: found {len(property_urls)} URLs, fetching details...")

    listings = []
    for url in property_urls:
        detail = await fetch_detail(url)
        if detail["price_raw"] == 0:
            continue
        # Extract address from URL or page
        slug = url.rstrip("/").split("/")[-1]
        address = slug.replace("-", " ").title()
        listings.append({
            "source": "Rotsvast",
            "title": f"{address}, Nijmegen",
            "price_raw": detail["price_raw"],
            "price": detail["price_text"],
            "surface": detail["surface"],
            "energy": detail["energy"],
            "price_per_m2": detail["price_per_m2"],
            "url": url,
        })

    log.info(f"Rotsvast: scraped {len(listings)} listings")
    return listings
