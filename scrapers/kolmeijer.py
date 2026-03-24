import re
import logging
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)
BASE_URL = "https://www.kolmeijernijmegen.nl/aanbod/"


def parse_price(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


async def scrape_kolmeijer() -> list[dict]:
    """
    Kolmeijer returns 403 on plain requests, so we use Playwright.
    We wait for the page to fully load and then parse all property links.
    """
    listings = []
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
            log.error(f"Kolmeijer page load failed: {e}")
            content = ""
        finally:
            await browser.close()

    if not content:
        return listings

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, "html.parser")

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Kolmeijer property links typically contain /aanbod/ + a slug
        if "/aanbod/" not in href or href.rstrip("/") == BASE_URL.rstrip("/"):
            continue
        url = href if href.startswith("http") else f"https://www.kolmeijernijmegen.nl{href}"
        if url in seen:
            continue
        seen.add(url)

        texts = [t.strip() for t in a.stripped_strings if t.strip()]
        if not texts:
            continue

        price_text = next((t for t in texts if "€" in t), "onbekend")
        price_raw = parse_price(price_text)
        title = texts[0]

        location = next(
            (t for t in texts if re.match(r"\d{4}\s*[a-z]{2}", t, re.I)),
            title
        )

        listings.append({
            "source": "Kolmeijer",
            "title": f"{title}, {location}",
            "price_raw": price_raw,
            "price": price_text,
            "surface": "zie woning",
            "energy": "zie woning",
            "url": url,
        })

    log.info(f"Kolmeijer: scraped {len(listings)} listings")
    return listings
