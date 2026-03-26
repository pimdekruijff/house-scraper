import re
import logging
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)
BASE_URL = "https://www.verbeek-makelaars.nl/aanbod/woningaanbod/nijmegen/koop/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "nl-NL,nl;q=0.9",
}


def parse_price(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def parse_surface(text: str) -> int:
    """Extract integer m² value from strings like '112 m²' or '112m2'."""
    m = re.search(r"(\d+)", text.replace(".", ""))
    return int(m.group(1)) if m else 0


def calc_price_per_m2(price: int, surface: int) -> str:
    if price and surface:
        return f"€ {price // surface:,.0f}".replace(",", ".")
    return "onbekend"


async def fetch_detail(url: str) -> dict:
    """
    Fetch price, surface, energy label and price per m² from a Verbeek detail page.
    Key elements:
      <span class="kenmerkValue">€ 850.000,- kosten koper</span>
      <span class="kenmerkValue">112 m²</span>  (woonoppervlakte)
      <span class="kenmerkValue">A</span>        (energielabel)
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        price_text = "onbekend"
        surface_text = "onbekend"
        surface_int = 0
        energy = "onbekend"
        price_per_m2 = "onbekend"

        # Find all kenmerkLabel/kenmerkValue pairs
        labels = soup.find_all(class_="kenmerkLabel")
        for label in labels:
            label_text = label.get_text(strip=True).lower()
            value_el = label.find_next_sibling(class_="kenmerkValue")
            if not value_el:
                continue
            value = value_el.get_text(strip=True)

            if "prijs" in label_text or "koopsom" in label_text or "vraagprijs" in label_text:
                price_text = value
            elif "woonoppervlak" in label_text or "oppervlak" in label_text:
                surface_text = value
                surface_int = parse_surface(value)
            elif "energielabel" in label_text or "energie" in label_text:
                energy = value
            elif "prijs per m" in label_text:
                price_per_m2 = value

        # Fallback: if price not found via label, look for kenmerkValue with €
        if price_text == "onbekend":
            for span in soup.find_all(class_="kenmerkValue"):
                if "€" in span.get_text():
                    price_text = span.get_text(strip=True)
                    break

        price_raw = parse_price(price_text)

        # Calculate price per m² if not found on page
        if price_per_m2 == "onbekend":
            price_per_m2 = calc_price_per_m2(price_raw, surface_int)

        return {
            "price_text": price_text,
            "price_raw": price_raw,
            "surface": surface_text,
            "energy": energy,
            "price_per_m2": price_per_m2,
        }
    except Exception as e:
        log.debug(f"Verbeek detail fetch failed for {url}: {e}")
        return {
            "price_text": "onbekend",
            "price_raw": 0,
            "surface": "onbekend",
            "energy": "onbekend",
            "price_per_m2": "onbekend",
        }


async def scrape_verbeek() -> list[dict]:
    """
    Step 1: use Playwright to load the listing page and collect property URLs.
    Step 2: fetch each detail page with httpx for price, surface, energy, price/m².
    """
    property_urls = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="nl-NL",
            extra_http_headers={"Accept-Language": "nl-NL,nl;q=0.9"},
        )
        page = await context.new_page()
        try:
            await page.goto(BASE_URL, wait_until="networkidle", timeout=40000)
            await page.wait_for_timeout(3000)
            content = await page.content()
        except Exception as e:
            log.error(f"Verbeek listing page failed: {e}")
            content = ""
        finally:
            await browser.close()

    if not content:
        return []

    soup = BeautifulSoup(content, "html.parser")
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Verbeek property links contain /aanbod/ + a property slug
        if not re.search(r"/aanbod/[^/]+/[^/]+", href):
            continue
        if "/woningaanbod/nijmegen/koop/" in href:
            continue  # skip the listing page itself
        url = href if href.startswith("http") else f"https://www.verbeek-makelaars.nl{href}"
        if url not in seen:
            seen.add(url)
            property_urls.append(url)

    log.info(f"Verbeek: found {len(property_urls)} property URLs, fetching details...")

    listings = []
    for url in property_urls:
        detail = await fetch_detail(url)
        if not detail or detail["price_raw"] == 0:
            continue

        # Extract address from URL slug: /aanbod/woningaanbod/straat-huisnummer-stad/
        slug = url.rstrip("/").split("/")[-1]
        address = slug.replace("-", " ").title()

        listings.append({
            "source": "Verbeek",
            "title": address,
            "price_raw": detail["price_raw"],
            "price": detail["price_text"],
            "surface": detail["surface"],
            "energy": detail["energy"],
            "price_per_m2": detail["price_per_m2"],
            "url": url,
        })

    log.info(f"Verbeek: scraped {len(listings)} listings")
    return listings
