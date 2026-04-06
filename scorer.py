import json
import logging
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a housing listing analyzer for a 24-year-old software engineer and DJ looking for a cheap room in San Francisco. Score this Craigslist listing on a scale of 1-10.

Consider:
- Rent control likelihood (building age, neighborhood, language clues)
- Scam probability (too good to be true, vague details, asks for money upfront)
- Vibe fit (creative/chill roommates, musician-friendly, young professionals)
- Value (price vs what you get — size, location, amenities)
- Location quality (walkable, transit access, safe-ish neighborhood)

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
