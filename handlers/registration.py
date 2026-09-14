"""Registration: name, roll number, date, shift, category, centre."""

from telegram import Update
from telegram.ext import ContextTypes

import config
import db
import keyboards as kb
import states
import texts
from handlers import common


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await db.clear_session(user.id)

    # Referral: /start ref_123456789
    referred_by = None
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                candidate_id = int(arg[4:])
                if candidate_id != user.id:
                    referred_by = candidate_id
            except ValueError:
                pass
    if referred_by:
        await db.set_session(user.id, states.IDLE, {"referred_by": referred_by})

    existing = await db.get_candidate(user.id)
    if existing:
        await common.show_menu(update, context, greeting=f"Welcome back, {existing.get('name') or ''}.".strip())
        return

    await update.effective_message.reply_text(
        texts.CONSENT.format(brand=config.BRAND_NAME, exam=config.EXAM_NAME)
    )
    await update.effective_message.reply_text(texts.ASK_NAME)
    draft = {"referred_by": referred_by} if referred_by else {}
    await db.set_session(user.id, states.REG_NAME, draft)


async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entered from the Register button."""
    user = update.effective_user
    session = await db.get_session(user.id)
    draft = session.get("draft") or {}
    await update.effective_message.reply_text(texts.ASK_NAME)
    await db.set_session(user.id, states.REG_NAME, draft)


async def on_name(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    name = (update.effective_message.text or "").strip()
    if not name or len(name) > 60:
        await update.effective_message.reply_text(texts.ERR_NAME)
        return
    draft["name"] = name
    await update.effective_message.reply_text(texts.ASK_ROLL)
    await db.set_session(update.effective_user.id, states.REG_ROLL, draft)


async def on_roll(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    roll = (update.effective_message.text or "").strip()
    if not roll or len(roll) > 30:
        await update.effective_message.reply_text(texts.ERR_NAME)
        return
    if await db.roll_taken_by_other(roll, update.effective_user.id):
        await update.effective_message.reply_text(texts.ERR_ROLL_TAKEN)
        return
    draft["roll_no"] = roll
    await update.effective_message.reply_text(texts.ASK_DATE, reply_markup=kb.dates("reg"))
    await db.set_session(update.effective_user.id, states.REG_DATE, draft)


async def on_date(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict, value: str) -> None:
    draft["exam_date"] = value
    await update.effective_message.edit_text(texts.ASK_SHIFT, reply_markup=kb.shifts("reg"))
    await db.set_session(update.effective_user.id, states.REG_SHIFT, draft)


async def on_shift(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict, value: str) -> None:
    draft["shift"] = int(value)
    await update.effective_message.edit_text(texts.ASK_CATEGORY, reply_markup=kb.categories())
    await db.set_session(update.effective_user.id, states.REG_CATEGORY, draft)


async def on_category(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict, value: str) -> None:
    """Category is the last required field. Save immediately, then ask centre.

    Centre is asked after saving on purpose: it is optional and must never
    stand between a candidate and a completed registration.
    """
    user = update.effective_user
    draft["category"] = value

    payload = {
        "telegram_id": user.id,
        "name": draft.get("name"),
        "roll_no": draft.get("roll_no"),
        "exam_date": draft.get("exam_date"),
        "shift": draft.get("shift"),
        "category": value,
        "status": "registered",
    }
    if draft.get("referred_by"):
        payload["referred_by"] = draft["referred_by"]

    await db.upsert_candidate(payload)
    if draft.get("referred_by"):
        await db.bump_referral(draft["referred_by"])

    await update.effective_message.edit_text(
        texts.REGISTERED.format(
            name=draft.get("name"),
            date=config.DATE_LABELS[draft["exam_date"]],
            shift=draft["shift"],
            category=value,
            unlock=config.unlock_label(),
        )
    )
    await update.effective_message.reply_text(texts.ASK_CENTRE, reply_markup=kb.centres())
    await db.set_session(user.id, states.REG_CENTRE, draft)


async def on_centre(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict, value: str) -> None:
    user = update.effective_user
    if value != "skip":
        await db.upsert_candidate({"telegram_id": user.id, "centre": value})
        await update.effective_message.edit_text(f"Centre saved: {value}")
    else:
        await update.effective_message.edit_text("Skipped.")
    await db.clear_session(user.id)
    await common.show_menu(update, context)
