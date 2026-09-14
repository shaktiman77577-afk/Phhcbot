"""The live report post.

Published once by the admin, then edited in place every 5 minutes. Telegram
rate limits edits and rejects an edit whose content is identical, so both are
handled here.
"""

import datetime as dt
import hashlib
import logging

from telegram.error import BadRequest, RetryAfter

import config
import db
from services import analytics
from services.validation import fmt

log = logging.getLogger(__name__)


def _stamp() -> str:
    return dt.datetime.now(config.IST).strftime("%I:%M %p").lstrip("0")


async def build_post(pool: analytics.Pool | None = None) -> str:
    if pool is None:
        pool = await analytics.load_pool()

    frozen = await db.get_config("frozen_difficulty", {}) or {}

    lines = [
        f"{config.EXAM_NAME} - LIVE SCORE REPORT",
        "",
        f"Based on {pool.n} submissions  |  updated {_stamp()}",
        "",
    ]

    overall = pool.overall_median
    if overall is not None:
        lines.append(f"Overall median score: {fmt(overall)} / 70")
        lines.append("")

    lines.append("SHIFT DIFFICULTY")
    any_shift = False
    for date in config.EXAM_DATES:
        parts = []
        for shift in config.SHIFTS:
            stats = pool.shift_stats(date, shift)
            if stats["n"] == 0:
                continue
            label = pool.difficulty(date, shift, frozen)
            short = {
                "Easy": "Easy",
                "Moderate": "Mod",
                "Hard": "Hard",
                "Collecting data": "...",
            }[label]
            parts.append(f"S{shift} {short}")
            any_shift = True
        if parts:
            lines.append(f"{config.DATE_LABELS[date]}:  " + "  ".join(parts))
    if not any_shift:
        lines.append("Collecting data.")
    lines.append("")

    lines.append("EXPECTED CUTOFF BAND")
    any_band = False
    for cat in config.CATEGORIES:
        band = pool.category_band(cat)
        if band:
            lines.append(f"{cat}: {fmt(band[0])} - {fmt(band[1])}")
            any_band = True
    if not any_band:
        lines.append("Not enough data yet.")
    lines.append("")

    lines.append(
        "This is self reported data from candidates, not official. SSSC "
        "normalises marks across shifts, so final scores will differ from raw "
        "scores. Treat the band as indicative only."
    )
    lines.append("")
    lines.append(
        f"Submit your score: https://t.me/{config.BOT_USERNAME}"
        if config.BOT_USERNAME
        else "Submit your score in the bot."
    )
    lines.append(f"- Team {config.BRAND_NAME}")

    return "\n".join(lines)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def publish(bot) -> int:
    """Post the report for the first time and remember its message id."""
    body = await build_post()
    msg = await bot.send_message(
        chat_id=config.REPORT_CHAT_ID, text=body, disable_web_page_preview=True
    )
    await db.set_config("report_message_id", msg.message_id)
    await db.set_config("report_edit_count", 0)
    await db.set_config("report_body_hash", _hash(body))
    await db.set_config("report_auto_update", True)
    return msg.message_id


async def refresh(bot, force: bool = False) -> str:
    """Edit the existing post. Returns a short status string."""
    message_id = await db.get_config("report_message_id")
    if not message_id:
        return "not published"

    if not force and not (await db.get_config("report_auto_update", True)):
        return "auto update paused"

    pool = await analytics.load_pool()
    await analytics.freeze_stable_labels(pool)
    body = await build_post(pool)

    previous = await db.get_config("report_body_hash")
    if previous == _hash(body) and not force:
        return "unchanged, skipped"

    try:
        await bot.edit_message_text(
            chat_id=config.REPORT_CHAT_ID,
            message_id=int(message_id),
            text=body,
            disable_web_page_preview=True,
        )
    except RetryAfter as exc:
        log.warning("Report edit rate limited, retry after %ss", exc.retry_after)
        return f"rate limited ({exc.retry_after}s)"
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return "unchanged, skipped"
        log.error("Report edit failed: %s", exc)
        return f"failed: {exc}"

    count = (await db.get_config("report_edit_count", 0)) or 0
    await db.set_config("report_edit_count", int(count) + 1)
    await db.set_config("report_body_hash", _hash(body))
    return "updated"


async def refresh_job(context) -> None:
    """JobQueue callback, runs every REPORT_REFRESH_SECONDS."""
    try:
        await refresh(context.bot)
    except Exception:  # never let a bad tick kill the job
        log.exception("Report refresh job failed")
