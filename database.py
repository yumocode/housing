import sqlite3
import logging
from datetime import datetime
from config import DB_PATH

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
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


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
    logger.info("Database initialized.")


def is_seen(listing_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM listings WHERE id = ?", (listing_id,)
        ).fetchone()
        return row is not None


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
    logger.debug(f"Saved listing {listing['id']} to DB.")


def mark_notified(listing_id: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE listings SET notified = 1 WHERE id = ?", (listing_id,)
        )
        conn.commit()
