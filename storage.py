import os
import logging
import psycopg2

log = logging.getLogger(__name__)
DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Create the seen_listings table if it doesn't exist yet."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS seen_listings (
                    url TEXT PRIMARY KEY,
                    seen_at TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()


def load_seen() -> set:
    init_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT url FROM seen_listings")
            return {row[0] for row in cur.fetchall()}


def save_seen(seen: set):
    """Insert any URLs not yet in the database."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO seen_listings (url) VALUES (%s) ON CONFLICT DO NOTHING",
                [(url,) for url in seen]
            )
        conn.commit()
