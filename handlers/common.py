"""Helpers shared across handlers."""

import datetime as dt

from telegram import Update
from telegram.ext import ContextTypes

import config
import db
import keyboards as kb


def is_admin(telegram_id: int) -> bool:
    return telegram_id in config.ADMIN_IDS


async def submission_open() -> bool:
    """True once the admin has opened it, or once the unlock moment passes.

    The unlock moment is a full date and time, not just a time of day. With a
    time alone the bot would open itself at 4 PM on whatever day it happened
    to be running, including days before the answer key is out.
    """
    flag = await db.get_config("submission_open", False)
    if flag is True or flag == "true":
        return True

    unlock = config.submission_unlock_at()
    if unlock is None:
        return False  # no date set: stays closed until an admin opens it

    return dt.datetime.now(config.IST) >= unlock


async def show_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, greeting: str | None = None
) -> None:
    user = update.effective_user
    candidate = await db.get_candidate(user.id)
    is_open = await submission_open()

    header = greeting or f"{config.EXAM_NAME} - Score Report Bot"
    if candidate and candidate.get("status") == "submitted":
        header += f"\n\nYour submitted total: {candidate.get('total_marks')} / 70"
    elif candidate and not is_open:
        header += f"\n\nYou are registered. Submission opens {config.unlock_label()}."

    markup = kb.main_menu(
        is_registered=bool(candidate),
        submission_open=is_open,
        is_admin=is_admin(user.id),
    )
    await update.effective_message.reply_text(header, reply_markup=markup)


def referral_link(telegram_id: int) -> str:
    if not config.BOT_USERNAME:
        return ""
    return f"https://t.me/{config.BOT_USERNAME}?start=ref_{telegram_id}"
