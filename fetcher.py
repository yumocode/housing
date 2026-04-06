"""
Fetcher — replaces feedparser/RSS with Craigslist's internal JSON API
via a headless Playwright browser (much harder to block than plain HTTP).

Flow:
  1. Spin up headless Chromium
  2. Call sapi.craigslist.org search endpoint → get all listings as JSON
  3. For each new listing that passes the title keyword filter, fetch the
     full listing page to grab the description body
  4. Return a list of listing dicts ready for the scorer
"""

import logging
import re
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from config import MAX_PRICE
from filters import passes_keyword_filter

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
    """
    Location string format: "area_idx:loc_idx:hood_idx~lat~lng"
    neighborhoods is a 1-indexed list from the API decode block.
    """
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
    Convert raw API items into flat listing dicts (no description yet).

    The items array uses positional encoding but the image array is optional,
    which shifts indices for listings without photos. We scan by type/marker
    instead of hardcoded positions to be resilient to both formats.
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

            # Scan for slug: list element whose first value is 6
            slug = ""
            title = ""
            for el in item:
                if isinstance(el, list) and len(el) >= 2 and el[0] == 6:
                    slug = el[1]
                elif isinstance(el, str) and el and not el.startswith("1:"):
                    title = el  # bare string = title (location_str starts with "1:")

            if not slug or not title:
                logger.warning(f"Could not parse slug/title from item: {item}")
                continue

            url = f"{LISTING_BASE}/{slug}/{post_id}.html"

            listings.append({
                "id": post_id,
                "title": title,
                "price": price,
                "url": url,
                "description": "",  # filled in later for new listings
                "neighborhood": neighborhood,
                "score": None,
                "rent_control_likely": None,
                "scam_risk": None,
                "summary": None,
                "notified": False,
            })
        except Exception as e:
            logger.warning(f"Failed to parse item: {e} — {item}")
            continue

    return listings


def _fetch_description(page, url: str) -> str:
    """Fetch a single listing page and extract the body text."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)

        # Wait for posting body to appear (up to 5s)
        try:
            page.wait_for_selector("#postingbody", timeout=5000)
        except PlaywrightTimeout:
            pass

        el = page.query_selector("#postingbody")
        if el:
            text = el.inner_text().strip()
            # Remove Craigslist's standard QR code notice
            text = re.sub(r"QR Code Link to This Post.*", "", text, flags=re.DOTALL).strip()
            return text[:3000]

        # Fallback: grab visible body text, skip nav/header noise
        section = page.query_selector("section.body") or page.query_selector("article")
        if section:
            return section.inner_text()[:1000]
        return page.inner_text("body")[:500]
    except PlaywrightTimeout:
        logger.warning(f"Timeout fetching description: {url}")
        return ""
    except Exception as e:
        logger.warning(f"Error fetching description {url}: {e}")
        return ""


def fetch_listings(is_seen_fn, max_descriptions: int = 20) -> list[dict]:
    """
    Main entry point. Returns a list of new listing dicts with descriptions
    populated for listings that passed the title-level keyword filter.

    is_seen_fn: callable(listing_id: str) -> bool
    max_descriptions: cap on individual listing page fetches per run
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=UA)
        page = context.new_page()

        # --- Step 1: fetch search results JSON ---
        try:
            logger.info(f"Fetching search API: {SEARCH_API}")
            response = page.request.get(
                SEARCH_API,
                headers={"Referer": REFERRER},
                timeout=20000,
            )
            if response.status != 200:
                logger.error(f"Search API returned {response.status}")
                browser.close()
                return []
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch search API: {e}")
            browser.close()
            return []

        all_listings = _parse_postings(data)
        logger.info(f"API returned {len(all_listings)} listings.")

        # --- Step 2: filter to new + title-passes-keywords ---
        candidates = []
        for listing in all_listings:
            if is_seen_fn(listing["id"]):
                continue
            title_passes, _ = passes_keyword_filter(listing["title"], "")
            if not title_passes:
                logger.info(f"[REJECT-TITLE] {listing['title']!r}")
                candidates.append({**listing, "score": 0, "summary": "rejected by title keyword filter", "_skip_scoring": True})
            else:
                candidates.append(listing)

        logger.info(f"{len(candidates)} new listings to process.")

        # --- Step 3: fetch descriptions for candidates that need scoring ---
        desc_count = 0
        for listing in candidates:
            if listing.get("_skip_scoring"):
                continue
            if desc_count >= max_descriptions:
                logger.warning(f"Hit description fetch limit ({max_descriptions}). Remaining deferred.")
                break
            logger.info(f"Fetching description: {listing['title']!r}")
            listing["description"] = _fetch_description(page, listing["url"])
            desc_count += 1
            time.sleep(1.5)  # polite delay between listing page fetches

        browser.close()

    return candidates
