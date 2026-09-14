"""Local SQLite storage.

The public function signatures are identical to the previous Supabase layer,
so nothing outside this file and main.py changed.

Two things matter operationally:

1. DB_PATH must live on a mounted Railway Volume. The container filesystem is
   ephemeral and a redeploy wipes anything not on the volume.
2. WAL mode is on, so reads never block the single writer. That is what makes
   the 4 PM rush fast: no network round trip per query.
"""

import datetime as dt
import json
import logging
import os
from typing import Any, Optional

import aiosqlite

import config

log = logging.getLogger(__name__)

_conn: Optional[aiosqlite.Connection] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    telegram_id   INTEGER PRIMARY KEY,
    state         TEXT NOT NULL DEFAULT 'IDLE',
    draft         TEXT NOT NULL DEFAULT '{}',
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
    telegram_id     INTEGER PRIMARY KEY,
    name            TEXT,
    roll_no         TEXT UNIQUE,
    exam_date       TEXT,
    shift           INTEGER,
    centre          TEXT,
    category        TEXT,
    gk_attempted    INTEGER,
    gk_marks        REAL,
    en_attempted    INTEGER,
    en_marks        REAL,
    total_marks     REAL,
    status          TEXT NOT NULL DEFAULT 'registered',
    key_version     TEXT DEFAULT 'provisional',
    referred_by     INTEGER,
    referral_count  INTEGER NOT NULL DEFAULT 0,
    is_flagged      INTEGER NOT NULL DEFAULT 0,
    qualified       INTEGER,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_candidates_shift ON candidates (exam_date, shift);
CREATE INDEX IF NOT EXISTS idx_candidates_category ON candidates (category);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates (status);

CREATE TABLE IF NOT EXISTS submission_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id   INTEGER NOT NULL,
    gk_marks      REAL,
    en_marks      REAL,
    total_marks   REAL,
    key_version   TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS answer_keys (
    exam_date     TEXT NOT NULL,
    shift         INTEGER NOT NULL,
    file_id       TEXT NOT NULL,
    file_name     TEXT,
    storage_path  TEXT,
    uploaded_by   INTEGER,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (exam_date, shift)
);

