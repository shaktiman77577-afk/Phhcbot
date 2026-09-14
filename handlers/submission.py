"""Marks entry, validation and the result card."""

from telegram import Update
from telegram.ext import ContextTypes

import config
import db
import keyboards as kb
import states
import texts
from handlers import common
from services import analytics, normalisation
from services.validation import (
    fmt,
    nearest_possible,
    parse_number,
    validate_attempted,
    validate_marks,
)


async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    candidate = await db.get_candidate(user.id)
    if not candidate:
        await update.effective_message.reply_text(texts.NOT_REGISTERED)
        return

    if not await common.submission_open():
        await update.effective_message.reply_text(
            texts.SUBMISSION_LOCKED.format(unlock=config.unlock_label())
        )
        return

    await update.effective_message.reply_text(texts.ASK_GK_ATTEMPTED)
    await db.set_session(user.id, states.SUB_GK_ATT, {})


async def on_gk_attempted(update, context, draft: dict) -> None:
    value = parse_number(update.effective_message.text or "")
    if value is None:
        await update.effective_message.reply_text(texts.ERR_NUMBER)
        return
    if validate_attempted(value, config.GK_QUESTIONS):
        await update.effective_message.reply_text(
            texts.ERR_ATTEMPTED_RANGE.format(max_q=config.GK_QUESTIONS)
        )
        return
    draft["gk_attempted"] = int(value)
    await update.effective_message.reply_text(texts.ASK_GK_MARKS)
    await db.set_session(update.effective_user.id, states.SUB_GK_MARKS, draft)


async def on_gk_marks(update, context, draft: dict) -> None:
    if await _handle_marks(update, draft, "gk", config.GK_MIN, config.GK_MAX):
        await update.effective_message.reply_text(texts.ASK_EN_ATTEMPTED)
        await db.set_session(update.effective_user.id, states.SUB_EN_ATT, draft)


async def on_en_attempted(update, context, draft: dict) -> None:
    value = parse_number(update.effective_message.text or "")
    if value is None:
        await update.effective_message.reply_text(texts.ERR_NUMBER)
        return
    if validate_attempted(value, config.EN_QUESTIONS):
        await update.effective_message.reply_text(
            texts.ERR_ATTEMPTED_RANGE.format(max_q=config.EN_QUESTIONS)
        )
        return
    draft["en_attempted"] = int(value)
    await update.effective_message.reply_text(texts.ASK_EN_MARKS)
    await db.set_session(update.effective_user.id, states.SUB_EN_MARKS, draft)


async def on_en_marks(update, context, draft: dict) -> None:
    if not await _handle_marks(update, draft, "en", config.EN_MIN, config.EN_MAX):
        return

    candidate = await db.get_candidate(update.effective_user.id)
    total = round(draft["gk_marks"] + draft["en_marks"], 2)
    draft["total"] = total

    await update.effective_message.reply_text(
        texts.CONFIRM_SUMMARY.format(
            name=candidate.get("name"),
            roll=candidate.get("roll_no"),
            date=config.DATE_LABELS.get(str(candidate.get("exam_date")), candidate.get("exam_date")),
            shift=candidate.get("shift"),
            category=candidate.get("category"),
            gk=fmt(draft["gk_marks"]),
            gk_att=draft["gk_attempted"],
            en=fmt(draft["en_marks"]),
            en_att=draft["en_attempted"],
            total=fmt(total),
        ),
        reply_markup=kb.confirm_submission(),
    )
    await db.set_session(update.effective_user.id, states.SUB_CONFIRM, draft)


