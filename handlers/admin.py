"""Admin panel."""

import csv
import io
import os
import tempfile

from telegram import Update
from telegram.ext import ContextTypes

import config
import db
import keyboards as kb
import states
import texts
from handlers import common
from services import analytics, backup, broadcast, normalisation, pdf_report, report
from services.validation import fmt


async def guard(update: Update) -> bool:
    if not common.is_admin(update.effective_user.id):
        await update.effective_message.reply_text(texts.NOT_ADMIN)
        return False
    return True


async def home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await update.effective_message.reply_text("Admin panel", reply_markup=kb.admin_home())


async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    registered = await db.count_where()
    submitted = await db.count_where(status="submitted")
    anonymised = await db.anonymised_count()
    today = await db.count_registered_today()
    pending = await db.broadcast_pending_count()
    slots = await db.answer_key_slots()
    pool = await analytics.load_pool()
    message_id = await db.get_config("report_message_id")
    edits = await db.get_config("report_edit_count", 0)
    is_open = await common.submission_open()

    lines = [
        "DASHBOARD",
        "",
        f"Registered: {registered}",
        f"Submitted: {submitted}",
        f"Anonymised on request: {anonymised} (scores kept, identity gone)",
        f"New in last 24h: {today}",
        f"Submission window: {'OPEN' if is_open else 'closed'}",
        "",
        f"Overall median: {fmt(pool.overall_median) if pool.overall_median is not None else '-'}",
        f"Answer keys: {len(slots)} / {len(config.EXAM_DATES) * len(config.SHIFTS)}",
        f"Broadcast queue pending: {pending}",
        "",
        f"Report post: {'live, ' + str(edits) + ' edits' if message_id else 'not published'}",
    ]
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb.back_to("admin:home"))


async def shifts_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    pool = await analytics.load_pool()
    frozen = await db.get_config("frozen_difficulty", {}) or {}
    lines = ["SHIFT DIFFICULTY", ""]
    for date in config.EXAM_DATES:
        for shift in config.SHIFTS:
            stats = pool.shift_stats(date, shift)
            label = pool.difficulty(date, shift, frozen)
            locked = " [locked]" if f"{date}|{shift}" in frozen else ""
            lines.append(
                f"{config.DATE_LABELS[date]} S{shift}: n={stats['n']} "
                f"med={fmt(stats['median']) if stats['median'] is not None else '-'} "
                f"hi={fmt(stats['high']) if stats['high'] is not None else '-'} "
                f"att={stats['avg_attempted'] or '-'} -> {label}{locked}"
            )
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb.back_to("admin:home"))


async def bands_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    pool = await analytics.load_pool()
    lines = ["CATEGORY BANDS", ""]
    for cat in config.CATEGORIES:
        vals = pool.by_category.get(cat, [])
        band = pool.category_band(cat)
        median = pool.category_median(cat)
        lines.append(
            f"{cat}: n={len(vals)} "
            f"med={fmt(median) if median is not None else '-'} "
            f"band={f'{fmt(band[0])} - {fmt(band[1])}' if band else 'insufficient'}"
        )
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb.back_to("admin:home"))


async def norm_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    pool = await analytics.load_pool()
    base = normalisation.pool_anchor(pool)
    rows = normalisation.all_estimates(pool)

    lines = ["NORMALISATION ESTIMATE", ""]
    if base is None:
        lines.append("Pool is too small to anchor anything yet.")
        await update.effective_message.reply_text(
            "\n".join(lines), reply_markup=kb.back_to("admin:home")
        )
        return

    g, anchor = base
    lines += [
        f"Pivot G (mean + 1 SD): {fmt(g)}",
        f"Overall 95th pct anchor: {fmt(anchor)}",
        f"Overall median: {fmt(pool.overall_median)}",
        "",
        "Sorted by estimated benefit, best first.",
        "",
    ]

    for r in rows:
        label = f"{config.DATE_LABELS[r['date']]} S{r['shift']}"
        if r["status"] == "insufficient":
            lines.append(f"{label}: n={r['n']} - too few, no estimate")
            continue
        arrow = {"up": "UP", "down": "DOWN", "flat": "~", "unclear": "?"}[r["direction"]]
        line = (
            f"{label}: n={r['n']} gap={r['gap']:+} "
            f"est={r['low']:+} to {r['high']:+} [{arrow}]"
        )
        if r["status"] == "unreliable":
            line += " (factor unusable, equating only)"
        lines.append(line)
        if r.get("factor"):
            lines.append(
                f"    factor={r['factor']} "
                f"at-median={r['adj_at_median']:+} "
                f"at-cutoff={r['adj_at_cutoff']:+}"
            )

    lines += [
        "",
        "Reading this: at-median and at-cutoff can carry opposite signs. The "
        "linear map pivots around G, so in a hard shift it lifts candidates "
        "above G and pushes those below G further down. Only the cutoff region "
        "decides selection, so at-cutoff is the number that matters.",
        "",
        "Range is the spread between the SSC-shaped map and plain median "
        "equating. A wide spread means the estimate is shaky.",
    ]

    await update.effective_message.reply_text(
        "\n".join(lines), reply_markup=kb.back_to("admin:home")
    )


