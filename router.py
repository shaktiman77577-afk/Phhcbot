"""Routing.

Conversation state lives in Supabase rather than in a ConversationHandler,
so a Railway redeploy in the middle of the 4 PM rush does not wipe every
half finished submission.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

import db
import states
import texts
from handlers import admin, answer_key, common, registration, stats, submission

log = logging.getLogger(__name__)

TEXT_ROUTES = {
    states.REG_NAME: registration.on_name,
    states.REG_ROLL: registration.on_roll,
    states.SUB_GK_ATT: submission.on_gk_attempted,
    states.SUB_GK_MARKS: submission.on_gk_marks,
    states.SUB_EN_ATT: submission.on_en_attempted,
    states.SUB_EN_MARKS: submission.on_en_marks,
    states.ADMIN_BROADCAST: admin.on_broadcast_text,
    states.ADMIN_RESTORE_CONFIRM: admin.on_restore_confirm,
}


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = await db.get_session(update.effective_user.id)
    state = session.get("state", states.IDLE)
    draft = session.get("draft") or {}

    handler = TEXT_ROUTES.get(state)
    if handler:
        await handler(update, context, draft)
        return

    await common.show_menu(update, context)


async def document_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = await db.get_session(update.effective_user.id)
    state = session.get("state")
    if state == states.KEY_AWAIT_FILE:
        await answer_key.on_file(update, context, session.get("draft") or {})
        return
    if state == states.ADMIN_RESTORE_FILE:
        await admin.on_restore_file(update, context, session.get("draft") or {})
        return
    await update.effective_message.reply_text(
        "Tap Answer Keys first, choose your date and shift, then send the PDF."
    )


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split(":")
    ns = parts[0]

    session = await db.get_session(update.effective_user.id)
    draft = session.get("draft") or {}

    try:
        if ns == "menu":
            await _menu(update, context, parts[1])
        elif ns == "reg":
            await _reg(update, context, draft, parts)
        elif ns == "sub":
            await _sub(update, context, draft, parts[1])
        elif ns == "key":
            if parts[1] == "slot":
                await answer_key.pick_slot(update, context, parts[2], int(parts[3]))
        elif ns == "data":
            if parts[1] == "delete_yes":
                await stats.do_delete(update, context)
        elif ns == "admin":
            await _admin(update, context, parts[1])
    except Exception:
        log.exception("Callback %s failed", data)
        await update.effective_message.reply_text(
            "Something went wrong there. Send /start to get back to the menu."
        )


async def _menu(update, context, action: str) -> None:
    if action == "register":
        await registration.begin(update, context)
    elif action == "submit":
        await submission.begin(update, context)
    elif action == "result":
        await stats.my_result(update, context)
    elif action == "stats":
        await stats.live_stats(update, context)
    elif action == "keys":
        await answer_key.show_grid(update, context)
    elif action == "share":
        await stats.share(update, context)
    elif action == "cancel":
        await db.clear_session(update.effective_user.id)
        await update.effective_message.reply_text(texts.CANCELLED)
        await common.show_menu(update, context)
    elif action == "home":
        await common.show_menu(update, context)


async def _reg(update, context, draft: dict, parts: list[str]) -> None:
    field, value = parts[1], parts[2]
    if field == "date":
        await registration.on_date(update, context, draft, value)
    elif field == "shift":
        await registration.on_shift(update, context, draft, value)
    elif field == "category":
        await registration.on_category(update, context, draft, value)
    elif field == "centre":
        await registration.on_centre(update, context, draft, value)


async def _sub(update, context, draft: dict, action: str) -> None:
    if action == "confirm":
        await submission.confirm(update, context, draft)
    elif action == "restart":
        await submission.begin(update, context)


async def _admin(update, context, action: str) -> None:
    routes = {
        "home": admin.home,
        "dashboard": admin.dashboard,
        "shifts": admin.shifts_view,
        "bands": admin.bands_view,
        "keys": admin.keys_view,
        "outliers": admin.outliers,
        "pdf": admin.send_pdf,
        "csv": admin.send_csv,
        "publish_home": admin.publish_home,
        "preview": admin.preview,
        "publish": admin.do_publish,
        "update_now": admin.update_now,
        "toggle_auto": admin.toggle_auto,
        "detach": admin.detach,
        "open_submission": admin.open_submission,
        "backup": admin.backup_now,
        "restore": admin.restore_start,
    }
    handler = routes.get(action)
    if handler:
        await handler(update, context)