async def _handle_marks(update, draft: dict, section: str, lo: float, hi: float) -> bool:
    value = parse_number(update.effective_message.text or "")
    if value is None:
        await update.effective_message.reply_text(texts.ERR_NUMBER)
        return False

    attempted = draft[f"{section}_attempted"]
    error = validate_marks(value, attempted, section)

    if error == "step":
        await update.effective_message.reply_text(texts.ERR_MARKS_STEP)
        return False
    if error == "range":
        await update.effective_message.reply_text(
            texts.ERR_MARKS_RANGE.format(lo=fmt(lo), hi=fmt(hi))
        )
        return False
    if error == "impossible":
        near = ", ".join(fmt(s) for s in nearest_possible(value, attempted))
        await update.effective_message.reply_text(
            texts.ERR_IMPOSSIBLE.format(att=attempted, near=near)
        )
        return False

    draft[f"{section}_marks"] = value
    return True


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    user = update.effective_user
    candidate = await db.get_candidate(user.id)

    payload = {
        "telegram_id": user.id,
        "gk_attempted": draft["gk_attempted"],
        "gk_marks": draft["gk_marks"],
        "en_attempted": draft["en_attempted"],
        "en_marks": draft["en_marks"],
        "total_marks": draft["total"],
        "status": "submitted",
    }
    await db.upsert_candidate(payload)
    await db.add_history(
        {
            "telegram_id": user.id,
            "gk_marks": draft["gk_marks"],
            "en_marks": draft["en_marks"],
            "total_marks": draft["total"],
            "key_version": candidate.get("key_version") or "provisional",
        }
    )
    await db.clear_session(user.id)

    await send_result_card(update, context, candidate, draft["total"])


async def send_result_card(update, context, candidate: dict, total: float) -> None:
    pool = await analytics.load_pool()
    date = str(candidate.get("exam_date"))
    shift = int(candidate.get("shift"))
    category = candidate.get("category")

    shift_vals = pool.by_shift.get((date, shift), [])
    shift_stats = pool.shift_stats(date, shift)
    top_pct = round(100.0 - analytics.percentile_of(shift_vals, total), 1)
    band = pool.category_band(category)
    cat_median = pool.category_median(category)

    band_line = (
        f"{category} expected band: {fmt(band[0])} - {fmt(band[1])}\n"
        if band
        else ""
    )

    body = texts.RESULT_CARD.format(
        total=fmt(total),
        gk=fmt(candidate.get("gk_marks") or 0) if candidate.get("gk_marks") is not None else fmt(0),
        en=fmt(candidate.get("en_marks") or 0) if candidate.get("en_marks") is not None else fmt(0),
        date=config.DATE_LABELS.get(date, date),
        shift=shift,
        percentile=max(top_pct, 0.1),
        shift_n=shift_stats["n"],
        shift_median=fmt(shift_stats["median"]) if shift_stats["median"] is not None else "-",
        category=category,
        cat_median=fmt(cat_median) if cat_median is not None else "-",
        band_line=band_line,
        total_n=pool.n,
    )
    body += normalisation.student_line(
        normalisation.estimate(pool, date, shift, total)
    )
    body += texts.RESULT_DISCLAIMER + texts.SHARE_PROMPT

    link = common.referral_link(update.effective_user.id)
    markup = kb.share_button(link) if link else None
    await update.effective_message.reply_text(body, reply_markup=markup)

    await _send_upsell(update, candidate, total, band)


async def _send_upsell(update, candidate: dict, total: float, band) -> None:
    """Branch on where the candidate landed. This is the business end."""
    if band and total >= band[0]:
        message = (
            "You are inside the expected band. The next stage is the Computer "
            "Proficiency Test, and it is qualifying but not optional.\n\n"
            f"{config.BRAND_NAME} has typing practice passages in court record "
            "style and a legal and court vocabulary booklet ready for exactly "
            "this stage. Ask support for the current link."
        )
    else:
        message = (
            "This exam is one attempt, not the whole plan. "
            f"{config.BRAND_NAME} runs courses for the next clerk and clerical "
            "cycles, with bilingual mock tests built on the same pattern. "
            "Ask support for what is running now."
        )
    await update.effective_message.reply_text(message)
