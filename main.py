#!/usr/bin/env python3
"""
sf-rent-scraper — Main entry point.

Pipeline:
  1. Fetch all new Craigslist listings (title + price + neighborhood)
  2. Batch pre-screen with one Haiku call → quick 1-10 score on titles alone
  3. For listings scoring >= PRE_SCREEN_THRESHOLD: fetch full description
  4. Full Haiku score on title + description
  5. Text via Twilio if full score >= SCORE_THRESHOLD
"""

import logging
import random
import sys
import time
from datetime import datetime

import config
from database import init_db, is_seen, save_listing, mark_notified, get_daily_llm_calls, increment_llm_calls
from fetcher import fetch_new_listings, fetch_description
from scorer import batch_prescreen, score_listing
from notifier import send_sms

PRE_SCREEN_THRESHOLD = 5  # batch pre-screen min score to fetch description


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
        logger.error(f"Missing required env vars: {missing}")
        sys.exit(1)

    jitter = random.uniform(0, 30)
    logger.info(f"Jitter sleep: {jitter:.1f}s")
    time.sleep(jitter)

    init_db()

    # --- Step 1: fetch new listings (title + price + neighborhood only) ---
    new_listings = fetch_new_listings(is_seen_fn=is_seen)
    if not new_listings:
        logger.info("No new listings this run.")
        sys.exit(0)

    # --- Daily budget check ---
    calls_today = get_daily_llm_calls()
    if calls_today >= config.MAX_LLM_CALLS_PER_DAY:
        logger.error(
            f"Daily LLM cap reached ({calls_today}/{config.MAX_LLM_CALLS_PER_DAY}). "
            "Skipping this run. Check for bugs or raise MAX_LLM_CALLS_PER_DAY."
        )
        send_sms(
            {"title": "RATE LIMIT HIT", "price": 0, "url": "", "neighborhood": ""},
            {"score": 0, "rent_control_likely": False, "scam_risk": "n/a",
             "summary": f"Daily LLM cap hit: {calls_today} calls today. Check logs.",
             "neighborhood": ""},
        )
        sys.exit(0)

    # --- Step 2: batch pre-screen (1 Haiku call for all new listings) ---
    pre_scores = batch_prescreen(new_listings)
    increment_llm_calls(1)

    finalists = []
    for listing in new_listings:
        pre_score = pre_scores.get(listing["id"], 6)
        listing["_pre_score"] = pre_score
        if pre_score <= PRE_SCREEN_THRESHOLD:
            logger.info(f"[PRE-REJECT {pre_score}/10] {listing['title']!r}")
            save_listing({**listing, "score": pre_score, "summary": f"pre-screen score {pre_score}/10"})
        else:
            logger.info(f"[PRE-PASS {pre_score}/10] {listing['title']!r}")
            finalists.append(listing)

    # Cap finalists at MAX_LLM_CALLS_PER_RUN to avoid runaway on first run
    if len(finalists) > config.MAX_LLM_CALLS_PER_RUN:
        logger.info(f"Capping finalists at {config.MAX_LLM_CALLS_PER_RUN} (had {len(finalists)}). Rest deferred.")
        finalists = finalists[:config.MAX_LLM_CALLS_PER_RUN]

    logger.info(f"{len(finalists)} listings passed pre-screen, fetching descriptions.")

    # --- Step 3: fetch descriptions for finalists only ---
    for listing in finalists:
        logger.info(f"Fetching description: {listing['url']}")
        listing["description"] = fetch_description(listing["url"])
        time.sleep(1.5)

    # --- Step 4 & 5: full score + notify ---
    llm_calls = 0
    notified_count = 0

    for listing in finalists:
        if llm_calls >= config.MAX_LLM_CALLS_PER_RUN:
            logger.warning(f"Hit LLM limit ({config.MAX_LLM_CALLS_PER_RUN}). Remaining deferred.")
            break

        try:
            # Re-check daily cap before each full score call
            if get_daily_llm_calls() >= config.MAX_LLM_CALLS_PER_DAY:
                logger.warning("Daily LLM cap hit mid-run. Stopping full scoring.")
                break

            score_result = score_listing(listing)
            llm_calls += 1
            increment_llm_calls(1)

            if score_result is None:
                save_listing({**listing, "score": -1, "summary": "full scoring failed"})
                continue

            listing.update({
                "score": score_result["score"],
                "rent_control_likely": score_result["rent_control_likely"],
                "scam_risk": score_result["scam_risk"],
                "summary": score_result["summary"],
                "neighborhood": score_result.get("neighborhood") or listing["neighborhood"],
            })
            save_listing(listing)

            if score_result["score"] >= config.SCORE_THRESHOLD:
                logger.info(f"[HIT {score_result['score']}/10] {listing['title']!r} — texting.")
                if send_sms(listing, score_result):
                    mark_notified(listing["id"])
                    notified_count += 1
            else:
                logger.info(f"[LOW {score_result['score']}/10] {listing['title']!r}")

        except Exception as e:
            logger.error(f"Error processing {listing.get('id')}: {e}", exc_info=True)
            try:
                save_listing({**listing, "score": -1, "summary": f"error: {e}"})
            except Exception:
                pass

    logger.info(
        f"Done. Pre-screen: 1 call. Full scores: {llm_calls}. Texts sent: {notified_count}."
    )


if __name__ == "__main__":
    run()
