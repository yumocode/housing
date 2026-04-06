import json
import logging
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a housing listing analyzer for a 24-year-old software engineer and DJ looking for a cheap room in San Francisco. Score this Craigslist listing on a scale of 1-10.

Score 1-2 (immediate reject) if ANY of these are true:
- It's a parking spot, storage unit, or not a room
- Weekly pricing disguised as monthly (e.g. "$350/week" posted as "$350")
- Obvious scam signals (asks for wire transfer, money order, sender is "out of town", no viewing allowed)
- Hotel, hostel, or shared bed situation
- Outside San Francisco proper (Daly City, Oakland, etc. are not SF)

Score 3-5 (below threshold, skip) if:
- Short-term sublet under 3 months
- Extremely vague listing with no real details
- High scam risk but not certain
- Overpriced for what's described

Score 6-7 (borderline) if:
- Decent room but no rent control signals, average neighborhood
- Some red flags but could be legit

Score 8-10 (text me) if:
- Rent control likely (pre-1979 building, Victorian, rent control language)
- Good neighborhood with transit access
- Chill/creative roommates, musician-friendly, or young professionals
- Strong value for SF at this price
- Long-term lease available

Respond in JSON only, no markdown, no preamble:
{"score": 8, "rent_control_likely": true, "scam_risk": "low", "summary": "One line summary of the listing", "neighborhood": "Sunset"}\
"""

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def score_listing(listing: dict) -> dict | None:
    """
    Send a listing to Claude Haiku for scoring.
    Returns a dict with score, rent_control_likely, scam_risk, summary, neighborhood.
    Returns None on failure.
    """
    title = listing.get("title", "")
    price = listing.get("price", "unknown")
    description = listing.get("description", "")[:2000]  # cap to save tokens
    url = listing.get("url", "")

    user_message = f"""Title: {title}
Price: ${price}/month
URL: {url}

Description:
{description}"""

    try:
        client = _get_client()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()
        result = json.loads(raw)

        # Validate required fields
        required = {"score", "rent_control_likely", "scam_risk", "summary", "neighborhood"}
        if not required.issubset(result.keys()):
            logger.warning(f"Haiku response missing fields: {raw}")
            return None

        result["score"] = int(result["score"])
        logger.info(
            f"Scored listing '{title}': {result['score']}/10 | "
            f"scam={result['scam_risk']} | rc={result['rent_control_likely']}"
        )
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Haiku JSON for '{title}': {e}")
        return None
    except anthropic.APIError as e:
        logger.error(f"Anthropic API error scoring '{title}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error scoring '{title}': {e}")
        return None
