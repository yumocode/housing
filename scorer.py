import json
import logging
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Stage 1 — batch pre-screen (one API call for all new listings)
# Input: title + price + neighborhood only
# Output: [{id, pre_score}] — just enough to decide if worth fetching desc
# ---------------------------------------------------------------------------
BATCH_SYSTEM = """\
You are a fast pre-screener for Craigslist SF room listings for a 24-year-old \
software engineer and DJ looking for cheap long-term housing in San Francisco.

Given a list of listings (title, price, neighborhood), give each a pre_score 1-10.

Score 1-2 if the title/price clearly indicates: parking spot, storage unit, \
weekly hotel rate disguised as monthly, obvious scam, or location outside SF.
Score 3-5 if it looks like a short-term sublet, very vague, or unlikely to be \
a real long-term room.
Score 6-10 if it could plausibly be a legit long-term room worth investigating.

When in doubt, score higher — we'd rather investigate than miss a deal.

Respond with a JSON array only, no markdown:
[{"id": "123", "pre_score": 7}, ...]\
"""


def batch_prescreen(listings: list[dict]) -> dict[str, int]:
    """
    Send all listings in one call. Returns {listing_id: pre_score}.
    Listings that fail to parse default to 6 (investigate rather than miss).
    """
    if not listings:
        return {}

    lines = []
    for l in listings:
        lines.append(
            f'ID:{l["id"]} | ${l["price"]} | {l["neighborhood"]} | {l["title"]}'
        )
    user_msg = "\n".join(lines)

    try:
        response = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=BATCH_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        results = json.loads(raw)
        scores = {str(r["id"]): int(r["pre_score"]) for r in results}
        logger.info(f"Batch pre-screen: {len(scores)} listings scored in 1 call.")
        return scores
    except Exception as e:
        logger.error(f"Batch pre-screen failed: {e} — defaulting all to 6")
        return {l["id"]: 6 for l in listings}


# ---------------------------------------------------------------------------
# Stage 2 — full score (one API call per promising listing, with description)
# ---------------------------------------------------------------------------
FULL_SCORE_SYSTEM = """\
You are a housing listing analyzer for a 24-year-old software engineer and DJ \
looking for a cheap long-term room in San Francisco.

Score 1-10 based on the full listing.

Hard 1-2 (not worth investigating):
- Not a room (parking, storage, shared bed, hostel)
- Weekly pricing disguised as monthly
- Scam signals (wire transfer, out of town landlord, no viewing)
- Outside SF proper (Daly City, Oakland, etc.)

3-5 (below threshold):
- Short-term sublet under 3 months
- Very vague with no real details
- Overpriced for what's described

6-7 (borderline — skip texting):
- Decent room, average neighborhood, no strong signals either way

8-10 (text me):
- Rent control likely (pre-1979 building, Victorian, explicit RC language)
- Creative/chill roommates, musician-friendly, young professionals
- Good transit access, walkable SF neighborhood
- Strong value — good size, included utilities, or other perks
- Long-term lease

Respond in JSON only, no markdown:
{"score": 8, "rent_control_likely": true, "scam_risk": "low", \
"summary": "One line summary", "neighborhood": "Sunset"}\
"""


def score_listing(listing: dict) -> dict | None:
    """Full score using title + description. Returns None on failure."""
    title = listing.get("title", "")
    price = listing.get("price", "unknown")
    description = listing.get("description", "")[:2000]
    url = listing.get("url", "")

    user_msg = f"Title: {title}\nPrice: ${price}/month\nURL: {url}\n\nDescription:\n{description}"

    try:
        response = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=256,
            system=FULL_SCORE_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        result = json.loads(raw)

        required = {"score", "rent_control_likely", "scam_risk", "summary", "neighborhood"}
        if not required.issubset(result.keys()):
            logger.warning(f"Missing fields in response: {raw}")
            return None

        result["score"] = int(result["score"])
        logger.info(
            f"Full score '{title}': {result['score']}/10 | "
            f"scam={result['scam_risk']} | rc={result['rent_control_likely']}"
        )
        return result

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for '{title}': {e}")
        return None
    except anthropic.APIError as e:
        logger.error(f"Anthropic API error for '{title}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error scoring '{title}': {e}")
        return None
