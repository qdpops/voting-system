import os
import sqlite3

DB_NAME = os.getenv("DB_PATH", "voting.db")

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_name TEXT NOT NULL,
                oto_number TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS votings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ends_at TIMESTAMP NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voting_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                choice TEXT CHECK(choice IN ('for', 'against', 'abstained')),
                voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(voting_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voting_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voting_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
                used BOOLEAN DEFAULT 0,
                UNIQUE(voting_id, user_id)
            )
        """)
        _migrate(conn)

def _migrate(conn):
    """Migrate from old schema where users had token/voted columns."""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "token" in columns or "voted" in columns:
        conn.execute("ALTER TABLE users RENAME TO _users_bak")
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_name TEXT NOT NULL,
                oto_number TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO users (id, org_name, oto_number, email) "
            "SELECT id, org_name, oto_number, email FROM _users_bak"
        )
        conn.execute("DROP TABLE _users_bak")

    # Add launched column to votings if missing
    v_cols = [row[1] for row in conn.execute("PRAGMA table_info(votings)").fetchall()]
    if "launched" not in v_cols:
        conn.execute("ALTER TABLE votings ADD COLUMN launched BOOLEAN DEFAULT 0")

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn
