import logging
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
    MY_PHONE_NUMBER,
)

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    return _client


def format_sms(listing: dict, score_result: dict) -> str:
    score = score_result.get("score", "?")
    summary = score_result.get("summary", listing.get("title", ""))
    price = listing.get("price", "?")
    neighborhood = score_result.get("neighborhood", listing.get("neighborhood", "SF"))
    rc = "likely" if score_result.get("rent_control_likely") else "unlikely"
    url = listing.get("url", "")

    return (
        f"NEW DEAL: {score}/10\n"
        f"{summary}\n"
        f"${price}/mo — {neighborhood}\n"
        f"Rent control: {rc}\n"
        f"{url}"
    )


def send_sms(listing: dict, score_result: dict) -> bool:
    """Send SMS via Twilio. Returns True on success."""
    body = format_sms(listing, score_result)
    try:
        client = _get_client()
        message = client.messages.create(
            body=body,
            from_=TWILIO_FROM_NUMBER,
            to=MY_PHONE_NUMBER,
        )
        logger.info(f"SMS sent (SID: {message.sid}) for listing {listing.get('id')}")
        return True
    except TwilioRestException as e:
        logger.error(f"Twilio error sending SMS for {listing.get('id')}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending SMS for {listing.get('id')}: {e}")
        return False
