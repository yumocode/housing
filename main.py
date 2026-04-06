#!/usr/bin/env python3
"""
sf-rent-scraper — Main entry point.
Fetches Craigslist SF rooms/shares RSS, filters, scores with Claude Haiku,
and texts good deals via Twilio.
"""

import logging
import random
import re
import sys
import time
from datetime import datetime

import feedparser
import requests

import config
from database import init_db, is_seen, save_listing, mark_notified
from filters import passes_keyword_filter, extract_price
from scorer import score_listing
from notifier import send_sms

# ---------------------------------------------------------------------------
# Logging setup — write to both file and stdout so cron captures it too
# ---------------------------------------------------------------------------
def setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# RSS helpers
# ---------------------------------------------------------------------------
def fetch_feed(url: str, retry: bool = True) -> feedparser.FeedParserDict | None:
    """Fetch and parse the RSS feed. Retries once on failure."""
    try:
        logger.info(f"Fetching RSS feed: {url}")
        # feedparser handles redirect/gzip automatically, but we set a UA
        feed = feedparser.parse(
            url,
            request_headers={"User-Agent": "sf-rent-scraper/1.0 (+github)"},
        )
        if feed.bozo and not feed.entries:
            raise ValueError(f"feedparser bozo error: {feed.bozo_exception}")
        logger.info(f"Fetched {len(feed.entries)} entries.")
        return feed
    except Exception as e:
        logger.error(f"Failed to fetch RSS feed: {e}")
        if retry:
            logger.info("Retrying after 60 seconds...")
            time.sleep(60)
            return fetch_feed(url, retry=False)
        logger.error("Skipping this run.")
        return None


def parse_listing(entry) -> dict:
    """Convert a feedparser entry into a flat dict."""
    # Craigslist post IDs live in the <id> tag or can be parsed from the URL
    url = entry.get("link", "")
    post_id = entry.get("id", url)

    # Try to pull the numeric CL post ID from the URL for deduplication
    match = re.search(r"/(\d{10,})\.html", url)
    if match:
        post_id = match.group(1)

    title = entry.get("title", "")
    description = entry.get("summary", "")

    # Strip HTML tags from description
    description = re.sub(r"<[^>]+>", " ", description).strip()

    # Price: try the title first ($800), then description
    price_str = f"{title} {description}"
    price = extract_price(price_str)

    # Rough neighborhood from title
    neighborhood = ""
    for hood in [
        "sunset", "richmond", "excelsior", "outer mission", "bayview",
        "chinatown", "dogpatch", "soma", "mission", "haight", "noe valley",
        "castro", "glen park", "bernal heights", "tenderloin", "pacific heights",
        "marina", "north beach", "inner sunset", "outer sunset",
    ]:
        if hood in title.lower() or hood in description.lower():
            neighborhood = hood.title()
            break

    return {
        "id": post_id,
        "title": title,
        "price": price,
        "url": url,
        "description": description,
        "neighborhood": neighborhood,
        "score": None,
        "rent_control_likely": None,
        "scam_risk": None,
        "summary": None,
        "notified": False,
    }


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------
def run():
    setup_logging()

    logger.info("=" * 60)
    logger.info(f"sf-rent-scraper starting at {datetime.utcnow().isoformat()}Z")

    # Validate config
    missing = config.validate_config()
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        sys.exit(1)

    # Random jitter to avoid predictable request timing
    jitter = random.uniform(0, 30)
    logger.info(f"Jitter sleep: {jitter:.1f}s")
    time.sleep(jitter)

    # Init database
    init_db()

    # Fetch RSS
    feed = fetch_feed(config.RSS_URL)
    if feed is None:
        logger.warning("No feed returned. Exiting.")
        sys.exit(0)

    if not feed.entries:
        logger.info("No listings in feed this run.")
        sys.exit(0)

    new_listings = []
    for entry in feed.entries:
        try:
            listing = parse_listing(entry)
            if is_seen(listing["id"]):
                logger.debug(f"Already seen: {listing['id']}")
                continue
            new_listings.append(listing)
        except Exception as e:
            logger.error(f"Error parsing entry: {e}")
            continue

    logger.info(f"{len(new_listings)} new listings to process.")

    llm_calls = 0
    notified_count = 0

    for listing in new_listings:
        try:
            # Stage 1: keyword filter
            passes, rejected_by = passes_keyword_filter(
                listing["title"], listing["description"]
            )
            if not passes:
                logger.info(
                    f"[REJECT-KW] {listing['title']!r} — {rejected_by}"
                )
                # Save as seen so we don't re-evaluate next run
                save_listing({**listing, "score": 0, "summary": "rejected by keyword filter"})
                continue

            # Stage 2: LLM scoring (rate-limited)
            if llm_calls >= config.MAX_LLM_CALLS_PER_RUN:
                logger.warning(
                    f"Hit LLM call limit ({config.MAX_LLM_CALLS_PER_RUN}). "
                    "Remaining listings deferred to next run."
                )
                break

            logger.info(f"[SCORING] {listing['title']!r} @ ${listing['price']}")
            score_result = score_listing(listing)
            llm_calls += 1

            if score_result is None:
                logger.warning(f"Scoring failed for {listing['id']}; saving as seen.")
                save_listing({**listing, "score": -1, "summary": "scoring failed"})
                continue

            listing.update({
                "score": score_result["score"],
                "rent_control_likely": score_result["rent_control_likely"],
                "scam_risk": score_result["scam_risk"],
                "summary": score_result["summary"],
                "neighborhood": score_result.get("neighborhood") or listing["neighborhood"],
            })

            save_listing(listing)

            # Stage 3: notify if score meets threshold
            if score_result["score"] >= config.SCORE_THRESHOLD:
                logger.info(
                    f"[HIT] {listing['title']!r} scored {score_result['score']}/10 — texting."
                )
                sent = send_sms(listing, score_result)
                if sent:
                    mark_notified(listing["id"])
                    notified_count += 1
            else:
                logger.info(
                    f"[LOW] {listing['title']!r} scored {score_result['score']}/10 — below threshold."
                )

        except Exception as e:
            logger.error(
                f"Unhandled error processing listing {listing.get('id', '?')}: {e}",
                exc_info=True,
            )
            # Try to at least mark it seen so we don't loop on a bad listing
            try:
                save_listing({**listing, "score": -1, "summary": f"error: {e}"})
            except Exception:
                pass
            continue

    logger.info(
        f"Run complete. LLM calls: {llm_calls}, texts sent: {notified_count}."
    )


if __name__ == "__main__":
    run()