CREATE TABLE IF NOT EXISTS bot_config (
    key           TEXT PRIMARY KEY,
    value         TEXT,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broadcast_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id   INTEGER NOT NULL,
    body          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    attempts      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_broadcast_pending ON broadcast_queue (status, id);
"""

TABLES = [
    "sessions",
    "candidates",
    "submission_history",
    "answer_keys",
    "bot_config",
    "broadcast_queue",
]


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


async def init() -> None:
    """Open the connection and create the schema. Call once at startup."""
    global _conn

    directory = os.path.dirname(config.DB_PATH)
    if directory:
        if not os.path.isdir(directory):
            log.warning(
                "Directory %s does not exist. If this is Railway, the volume is "
                "NOT mounted and all data will be lost on redeploy.",
                directory,
            )
        os.makedirs(directory, exist_ok=True)

    _conn = await aiosqlite.connect(config.DB_PATH)
    _conn.row_factory = aiosqlite.Row
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA synchronous=NORMAL")
    await _conn.execute("PRAGMA foreign_keys=ON")
    await _conn.executescript(SCHEMA)
    await _conn.commit()

    for key, value in [
        ("submission_open", False),
        ("report_message_id", None),
        ("report_edit_count", 0),
        ("report_auto_update", True),
        ("frozen_difficulty", {}),
    ]:
        existing = await _conn.execute_fetchall(
            "SELECT 1 FROM bot_config WHERE key = ?", (key,)
        )
        if not existing:
            await set_config(key, value)

    log.info("SQLite ready at %s", config.DB_PATH)


def conn() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("db.init() was never called")
    return _conn


async def close() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


async def _fetchone(sql: str, args: tuple = ()) -> Optional[dict]:
    async with conn().execute(sql, args) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def _fetchall(sql: str, args: tuple = ()) -> list[dict]:
    async with conn().execute(sql, args) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def _exec(sql: str, args: tuple = ()) -> None:
    await conn().execute(sql, args)
    await conn().commit()


# ---------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------
async def get_session(telegram_id: int) -> dict:
    row = await _fetchone(
        "SELECT state, draft FROM sessions WHERE telegram_id = ?", (telegram_id,)
    )
    if not row:
        return {"state": "IDLE", "draft": {}}
    return {"state": row["state"], "draft": json.loads(row["draft"] or "{}")}


async def set_session(telegram_id: int, state: str, draft: dict | None = None) -> None:
    await _exec(
        """
        INSERT INTO sessions (telegram_id, state, draft, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            state = excluded.state,
            draft = excluded.draft,
            updated_at = excluded.updated_at
        """,
        (telegram_id, state, json.dumps(draft or {}), _now()),
    )


async def clear_session(telegram_id: int) -> None:
    await set_session(telegram_id, "IDLE", {})


# ---------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------
async def get_candidate(telegram_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM candidates WHERE telegram_id = ?", (telegram_id,)
    )


async def roll_taken_by_other(roll_no: str, telegram_id: int) -> bool:
    row = await _fetchone(
        "SELECT telegram_id FROM candidates WHERE roll_no = ?", (roll_no,)
    )
    return bool(row) and row["telegram_id"] != telegram_id


async def upsert_candidate(payload: dict) -> dict:
    """Insert, or update only the columns present in payload."""
    telegram_id = payload["telegram_id"]
    fields = {k: v for k, v in payload.items() if k != "telegram_id"}
    now = _now()

    columns = ["telegram_id"] + list(fields.keys()) + ["created_at", "updated_at"]
    values = [telegram_id] + list(fields.values()) + [now, now]
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{k} = excluded.{k}" for k in fields)
    updates = f"{updates}, updated_at = excluded.updated_at" if updates else "updated_at = excluded.updated_at"

    await _exec(
        f"""
        INSERT INTO candidates ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(telegram_id) DO UPDATE SET {updates}
        """,
        tuple(values),
    )
    return await get_candidate(telegram_id) or {}


async def delete_candidate(telegram_id: int) -> None:
    await _exec("DELETE FROM candidates WHERE telegram_id = ?", (telegram_id,))
    await _exec("DELETE FROM sessions WHERE telegram_id = ?", (telegram_id,))
    await _exec("DELETE FROM submission_history WHERE telegram_id = ?", (telegram_id,))


async def add_history(row: dict) -> None:
    await _exec(
        """
        INSERT INTO submission_history
            (telegram_id, gk_marks, en_marks, total_marks, key_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            row["telegram_id"],
            row.get("gk_marks"),
            row.get("en_marks"),
            row.get("total_marks"),
            row.get("key_version"),
            _now(),
        ),
    )


async def bump_referral(telegram_id: int) -> None:
    await _exec(
        "UPDATE candidates SET referral_count = referral_count + 1 "
        "WHERE telegram_id = ?",
        (telegram_id,),
    )


# ---------------------------------------------------------------
# Bulk reads for analytics
# ---------------------------------------------------------------
async def all_submissions() -> list[dict]:
    return await _fetchall(
        """
        SELECT telegram_id, name, roll_no, exam_date, shift, centre, category,
               gk_marks, en_marks, total_marks, gk_attempted, en_attempted,
               is_flagged, created_at
        FROM candidates
        WHERE status = 'submitted' AND is_flagged = 0
        """
    )


async def count_where(**filters) -> int:
    if not filters:
        row = await _fetchone("SELECT COUNT(*) AS n FROM candidates")
        return row["n"] if row else 0
    clause = " AND ".join(f"{k} = ?" for k in filters)
    row = await _fetchone(
        f"SELECT COUNT(*) AS n FROM candidates WHERE {clause}",
        tuple(filters.values()),
    )
    return row["n"] if row else 0


async def count_registered_today() -> int:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat()
    row = await _fetchone(
        "SELECT COUNT(*) AS n FROM candidates WHERE created_at >= ?", (since,)
    )
    return row["n"] if row else 0


async def flagged_rows() -> list[dict]:
    return await _fetchall(
        "SELECT telegram_id, name, roll_no, exam_date, shift, total_marks "
        "FROM candidates WHERE is_flagged = 1"
    )


async def set_flag(telegram_id: int, flagged: bool) -> None:
    await _exec(
        "UPDATE candidates SET is_flagged = ?, updated_at = ? WHERE telegram_id = ?",
        (1 if flagged else 0, _now(), telegram_id),
    )


async def registered_telegram_ids() -> list[int]:
    rows = await _fetchall("SELECT telegram_id FROM candidates")
    return [r["telegram_id"] for r in rows]


# ---------------------------------------------------------------
# Answer keys
# ---------------------------------------------------------------
async def save_answer_key(row: dict) -> None:
    await _exec(
        """
        INSERT INTO answer_keys
            (exam_date, shift, file_id, file_name, storage_path, uploaded_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(exam_date, shift) DO UPDATE SET
            file_id = excluded.file_id,
            file_name = excluded.file_name,
            uploaded_by = excluded.uploaded_by,
            created_at = excluded.created_at
        """,
        (
            row["exam_date"],
            row["shift"],
            row["file_id"],
            row.get("file_name"),
            row.get("storage_path"),
            row.get("uploaded_by"),
            _now(),
        ),
    )


async def answer_key_slots() -> dict:
    rows = await _fetchall("SELECT * FROM answer_keys")
    return {(r["exam_date"], r["shift"]): r for r in rows}


# ---------------------------------------------------------------
# Config
# ---------------------------------------------------------------
async def get_config(key: str, default: Any = None) -> Any:
    row = await _fetchone("SELECT value FROM bot_config WHERE key = ?", (key,))
    if not row or row["value"] is None:
        return default
    try:
        value = json.loads(row["value"])
    except (TypeError, ValueError):
        return default
    return default if value is None else value


async def set_config(key: str, value: Any) -> None:
    await _exec(
        """
        INSERT INTO bot_config (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, json.dumps(value), _now()),
    )


# ---------------------------------------------------------------
# Broadcast queue
# ---------------------------------------------------------------
async def queue_broadcast(telegram_ids: list[int], body: str) -> int:
    now = _now()
    await conn().executemany(
        "INSERT INTO broadcast_queue (telegram_id, body, created_at) VALUES (?, ?, ?)",
        [(t, body, now) for t in telegram_ids],
    )
    await conn().commit()
    return len(telegram_ids)


async def take_broadcast_batch(limit: int) -> list[dict]:
    return await _fetchall(
        "SELECT * FROM broadcast_queue WHERE status = 'pending' ORDER BY id LIMIT ?",
        (limit,),
    )


async def mark_broadcast(row_id: int, status: str) -> None:
    await _exec(
        "UPDATE broadcast_queue SET status = ?, attempts = attempts + 1 WHERE id = ?",
        (status, row_id),
    )


async def broadcast_pending_count() -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS n FROM broadcast_queue WHERE status = 'pending'"
    )
    return row["n"] if row else 0


# ---------------------------------------------------------------
# Backup support
# ---------------------------------------------------------------
async def table_counts(path: str | None = None) -> dict[str, int]:
    """Row counts, either for the live DB or for a candidate restore file."""
    if path is None:
        out = {}
        for table in TABLES:
            row = await _fetchone(f"SELECT COUNT(*) AS n FROM {table}")
            out[table] = row["n"] if row else 0
        return out

    out = {}
    async with aiosqlite.connect(path) as other:
        for table in TABLES:
            try:
                async with other.execute(f"SELECT COUNT(*) FROM {table}") as cur:
                    row = await cur.fetchone()
                out[table] = row[0] if row else 0
            except Exception:
                out[table] = -1  # table missing, schema mismatch
    return out


async def checkpoint() -> None:
    """Fold the WAL back into the main file before a snapshot."""
    await conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    await conn().commit()
