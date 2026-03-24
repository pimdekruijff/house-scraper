import re
import logging
from bs4 import BeautifulSoup
import httpx

log = logging.getLogger(__name__)
BASE_URL = "https://www.hansjanssen.nl/wonen/"


def parse_price(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


async def scrape_hansjanssen() -> list[dict]:
    """
    Hans Janssen renders listings server-side — no JS needed.
    Each listing is an <a> tag linking to /wonen/object/... containing:
      - <h6> for the street name
      - price text like "€ 265.000,- k.k."
      - postcode + city text like "6541 rv Nijmegen"
    """
    listings = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "nl-NL,nl;q=0.9",
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        resp = await client.get(BASE_URL, headers=headers)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    for a in soup.find_all("a", href=re.compile(r"/wonen/object/")):
        try:
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
                (t for t in texts if re.match(r"\d{4}\s+[a-z]{2}\s+\w", t, re.I)),
                street
            )

            listings.append({
                "source": "Hans Janssen",
                "title": f"{street}, {location}",
                "price_raw": price_raw,
                "price": price_text,
                "surface": "zie woning",
                "energy": "zie woning",
                "url": url,
            })
        except Exception as e:
            log.debug(f"Hans Janssen parse error: {e}")

    log.info(f"Hans Janssen: scraped {len(listings)} listings")
    return listings
