import re
import logging
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)
BASE_URL = "https://www.ooststede.nl/aanbod/woningaanbod/Nijmegen/koop/provincie-Gelderland/"
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
    """Fetch price, surface, energy from Ooststede detail page."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        price_text = "onbekend"
        surface_text = "onbekend"
        surface_int = 0
        energy = "onbekend"

        def process(label: str, value: str):
            nonlocal price_text, surface_text, surface_int, energy
            label = label.lower()
            if any(w in label for w in ["vraagprijs", "koopsom", "koopprijs"]):
                price_text = value
            elif "woonoppervlakt" in label or "woonfunctie" in label:
                surface_int = parse_surface(value)
                surface_text = f"{value} m²" if "m" not in value.lower() else value
            elif "energielabel" in label or "energieklasse" in label:
                energy = value

        # Ooststede uses same Sure/Realworks CMS as Hans Janssen
        for lbl in soup.find_all(class_="kenmerkLabel"):
            val = lbl.find_next_sibling(class_="kenmerkValue")
            if val:
                process(lbl.get_text(strip=True), val.get_text(strip=True))

        # Try house-feature divs
        for wrapper in soup.select(".house-feature-wrapper"):
            lbl = wrapper.find(class_="house-feature-label")
            val = wrapper.find(class_="house-feature-value")
            if lbl and val:
                process(lbl.get_text(strip=True), val.get_text(strip=True))

        # Fallback: icon-based li items (like Hans Janssen)
        for li in soup.find_all("li"):
            i_tag = li.find("i")
            if not i_tag:
                continue
            classes = i_tag.get("class", [])
            text = li.get_text(strip=True)
            if "icon-surface" in classes:
                surface_int = parse_surface(text)
                surface_text = text
            elif "icon-label" in classes:
                energy = text

        if price_text == "onbekend":
            for el in soup.find_all(string=re.compile(r"€\s*[\d\.]+")):
                t = el.strip()
                if re.search(r"\d{3}", t) and ",-" in t:
                    price_text = t
                    break

        price_raw = parse_price(price_text)
        price_per_m2 = calc_price_per_m2(price_raw, surface_int)
        return {"price_text": price_text, "price_raw": price_raw,
                "surface": surface_text, "energy": energy, "price_per_m2": price_per_m2}
    except Exception as e:
        log.debug(f"Ooststede detail failed for {url}: {e}")
        return {"price_text": "onbekend", "price_raw": 0, "surface": "onbekend",
                "energy": "onbekend", "price_per_m2": "onbekend"}


async def scrape_ooststede() -> list[dict]:
    """
    Ooststede uses same CMS as Hans Janssen (Sure).
    URL pattern: /aanbod/woningaanbod/NIJMEGEN/koop/.../object-NNNNxxx/
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
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
            content = await page.content()
        except Exception as e:
            log.error(f"Ooststede listing page failed: {e}")
            content = ""
        finally:
            await browser.close()

    if not content:
        return []

    soup = BeautifulSoup(content, "html.parser")
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full_url = href if href.startswith("http") else f"https://www.ooststede.nl{href}"
        if not re.search(r"/aanbod/woningaanbod/.+/.+/", full_url):
            continue
        if full_url.rstrip("/") == BASE_URL.rstrip("/"):
            continue
        if any(x in full_url for x in ["?", "pagina", "filter", "provincie"]) and "object" not in full_url:
            continue
        if full_url not in seen:
            seen.add(full_url)
            property_urls.append(full_url)

    log.info(f"Ooststede: found {len(property_urls)} URLs, fetching details...")

    listings = []
    for url in property_urls:
        detail = await fetch_detail(url)
        if detail["price_raw"] == 0:
            continue
        # Extract address from URL: /aanbod/woningaanbod/NIJMEGEN/.../straat-nr-stad/
        slug = url.rstrip("/").split("/")[-1]
        address = slug.replace("-", " ").title()
        listings.append({
            "source": "Ooststede",
            "title": f"{address}, Nijmegen",
            "price_raw": detail["price_raw"],
            "price": detail["price_text"],
            "surface": detail["surface"],
            "energy": detail["energy"],
            "price_per_m2": detail["price_per_m2"],
            "url": url,
        })

    log.info(f"Ooststede: scraped {len(listings)} listings")
    return listings
