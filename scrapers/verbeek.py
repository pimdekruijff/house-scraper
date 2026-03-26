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
    m = re.search(r"(\d+)", text.replace(".", ""))
    return int(m.group(1)) if m else 0


def calc_price_per_m2(price: int, surface: int) -> str:
    if price and surface:
        return f"€ {price // surface:,.0f}".replace(",", ".")
    return "onbekend"


async def fetch_detail(url: str) -> dict:
    """Fetch price, surface, energy label from a Verbeek detail page."""
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

        # Try label/value pairs first
        labels = soup.find_all(class_="kenmerkLabel")
        for label in labels:
            label_text = label.get_text(strip=True).lower()
            value_el = label.find_next_sibling(class_="kenmerkValue")
            if not value_el:
                continue
            value = value_el.get_text(strip=True)

            if any(w in label_text for w in ["prijs", "koopsom", "vraagprijs"]):
                price_text = value
            elif any(w in label_text for w in ["woonoppervlak", "oppervlak"]):
                surface_text = value
                surface_int = parse_surface(value)
            elif any(w in label_text for w in ["energielabel", "energie"]):
                energy = value
            elif "prijs per m" in label_text:
                price_per_m2 = value

        # Fallback: any kenmerkValue containing €
        if price_text == "onbekend":
            for span in soup.find_all(class_="kenmerkValue"):
                t = span.get_text(strip=True)
                if "€" in t:
                    price_text = t
                    break

        # Fallback: look for price anywhere on page
        if price_text == "onbekend":
            for el in soup.find_all(string=re.compile(r"€\s*[\d\.]+")):
                price_text = el.strip()
                break

        price_raw = parse_price(price_text)
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
        return {"price_text": "onbekend", "price_raw": 0, "surface": "onbekend",
                "energy": "onbekend", "price_per_m2": "onbekend"}


async def scrape_verbeek() -> list[dict]:
    """
    Step 1: Playwright to load listing page, collect all property URLs.
    Step 2: httpx to fetch each detail page.
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
            # Log all hrefs for debugging
            all_links = await page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.getAttribute('href'))"
            )
            log.info(f"Verbeek: found {len(all_links)} total links on page")
            aanbod_links = [l for l in all_links if l and "aanbod" in l]
            log.info(f"Verbeek: aanbod links: {aanbod_links[:20]}")
        except Exception as e:
            log.error(f"Verbeek listing page failed: {e}")
            content = ""
            all_links = []
        finally:
            await browser.close()

    if not content:
        return []

    soup = BeautifulSoup(content, "html.parser")
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        full_url = href if href.startswith("http") else f"https://www.verbeek-makelaars.nl{href}"

        # Property pages are deeper than the listing page itself
        # BASE_URL has 6 segments: /aanbod/woningaanbod/nijmegen/koop/
        # Property pages have one more: /aanbod/woningaanbod/nijmegen/koop/straat-nr/
        if not href:
            continue
        path = href.rstrip("/")
        # Must contain the base path and have at least one extra segment
        # Property URLs match pattern: /aanbod/woningaanbod/nijmegen/koop/huis-XXXXXXX-straat-nr/
        if not re.search(r"/aanbod/woningaanbod/nijmegen/koop/[^/]+", full_url):
            continue
        if full_url.rstrip("/") == BASE_URL.rstrip("/"):
            continue
        if full_url not in seen:
            seen.add(full_url)
            property_urls.append(full_url)

    log.info(f"Verbeek: found {len(property_urls)} property URLs")

    listings = []
    for url in property_urls:
        detail = await fetch_detail(url)
        if not detail or detail["price_raw"] == 0:
            log.debug(f"Verbeek: skipping {url} (no price)")
            continue

        # Extract address from URL slug: huis-9049930-Batavierenweg-44 -> Batavierenweg 44
        slug = url.rstrip("/").split("/")[-1]
        slug_clean = re.sub(r"^[a-z]+-\d+-", "", slug)
        address = slug_clean.replace("-", " ").title()

        listings.append({
            "source": "Verbeek",
            "title": f"{address}, Nijmegen",
            "price_raw": detail["price_raw"],
            "price": detail["price_text"],
            "surface": detail["surface"],
            "energy": detail["energy"],
            "price_per_m2": detail["price_per_m2"],
            "url": url,
        })

    log.info(f"Verbeek: scraped {len(listings)} listings with price")
    return listings
