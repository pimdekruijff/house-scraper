import re
import logging
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)
BASE_URL = "https://www.kolmeijernijmegen.nl/aanbod/"
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
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        h1 = soup.find("h1", class_="house-header__title")
        address = h1.get_text(strip=True) if h1 else ""

        loc_div = soup.find("div", class_="house-header__location")
        location = loc_div.get_text(strip=True) if loc_div else ""

        price_div = soup.find("div", class_="house-header__price")
        price_text = price_div.get_text(strip=True) if price_div else "onbekend"
        price_raw = parse_price(price_text)

        surface_text = "onbekend"
        surface_int = 0
        energy = "onbekend"

        for item in soup.find_all("div", class_="house-header__meta-item-label"):
            text = item.get_text(strip=True)
            if "wonen" in text:
                surface_text = text.replace("wonen", "").strip()
                surface_int = parse_surface(surface_text)
            elif "energielabel" in text:
                energy = text.replace("energielabel", "").strip()

        price_per_m2 = calc_price_per_m2(price_raw, surface_int)

        return {
            "address": address,
            "location": location,
            "price_text": price_text,
            "price_raw": price_raw,
            "surface": surface_text,
            "energy": energy,
            "price_per_m2": price_per_m2,
        }
    except Exception as e:
        log.debug(f"Kolmeijer detail fetch failed for {url}: {e}")
        return {}


async def scrape_kolmeijer() -> list[dict]:
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
            log.error(f"Kolmeijer listing page failed: {e}")
            content = ""
        finally:
            await browser.close()

    if not content:
        return []

    soup = BeautifulSoup(content, "html.parser")
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/aanbod/" not in href or href.rstrip("/") == BASE_URL.rstrip("/"):
            continue
        url = href if href.startswith("http") else f"https://www.kolmeijernijmegen.nl{href}"
        if url not in seen:
            seen.add(url)
            property_urls.append(url)

    listings = []
    for url in property_urls:
        detail = await fetch_detail(url)
        if not detail or not detail.get("address"):
            continue
        listings.append({
            "source": "Kolmeijer",
            "title": f"{detail['address']}, {detail['location']}",
            "price_raw": detail["price_raw"],
            "price": detail["price_text"],
            "surface": detail["surface"],
            "energy": detail["energy"],
            "price_per_m2": detail["price_per_m2"],
            "url": url,
        })

    log.info(f"Kolmeijer: scraped {len(listings)} listings")
    return listings
