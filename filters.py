import re
import logging

logger = logging.getLogger(__name__)

POSITIVE_KEYWORDS = [
    "rent control",
    "rent-controlled",
    "rent controlled",
    "victorian",
    "pre-war",
    "prewar",
    "old building",
    "lease takeover",
    "taking over lease",
    "sunset",
    "richmond",
    "excelsior",
    "outer mission",
    "bayview",
    "chinatown",
    "dogpatch",
    "soma",
    "mission",
    "haight",
    "noe valley",
    "castro",
    "glen park",
    "bernal heights",
    "loft",
    "warehouse",
    "artist",
    "creative",
    "musician",
    "chill",
    "laid back",
    "easygoing",
    "easy going",
    "420 friendly",
    "420friendly",
]

NEGATIVE_KEYWORDS = [
    "parking only",
    "storage only",
    "temporary",
    "short term",
    "short-term",
    "2 weeks",
    "1 month only",
    "hotel",
    "hostel",
    "shared bed",
    "send money before viewing",
    "send deposit before",
    "i'm out of town",
    "im out of town",
    "i am out of town",
    "western union",
    "money order only",
    "wire transfer",
    "pay before you see",
    "no viewing",
    "can't show",
    "cannot show",
    "non-refundable deposit",
    "nonrefundable deposit",
    "deposit is non refundable",
]


def _normalize(text: str) -> str:
    return text.lower()


def passes_keyword_filter(title: str, description: str) -> tuple[bool, list[str]]:
    """
    Returns (passes: bool, matched_negative_keywords: list).
    A listing fails if it matches any negative keyword.
    Positive keywords are informational only — we don't require them.
    """
    combined = _normalize(f"{title} {description}")

    matched_negatives = [kw for kw in NEGATIVE_KEYWORDS if kw in combined]
    if matched_negatives:
        logger.debug(f"Listing rejected by negative keywords: {matched_negatives}")
        return False, matched_negatives

    matched_positives = [kw for kw in POSITIVE_KEYWORDS if kw in combined]
    logger.debug(f"Listing passed keyword filter. Positive matches: {matched_positives}")
    return True, []


def extract_price(text: str) -> int | None:
    """Best-effort price extraction from listing text."""
    matches = re.findall(r"\$(\d{3,4})", text)
    if matches:
        return int(matches[0])
    return None
