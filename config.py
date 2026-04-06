import os
from dotenv import load_dotenv

load_dotenv()

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
MY_PHONE_NUMBER = os.getenv("MY_PHONE_NUMBER", "")

# Scraper settings
SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "7"))
MAX_PRICE = int(os.getenv("MAX_PRICE", "1000"))
FETCH_INTERVAL_MINUTES = int(os.getenv("FETCH_INTERVAL_MINUTES", "10"))
MAX_LLM_CALLS_PER_RUN = int(os.getenv("MAX_LLM_CALLS_PER_RUN", "10"))

# RSS Feed
RSS_URL = f"https://sfbay.craigslist.org/search/sfc/roo?format=rss&max_price={MAX_PRICE}"

# Database
DB_PATH = os.getenv("DB_PATH", "sf_rent_scraper.db")

# Logging
LOG_FILE = os.getenv("LOG_FILE", "sf_rent_scraper.log")

# Claude model
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# Validation
def validate_config():
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not TWILIO_ACCOUNT_SID:
        missing.append("TWILIO_ACCOUNT_SID")
    if not TWILIO_AUTH_TOKEN:
        missing.append("TWILIO_AUTH_TOKEN")
    if not TWILIO_FROM_NUMBER:
        missing.append("TWILIO_FROM_NUMBER")
    if not MY_PHONE_NUMBER:
        missing.append("MY_PHONE_NUMBER")
    return missing
