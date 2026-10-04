import sqlite3
from contextlib import closing

from app.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "data" / "prescripts.db"


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS prescripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            mode TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'new'
        )
        """)


def save_prescript(content: str, mode: str) -> int:
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        cur = conn.execute(
            "INSERT INTO prescripts (content, mode) VALUES (?, ?)",
            (content, mode)
        )
        return cur.lastrowid


def get_recent_prescripts(limit: int = 10) -> list[str]:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.execute(
            """
            SELECT content FROM prescripts
            WHERE content != '静候下一则指令'
            ORDER BY id DESC LIMIT ?
            """,
            (limit,)
        )
        rows = cur.fetchall()
    return [row[0] for row in rows][::-1]
