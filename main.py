"""Entry point."""

import datetime as dt
import logging
import os

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import config
import db
import router
import texts
from handlers import admin, common, registration, stats
from services import backup, broadcast, report

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


async def open_submission_job(context) -> None:
    """Flip the submission window at 4 PM IST and notify everyone once."""
    try:
        if await db.get_config("submission_open", False) is True:
            return

        unlock = config.submission_unlock_at()
        if unlock is None:
            return  # no SUBMISSION_OPEN_DATE set, admin opens it manually
        if dt.datetime.now(config.IST) < unlock:
            return

        await db.set_config("submission_open", True)
        count = await broadcast.enqueue_all(texts.SUBMISSION_OPEN_BROADCAST)
        log.info("Submission window opened, %s notifications queued", count)

        for admin_id in config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"Submission window opened automatically. "
                    f"{count} notifications queued.",
                )
            except Exception:
                pass
    except Exception:
        log.exception("open_submission_job failed")


async def report_threshold_job(context) -> None:
    """Nudge the admin once the pool is big enough to publish."""
    try:
        if await db.get_config("report_message_id"):
            return
        if await db.get_config("threshold_notified", False) is True:
            return

        submitted = await db.count_where(status="submitted")
        if submitted < config.REPORT_MIN_SUBMISSIONS:
            return

        await db.set_config("threshold_notified", True)
        for admin_id in config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"{submitted} submissions received. The report is ready to "
                    "preview. Open the admin panel to review and publish.",
                )
            except Exception:
                pass
    except Exception:
        log.exception("report_threshold_job failed")


async def cmd_menu(update, context) -> None:
    await common.show_menu(update, context)


async def cmd_cancel(update, context) -> None:
    await db.clear_session(update.effective_user.id)
    await update.effective_message.reply_text(texts.CANCELLED)
    await common.show_menu(update, context)


async def _on_startup(app: Application) -> None:
    await db.init()
    counts = await db.table_counts()
    log.info(
        "Loaded %s candidates, %s answer keys",
        counts["candidates"],
        counts["answer_keys"],
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await app.bot.send_message(
                admin_id,
                "Bot started.\n"
                f"Database: {config.DB_PATH}\n"
                f"Candidates on file: {counts['candidates']}\n"
                f"Submission unlocks: {config.unlock_label()}",
            )
        except Exception:
            pass


async def _on_shutdown(app: Application) -> None:
    try:
        await backup.send_backup(
            app.bot, config.BACKUP_CHAT_ID, note="Shutdown backup"
        )
    except Exception:
        log.exception("Shutdown backup failed")
    await db.close()


def build() -> Application:
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", registration.cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("stats", stats.live_stats))
    app.add_handler(CommandHandler("deletemydata", stats.cmd_delete))

    app.add_handler(CommandHandler("admin", admin.home))
    app.add_handler(CommandHandler("broadcast", admin.cmd_broadcast))
    app.add_handler(CommandHandler("flag", admin.cmd_flag))
    app.add_handler(CommandHandler("unflag", admin.cmd_unflag))

    app.add_handler(CallbackQueryHandler(router.callback_router))
    app.add_handler(MessageHandler(filters.Document.ALL, router.document_router))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, router.text_router)
    )

    jq = app.job_queue
    jq.run_repeating(report.refresh_job, interval=config.REPORT_REFRESH_SECONDS, first=120)
    jq.run_repeating(broadcast.drain_job, interval=config.BROADCAST_TICK_SECONDS, first=15)
    jq.run_repeating(open_submission_job, interval=60, first=10)
    jq.run_repeating(report_threshold_job, interval=180, first=60)
    jq.run_repeating(
        backup.backup_job,
        interval=int(config.BACKUP_INTERVAL_HOURS * 3600),
        first=300,
    )

    return app


if __name__ == "__main__":
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set. Copy .env.example to .env first.")

    volume_dir = os.path.dirname(config.DB_PATH)
    if volume_dir and not os.path.isdir(volume_dir):
        log.warning(
            "=" * 60 + "\n"
            "%s does not exist. On Railway this means the VOLUME IS NOT "
            "MOUNTED and every submission will be lost on the next redeploy. "
            "Attach a volume at this mount path before going live.\n" + "=" * 60,
            volume_dir,
        )
    log.info("Starting %s score bot", config.EXAM_NAME)
    build().run_polling(drop_pending_updates=False)
