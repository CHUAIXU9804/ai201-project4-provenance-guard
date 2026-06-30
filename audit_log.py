import sqlite3
from datetime import datetime, timezone

DB_PATH = "audit_log.db"

# Columns written for every audit entry. Order matters for the INSERT below.
# Submission rows fill the score/attribution columns; appeal rows fill the
# appeal_* columns. event_type distinguishes the two.
COLUMNS = [
    "content_id",
    "creator_id",
    "timestamp",
    "event_type",
    "attribution",
    "combined_confidence",
    "llm_score",
    "sh_score",
    "appeal_classification",
    "appeal_reason",
    "status",
]

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                content_id TEXT,
                creator_id TEXT,
                timestamp  TEXT,
                event_type TEXT,
                attribution TEXT,
                combined_confidence REAL,
                llm_score REAL,
                sh_score REAL,
                appeal_classification TEXT,
                appeal_reason TEXT,
                status TEXT
            )
        """)
        # Idempotent migrations for pre-existing tables.
        existing = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
        # Rename the old `confidence` column to `combined_confidence`.
        if "confidence" in existing and "combined_confidence" not in existing:
            conn.execute("ALTER TABLE audit_log RENAME COLUMN confidence TO combined_confidence")
            existing.discard("confidence")
            existing.add("combined_confidence")
        # Add columns missing from a pre-existing table (col -> type).
        added = {
            "llm_score": "REAL",
            "sh_score": "REAL",
            "event_type": "TEXT",
            "appeal_classification": "TEXT",
            "appeal_reason": "TEXT",
        }
        for col, col_type in added.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE audit_log ADD COLUMN {col} {col_type}")

def log_event(entry):
    # Pull only known columns; missing keys default to NULL so partial
    # entries (e.g. appeals) don't fail on absent bind parameters.
    row = {col: entry.get(col) for col in COLUMNS}
    row["timestamp"] = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        placeholders = ", ".join(f":{col}" for col in COLUMNS)
        conn.execute(
            f"INSERT INTO audit_log ({', '.join(COLUMNS)}) VALUES ({placeholders})",
            row,
        )

def read_log(limit=20):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]

def get_submission(content_id):
    """Return the original classification row for a content_id, or None."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM audit_log WHERE content_id = ? AND status = 'classified' "
            "ORDER BY timestamp ASC LIMIT 1",
            (content_id,),
        ).fetchone()
    return dict(row) if row else None