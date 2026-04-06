import sqlite3
import logging
from datetime import datetime, date
from config import DB_PATH

logger = logging.getLogger(__name__)

CREATE_LISTINGS_SQL = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    title TEXT,
    price INTEGER,
    url TEXT,
    description TEXT,
    neighborhood TEXT,
    score INTEGER,
    rent_control_likely BOOLEAN,
    scam_risk TEXT,
    summary TEXT,
    notified BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_USAGE_SQL = """
CREATE TABLE IF NOT EXISTS daily_usage (
    day TEXT PRIMARY KEY,   -- YYYY-MM-DD
    llm_calls INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute(CREATE_LISTINGS_SQL)
        conn.execute(CREATE_USAGE_SQL)
        conn.commit()
    logger.info("Database initialized.")


def is_seen(listing_id: str) -> bool:
    with get_connection() as conn:
        return conn.execute(
            "SELECT 1 FROM listings WHERE id = ?", (listing_id,)
        ).fetchone() is not None


def save_listing(listing: dict):
    sql = """
    INSERT OR IGNORE INTO listings
        (id, title, price, url, description, neighborhood, score,
         rent_control_likely, scam_risk, summary, notified, created_at)
    VALUES
        (:id, :title, :price, :url, :description, :neighborhood, :score,
         :rent_control_likely, :scam_risk, :summary, :notified, :created_at)
    """
    listing.setdefault("created_at", datetime.utcnow().isoformat())
    with get_connection() as conn:
        conn.execute(sql, listing)
        conn.commit()


def mark_notified(listing_id: str):
    with get_connection() as conn:
        conn.execute("UPDATE listings SET notified = 1 WHERE id = ?", (listing_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Daily LLM usage tracking
# ---------------------------------------------------------------------------

def get_daily_llm_calls(today: str | None = None) -> int:
    today = today or date.today().isoformat()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT llm_calls FROM daily_usage WHERE day = ?", (today,)
        ).fetchone()
        return row["llm_calls"] if row else 0


def increment_llm_calls(n: int = 1, today: str | None = None):
    today = today or date.today().isoformat()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO daily_usage (day, llm_calls, last_updated)
            VALUES (?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
                llm_calls = llm_calls + excluded.llm_calls,
                last_updated = excluded.last_updated
        """, (today, n, datetime.utcnow().isoformat()))
        conn.commit()