async def keys_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    slots = await db.answer_key_slots()
    lines = ["ANSWER KEY COVERAGE", ""]
    for date in config.EXAM_DATES:
        marks = []
        for shift in config.SHIFTS:
            marks.append(f"S{shift} {'received' if (date, shift) in slots else 'missing'}")
        lines.append(f"{config.DATE_LABELS[date]}: " + " | ".join(marks))
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb.back_to("admin:home"))


async def outliers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entries that survived arithmetic validation but look statistically odd."""
    if not await guard(update):
        return
    pool = await analytics.load_pool()
    suspects = []
    for date in config.EXAM_DATES:
        for shift in config.SHIFTS:
            vals = pool.by_shift.get((date, shift), [])
            if len(vals) < 15:
                continue
            median = analytics.trimmed_median(vals) or 0
            for row in pool.rows:
                if str(row.get("exam_date")) != date or int(row.get("shift") or 0) != shift:
                    continue
                total = float(row["total_marks"])
                if total - median >= 20:
                    suspects.append((row, total, median))

    already = await db.flagged_rows()
    lines = ["OUTLIER QUEUE", ""]
    if not suspects:
        lines.append("Nothing unusual right now.")
    for row, total, median in suspects[:25]:
        lines.append(
            f"{row.get('name') or '(anonymised)'} / roll "
            f"{row.get('roll_no') or '-'} - {fmt(total)} "
            f"vs shift median {fmt(median)}  (id {row['telegram_id']})"
        )
    if suspects:
        lines.append("")
        lines.append("Remove one with: /flag <telegram_id>")
        lines.append("Restore with: /unflag <telegram_id>")
    if already:
        lines.append("")
        lines.append(f"Currently excluded: {len(already)}")
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb.back_to("admin:home"))


async def cmd_flag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /flag <telegram_id>")
        return
    await db.set_flag(int(context.args[0]), True)
    await update.effective_message.reply_text("Excluded from all statistics.")


async def cmd_unflag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /unflag <telegram_id>")
        return
    await db.set_flag(int(context.args[0]), False)
    await update.effective_message.reply_text("Restored.")


async def send_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await update.effective_message.reply_text("Building report...")
    data, name = await pdf_report.build()
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=io.BytesIO(data),
        filename=name,
        caption="Safe to share. No candidate identities in it.",
    )


async def send_detailed_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Full internal analysis. No names or roll numbers, but not for students."""
    if not await guard(update):
        return
    await update.effective_message.reply_text("Building detailed analysis...")
    try:
        data, name = await pdf_report.build_detailed()
    except Exception as exc:
        await update.effective_message.reply_text(f"Could not build the report: {exc}")
        return
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=io.BytesIO(data),
        filename=name,
        caption=(
            "INTERNAL. Shift ranking, score distribution, category by shift, "
            "centre breakdown and daily timeline.\n\n"
            "No names or roll numbers inside, but do not post this in a "
            "student group."
        ),
    )


async def send_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    rows = await db.all_submissions()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "name", "roll_no", "exam_date", "shift", "centre", "category",
            "gk_attempted", "gk_marks", "en_attempted", "en_marks",
            "total_marks", "created_at",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.get("name"), r.get("roll_no"), r.get("exam_date"), r.get("shift"),
                r.get("centre"), r.get("category"), r.get("gk_attempted"),
                r.get("gk_marks"), r.get("en_attempted"), r.get("en_marks"),
                r.get("total_marks"), r.get("created_at"),
            ]
        )
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=io.BytesIO(buf.getvalue().encode()),
        filename="haryana_clerk_2026_submissions.csv",
    )


# ---------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------
async def publish_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    message_id = await db.get_config("report_message_id")
    auto = await db.get_config("report_auto_update", True)
    submitted = await db.count_where(status="submitted")
    edits = await db.get_config("report_edit_count", 0)

    lines = ["PUBLISH REPORT", "", f"Submissions: {submitted}"]
    if submitted < config.REPORT_MIN_SUBMISSIONS and not message_id:
        lines.append(
            f"Below the suggested minimum of {config.REPORT_MIN_SUBMISSIONS}. "
            "You can still publish, the numbers will just be thin."
        )
    if message_id:
        lines.append(f"Post is live. {edits} edits so far.")
        lines.append(f"Auto update: {'on' if auto else 'paused'}")
    else:
        lines.append("Not published yet.")

    await update.effective_message.reply_text(
        "\n".join(lines), reply_markup=kb.admin_publish(bool(message_id), bool(auto))
    )


async def preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    body = await report.build_post()
    await update.effective_message.reply_text(
        "PREVIEW - this is exactly what gets posted:\n\n" + "-" * 30 + "\n" + body,
        disable_web_page_preview=True,
    )
    await publish_home(update, context)


