"""Backup and restore.

A plain file copy of a live SQLite database can catch a half-written
transaction, so snapshots go through sqlite3's own backup API, which is
consistent even while the bot is writing.

Snapshots are sent to Telegram as documents. That makes the backup offsite,
free and permanent, with no extra service to configure.
"""

import datetime as dt
import logging
import os
import shutil
import sqlite3
import tempfile

import config
import db

log = logging.getLogger(__name__)

RESTORE_TOKEN = "RESTORE"


def _stamp() -> str:
    return dt.datetime.now(config.IST).strftime("%Y%m%d_%H%M")


async def snapshot() -> tuple[str, int]:
    """Write a consistent copy to a temp path. Returns (path, size_bytes)."""
    await db.checkpoint()

    target = os.path.join(
        tempfile.gettempdir(), f"bot_backup_{_stamp()}.db"
    )
    if os.path.exists(target):
        os.remove(target)

    source = sqlite3.connect(config.DB_PATH)
    dest = sqlite3.connect(target)
    try:
        with dest:
            source.backup(dest)
    finally:
        dest.close()
        source.close()

    return target, os.path.getsize(target)


async def send_backup(bot, chat_id: int, note: str = "") -> str:
    """Take a snapshot and deliver it. Returns a short status line."""
    if not chat_id:
        return "no backup chat configured"

    path, size = await snapshot()
    counts = await db.table_counts()
    caption = (
        f"Backup {_stamp()} IST\n"
        f"candidates {counts['candidates']} | "
        f"submitted-history {counts['submission_history']} | "
        f"keys {counts['answer_keys']}\n"
        f"{size // 1024} KB"
    )
    if note:
        caption = f"{note}\n\n{caption}"

    try:
        with open(path, "rb") as fh:
            await bot.send_document(
                chat_id=chat_id,
                document=fh,
                filename=os.path.basename(path),
                caption=caption,
            )
        return "sent"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def backup_job(context) -> None:
    try:
        await send_backup(context.bot, config.BACKUP_CHAT_ID, note="Automatic backup")
    except Exception:
        log.exception("Automatic backup failed")


async def inspect_restore(path: str) -> tuple[bool, dict, str]:
    """Check an uploaded file is a usable backup.

    Returns (ok, row_counts, message).
    """
    if not os.path.exists(path):
        return False, {}, "File not found."

    try:
        probe = sqlite3.connect(path)
        probe.execute("PRAGMA schema_version")
        probe.close()
    except sqlite3.DatabaseError:
        return False, {}, "That file is not a valid SQLite database."

    counts = await db.table_counts(path)
    missing = [t for t, n in counts.items() if n == -1]
    if missing:
        return False, counts, f"Schema mismatch, missing tables: {', '.join(missing)}"

    return True, counts, "Looks like a valid backup."


async def apply_restore(path: str) -> str:
    """Swap the uploaded file in. The current DB is preserved alongside it."""
    await db.checkpoint()
    await db.close()

    safety = f"{config.DB_PATH}.replaced_{_stamp()}"
    try:
        if os.path.exists(config.DB_PATH):
            shutil.copy2(config.DB_PATH, safety)

        # Stale WAL or shared-memory files would otherwise shadow the new file.
        for suffix in ("-wal", "-shm"):
            side = config.DB_PATH + suffix
            if os.path.exists(side):
                os.remove(side)

        shutil.copy2(path, config.DB_PATH)
    finally:
        await db.init()

    counts = await db.table_counts()
    return (
        f"Restored. candidates {counts['candidates']}, "
        f"keys {counts['answer_keys']}.\n"
        f"Previous database kept at {os.path.basename(safety)}."
    )
