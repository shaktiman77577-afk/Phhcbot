"""Shift wise answer key collection.

Shift wise official keys only. Personal response sheets carry the candidate's
roll number and name, so the bot does not accept them.
"""

from telegram import Update
from telegram.ext import ContextTypes

import config
import db
import keyboards as kb
import states
import texts


async def show_grid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    slots = await db.answer_key_slots()
    total = len(config.EXAM_DATES) * len(config.SHIFTS)
    header = f"{texts.KEY_MENU}\n\nReceived: {len(slots)} of {total}"
    await update.effective_message.reply_text(header, reply_markup=kb.key_grid(slots))


async def pick_slot(
    update: Update, context: ContextTypes.DEFAULT_TYPE, date: str, shift: int
) -> None:
    slots = await db.answer_key_slots()
    if (date, shift) in slots:
        existing = slots[(date, shift)]
        await update.effective_message.reply_text(
            f"Answer key for {config.DATE_LABELS[date]} Shift {shift} is already "
            "on file. Send a new PDF to replace it."
        )
        await context.bot.send_document(
            chat_id=update.effective_chat.id, document=existing["file_id"]
        )

    await update.effective_message.reply_text(
        texts.KEY_ASK_FILE.format(date=config.DATE_LABELS[date], shift=shift)
    )
    await db.set_session(
        update.effective_user.id,
        states.KEY_AWAIT_FILE,
        {"exam_date": date, "shift": shift},
    )


async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    doc = update.effective_message.document
    if not doc or (doc.mime_type or "") != "application/pdf":
        await update.effective_message.reply_text(texts.KEY_WRONG_TYPE)
        return

    await db.save_answer_key(
        {
            "exam_date": draft["exam_date"],
            "shift": draft["shift"],
            "file_id": doc.file_id,
            "file_name": doc.file_name,
            "uploaded_by": update.effective_user.id,
        }
    )
    await db.clear_session(update.effective_user.id)
    await update.effective_message.reply_text(texts.KEY_SAVED)
    await show_grid(update, context)
