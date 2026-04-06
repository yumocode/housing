import re
import logging

logger = logging.getLogger(__name__)

# Only reject listings that are provably NOT a room for rent.
# Everything else goes to Haiku — let the LLM decide.
# Keep this list short and unambiguous to avoid missing real deals.
NEGATIVE_KEYWORDS = [
    # Definitely not a room
    "parking only",
    "parking space",
    "storage unit",
    "storage only",
    # Scam giveaways (not subjective — these phrases don't appear in legit posts)
    "western union",
    "wire transfer",
    "money order only",
    "send money before",
    "i'm out of town",
    "im out of town",
    "i am out of town",
    # Weekly hotel / hostel / shared bed (per-week pricing at <$1k is never a real apt)
    "price is weekly",
    "per week",
    "shared bed",
    "hostel",
]


def passes_keyword_filter(title: str, description: str) -> tuple[bool, list[str]]:
    """
    Hard-reject only listings that are provably not a real room.
    Returns (passes, list_of_matched_negative_keywords).
    """
    combined = f"{title} {description}".lower()
    matched = [kw for kw in NEGATIVE_KEYWORDS if kw in combined]
    if matched:
        logger.debug(f"Keyword reject: {matched}")
        return False, matched
    return True, []


def extract_price(text: str) -> int | None:
    matches = re.findall(r"\$(\d{3,4})", text)
    if matches:
        return int(matches[0])
    return None
