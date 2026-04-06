"""
Fetcher — Craigslist's internal JSON API via headless Playwright.

Flow:
  1. Spin up headless Chromium
  2. Call sapi.craigslist.org → get all listings as JSON
  3. Filter to unseen listings only
  4. For listings that pass Haiku pre-screen (main.py), fetch descriptions on demand
"""

import logging
import re
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from config import MAX_PRICE

logger = logging.getLogger(__name__)

SEARCH_API = (
    "https://sapi.craigslist.org/web/v8/postings/search/full"
    "?batch=1-0-360-0-0"
    f"&max_price={MAX_PRICE}"
    "&searchPath=sfc%2Froo"
    "&lang=en&cc=us"
)
LISTING_BASE = "https://sfbay.craigslist.org/sfc/roo/d"
REFERRER = "https://sfbay.craigslist.org/"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _decode_neighborhood(location_str: str, neighborhoods: list) -> str:
    try:
        parts = location_str.split("~")[0].split(":")
        hood_idx = int(parts[2])
        if 0 < hood_idx < len(neighborhoods):
            return neighborhoods[hood_idx]
    except (IndexError, ValueError):
        pass
    return ""


def _parse_postings(data: dict) -> list[dict]:
    """
    Convert raw API items into flat listing dicts.
    Image array is optional so we scan by type markers instead of fixed indices.
    """
    items = data.get("data", {}).get("items", [])
    decode = data.get("data", {}).get("decode", {})
    min_posting_id = decode.get("minPostingId", 0)
    neighborhoods = decode.get("neighborhoods", [])

    listings = []
    for item in items:
        try:
            post_id = str(min_posting_id + item[0])
            price = item[3] if isinstance(item[3], int) else None
            location_str = item[4] if isinstance(item[4], str) else ""
            neighborhood = _decode_neighborhood(location_str, neighborhoods)

            slug = ""
            title = ""
            for el in item:
                if isinstance(el, list) and len(el) >= 2 and el[0] == 6:
                    slug = el[1]
                elif isinstance(el, str) and el and not el.startswith("1:"):
                    title = el

            if not slug or not title:
                logger.warning(f"Could not parse slug/title: {item}")
                continue

            listings.append({
                "id": post_id,
                "title": title,
                "price": price,
                "url": f"{LISTING_BASE}/{slug}/{post_id}.html",
                "description": "",
                "neighborhood": neighborhood,
                "score": None,
                "rent_control_likely": None,
                "scam_risk": None,
                "summary": None,
                "notified": False,
            })
        except Exception as e:
            logger.warning(f"Failed to parse item: {e}")
            continue

    return listings


def fetch_new_listings(is_seen_fn) -> list[dict]:
    """
    Fetch all listings from Craigslist API, return only ones not yet seen.
    No filtering — caller decides what to do with them.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(user_agent=UA).new_page()

        try:
            logger.info("Fetching Craigslist search API...")
            response = page.request.get(
                SEARCH_API, headers={"Referer": REFERRER}, timeout=20000
            )
            if response.status != 200:
                logger.error(f"Search API returned HTTP {response.status}")
                browser.close()
                return []
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch search API: {e}")
            browser.close()
            return []

        all_listings = _parse_postings(data)
        logger.info(f"API returned {len(all_listings)} total listings.")
        browser.close()

    new = [l for l in all_listings if not is_seen_fn(l["id"])]
    logger.info(f"{len(new)} new (unseen) listings.")
    return new


def fetch_description(url: str) -> str:
    """Fetch a single listing page and return the description text."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(user_agent=UA).new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            try:
                page.wait_for_selector("#postingbody", timeout=5000)
            except PlaywrightTimeout:
                pass

            el = page.query_selector("#postingbody")
            if el:
                text = el.inner_text().strip()
                text = re.sub(r"QR Code Link to This Post.*", "", text, flags=re.DOTALL).strip()
                browser.close()
                return text[:3000]

            section = page.query_selector("section.body") or page.query_selector("article")
            result = section.inner_text()[:1000] if section else page.inner_text("body")[:500]
            browser.close()
            return result
        except PlaywrightTimeout:
            logger.warning(f"Timeout fetching description: {url}")
            browser.close()
            return ""
        except Exception as e:
            logger.warning(f"Error fetching description {url}: {e}")
            browser.close()
            return ""
