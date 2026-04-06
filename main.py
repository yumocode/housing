#!/usr/bin/env python3
"""
sf-rent-scraper — Main entry point.
Fetches Craigslist SF rooms/shares via headless browser + internal JSON API,
filters, scores with Claude Haiku, and texts good deals via Twilio.
"""

import logging
import random
import sys
import time
from datetime import datetime

import config
from database import init_db, is_seen, save_listing, mark_notified
from fetcher import fetch_listings
from filters import passes_keyword_filter
from scorer import score_listing
from notifier import send_sms


def setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


logger = logging.getLogger("main")


def run():
    setup_logging()

    logger.info("=" * 60)
    logger.info(f"sf-rent-scraper starting at {datetime.utcnow().isoformat()}Z")

    missing = config.validate_config()
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        sys.exit(1)

    # Random jitter to avoid predictable timing
    jitter = random.uniform(0, 30)
    logger.info(f"Jitter sleep: {jitter:.1f}s")
    time.sleep(jitter)

    init_db()

    # Fetch + dedupe + title-filter + description fetch all happen in fetcher
    candidates = fetch_listings(is_seen_fn=is_seen, max_descriptions=config.MAX_LLM_CALLS_PER_RUN)

    if not candidates:
        logger.info("No new candidates this run.")
        sys.exit(0)

    llm_calls = 0
    notified_count = 0

    for listing in candidates:
        try:
            # Listings rejected at title stage are pre-marked, just save and skip
            if listing.get("_skip_scoring"):
                save_listing({k: v for k, v in listing.items() if k != "_skip_scoring"})
                continue

            # Stage 1: full keyword filter (title + description now available)
            passes, rejected_by = passes_keyword_filter(
                listing["title"], listing["description"]
            )
            if not passes:
                logger.info(f"[REJECT-KW] {listing['title']!r} — {rejected_by}")
                save_listing({**listing, "score": 0, "summary": "rejected by keyword filter"})
                continue

            # Stage 2: LLM scoring
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
            try:
                save_listing({**listing, "score": -1, "summary": f"error: {e}"})
            except Exception:
                pass
            continue

    logger.info(f"Run complete. LLM calls: {llm_calls}, texts sent: {notified_count}.")


if __name__ == "__main__":
    run()
