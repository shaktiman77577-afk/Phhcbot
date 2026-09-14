"""Public facing stats, personal result, sharing and data deletion."""

from telegram import Update
from telegram.ext import ContextTypes

import config
import db
import keyboards as kb
import texts
from handlers import common
from services import analytics
from services.validation import fmt

REFERRALS_FOR_FULL_BREAKDOWN = 3


async def live_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await common.submission_open():
        n = await db.count_where()
        await update.effective_message.reply_text(
            texts.LIVE_STATS_PRE.format(
                exam=config.EXAM_NAME, n=n, unlock=config.unlock_label()
            ),
            reply_markup=kb.back_to(),
        )
        return

    pool = await analytics.load_pool()
    if pool.n == 0:
        await update.effective_message.reply_text(texts.NO_DATA_YET, reply_markup=kb.back_to())
        return

    frozen = await db.get_config("frozen_difficulty", {}) or {}
    lines = [
        f"{config.EXAM_NAME} - Live Stats",
        "",
        f"Submissions: {pool.n}",
    ]
    overall = pool.overall_median
    if overall is not None:
        lines.append(f"Overall median: {fmt(overall)} / 70")
    lines.append("")

    lines.append("Category medians")
    for cat in config.CATEGORIES:
        median = pool.category_median(cat)
        count = len(pool.by_category.get(cat, []))
        if count:
            lines.append(f"{cat}: {fmt(median)}  ({count} entries)")
    lines.append("")

    lines.append("Shift difficulty")
    shown = 0
    for date in config.EXAM_DATES:
        parts = []
        for shift in config.SHIFTS:
            stats = pool.shift_stats(date, shift)
            if stats["n"] == 0:
                continue
            parts.append(f"S{shift} {pool.difficulty(date, shift, frozen)}")
            shown += 1
        if parts:
            lines.append(f"{config.DATE_LABELS[date]}: " + " | ".join(parts))
    if not shown:
        lines.append("Collecting data.")

    lines.append("")
    lines.append(
        "Self reported data. SSSC normalises across shifts, so final scores "
        "will differ."
    )
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb.back_to())


async def my_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    candidate = await db.get_candidate(user.id)
    if not candidate:
        await update.effective_message.reply_text(texts.NOT_REGISTERED)
        return
    if candidate.get("status") != "submitted":
        await update.effective_message.reply_text(
            texts.SUBMISSION_LOCKED.format(unlock=config.unlock_label())
        )
        return

    from handlers import submission

    await submission.send_result_card(
        update, context, candidate, float(candidate["total_marks"])
    )


async def share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    candidate = await db.get_candidate(user.id)
    link = common.referral_link(user.id)
    count = (candidate or {}).get("referral_count") or 0

    if count >= REFERRALS_FOR_FULL_BREAKDOWN:
        await _full_breakdown(update)
        return

    await update.effective_message.reply_text(
        texts.REFERRAL_LOCKED.format(count=count, link=link),
        reply_markup=kb.share_button(link) if link else None,
    )


async def _full_breakdown(update: Update) -> None:
    pool = await analytics.load_pool()
    frozen = await db.get_config("frozen_difficulty", {}) or {}
    lines = ["Full shift by shift breakdown", ""]
    for date in config.EXAM_DATES:
        for shift in config.SHIFTS:
            stats = pool.shift_stats(date, shift)
            if stats["n"] == 0:
                continue
            lines.append(
                f"{config.DATE_LABELS[date]} S{shift}  "
                f"n={stats['n']}  median={fmt(stats['median'])}  "
                f"high={fmt(stats['high'])}  {pool.difficulty(date, shift, frozen)}"
            )
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb.back_to())


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.delete_candidate(update.effective_user.id)
    await update.effective_message.reply_text(texts.DELETED)