async def do_publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    existing = await db.get_config("report_message_id")
    if existing:
        await update.effective_message.reply_text(
            "A post is already live. Detach it first if you want a new one."
        )
        return
    message_id = await report.publish(context.bot)
    await update.effective_message.reply_text(
        f"Published. Message id {message_id}. It will now refresh every "
        f"{config.REPORT_REFRESH_SECONDS // 60} minutes."
    )


async def update_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    status = await report.refresh(context.bot, force=True)
    await update.effective_message.reply_text(f"Refresh: {status}")


async def toggle_auto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    current = await db.get_config("report_auto_update", True)
    await db.set_config("report_auto_update", not bool(current))
    await publish_home(update, context)


async def detach(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await db.set_config("report_message_id", None)
    await update.effective_message.reply_text(
        "Detached. The old post stays in the group but is no longer updated."
    )


async def open_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual override, for when the official key slips past 4 PM."""
    if not await guard(update):
        return
    await db.set_config("submission_open", True)
    count = await broadcast.enqueue_all(texts.SUBMISSION_OPEN_BROADCAST)
    await update.effective_message.reply_text(
        f"Submission opened. {count} notifications queued, sending gradually."
    )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await update.effective_message.reply_text(
        "Send the message to broadcast to every registered user, or /cancel."
    )
    await db.set_session(update.effective_user.id, states.ADMIN_BROADCAST, {})


async def on_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    body = update.effective_message.text or ""
    count = await broadcast.enqueue_all(body)
    await db.clear_session(update.effective_user.id)
    await update.effective_message.reply_text(f"{count} messages queued.")


# ---------------------------------------------------------------
# Backup and restore
# ---------------------------------------------------------------
async def backup_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await update.effective_message.reply_text("Taking a snapshot...")
    try:
        await backup.send_backup(
            context.bot, update.effective_chat.id, note="Manual backup"
        )
    except Exception as exc:
        await update.effective_message.reply_text(f"Backup failed: {exc}")
        return
    counts = await db.table_counts()
    await update.effective_message.reply_text(
        "Backup delivered above. Save it somewhere you can find later.\n\n"
        f"Live database: {counts['candidates']} candidates, "
        f"{counts['answer_keys']} answer keys.",
        reply_markup=kb.back_to("admin:home"),
    )


async def restore_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    counts = await db.table_counts()
    await update.effective_message.reply_text(
        "RESTORE\n\n"
        "This replaces the entire live database with an uploaded backup.\n\n"
        f"Right now the bot holds {counts['candidates']} candidates and "
        f"{counts['answer_keys']} answer keys. All of it will be swapped out, "
        "though a copy of the current database is kept on the volume.\n\n"
        "Send the .db backup file now, or /cancel."
    )
    await db.set_session(update.effective_user.id, states.ADMIN_RESTORE_FILE, {})


async def on_restore_file(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    if not await guard(update):
        return
    doc = update.effective_message.document
    if not doc:
        await update.effective_message.reply_text("Send the backup file as a document.")
        return

    path = os.path.join(tempfile.gettempdir(), f"restore_{update.effective_user.id}.db")
    tg_file = await context.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(path)

    ok, counts, message = await backup.inspect_restore(path)
    if not ok:
        await update.effective_message.reply_text(f"Rejected. {message}")
        await db.clear_session(update.effective_user.id)
        return

    live = await db.table_counts()
    await update.effective_message.reply_text(
        f"{message}\n\n"
        "Uploaded backup:\n"
        f"  candidates {counts['candidates']}\n"
        f"  history {counts['submission_history']}\n"
        f"  answer keys {counts['answer_keys']}\n\n"
        "Currently live:\n"
        f"  candidates {live['candidates']}\n"
        f"  history {live['submission_history']}\n"
        f"  answer keys {live['answer_keys']}\n\n"
        f"To go ahead, type {backup.RESTORE_TOKEN} exactly. Anything else cancels."
    )
    await db.set_session(
        update.effective_user.id, states.ADMIN_RESTORE_CONFIRM, {"path": path}
    )


async def on_restore_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> None:
    if not await guard(update):
        return
    typed = (update.effective_message.text or "").strip()
    path = draft.get("path")

    if typed != backup.RESTORE_TOKEN:
        await db.clear_session(update.effective_user.id)
        if path and os.path.exists(path):
            os.remove(path)
        await update.effective_message.reply_text("Cancelled. Nothing was changed.")
        return

    await update.effective_message.reply_text("Restoring...")
    try:
        summary = await backup.apply_restore(path)
    except Exception as exc:
        await update.effective_message.reply_text(
            f"Restore failed: {exc}\nThe live database was not replaced."
        )
        return
    finally:
        if path and os.path.exists(path):
            os.remove(path)

    await db.clear_session(update.effective_user.id)
    await update.effective_message.reply_text(summary, reply_markup=kb.back_to("admin:home"))
