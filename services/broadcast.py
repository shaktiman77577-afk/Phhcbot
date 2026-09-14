"""Throttled broadcast.

Telegram caps bulk sending at roughly 30 messages a second and will block a
bot that fires at everyone at once. Messages are queued in the DB and drained
a few at a time, which also means a redeploy mid broadcast resumes instead of
starting over or double sending.
"""

import asyncio
import logging

from telegram.error import Forbidden, RetryAfter, TelegramError

import config
import db

log = logging.getLogger(__name__)


async def enqueue_all(body: str) -> int:
    ids = await db.registered_telegram_ids()
    return await db.queue_broadcast(ids, body)


async def drain_job(context) -> None:
    """JobQueue callback. Sends a small batch, then yields."""
    try:
        batch = await db.take_broadcast_batch(config.BROADCAST_BATCH)
        for row in batch:
            try:
                await context.bot.send_message(
                    chat_id=row["telegram_id"],
                    text=row["body"],
                    disable_web_page_preview=True,
                )
                await db.mark_broadcast(row["id"], "sent")
            except Forbidden:
                # User blocked the bot. Not an error worth retrying.
                await db.mark_broadcast(row["id"], "failed")
            except RetryAfter as exc:
                log.warning("Broadcast throttled, sleeping %ss", exc.retry_after)
                await asyncio.sleep(exc.retry_after + 1)
                break
            except TelegramError as exc:
                log.warning("Broadcast to %s failed: %s", row["telegram_id"], exc)
                await db.mark_broadcast(row["id"], "failed")
            await asyncio.sleep(0.05)
    except Exception:
        log.exception("Broadcast drain failed")
