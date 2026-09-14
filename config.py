"""Configuration and exam constants."""

import datetime as dt
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", "0") or 0)
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
}

# --- Storage ---
# MUST sit on a mounted Railway Volume. Railway's container filesystem is
# ephemeral: without a volume at this mount point, every redeploy deletes the
# database and every submission in it.
DB_PATH = os.getenv("DB_PATH", "/data/bot.db")

# Where automatic backups are sent. Defaults to the first admin's DM.
BACKUP_CHAT_ID = int(os.getenv("BACKUP_CHAT_ID", "0") or 0) or (
    min(ADMIN_IDS) if ADMIN_IDS else 0
)
BACKUP_INTERVAL_HOURS = float(os.getenv("BACKUP_INTERVAL_HOURS", "2"))

# --- Timing ---
IST = ZoneInfo("Asia/Kolkata")

# Submission unlocks at this time ON THIS DATE, not at this time on whatever
# day the bot happens to be running. Without the date, deploying early would
# auto-open submission at 4 PM that same day.
SUBMISSION_OPEN_DATE = os.getenv("SUBMISSION_OPEN_DATE", "")  # YYYY-MM-DD
SUBMISSION_OPEN_HOUR = int(os.getenv("SUBMISSION_OPEN_HOUR", "16"))
SUBMISSION_OPEN_MINUTE = int(os.getenv("SUBMISSION_OPEN_MINUTE", "0"))


def submission_unlock_at() -> "dt.datetime | None":
    """The exact IST moment submission opens, or None if no date is set."""
    if not SUBMISSION_OPEN_DATE:
        return None
    try:
        day = dt.date.fromisoformat(SUBMISSION_OPEN_DATE.strip())
    except ValueError:
        return None
    return dt.datetime(
        day.year,
        day.month,
        day.day,
        SUBMISSION_OPEN_HOUR,
        SUBMISSION_OPEN_MINUTE,
        tzinfo=IST,
    )


def unlock_label() -> str:
    moment = submission_unlock_at()
    if moment is None:
        return "a time we will announce"
    return moment.strftime("%d %b at %I:%M %p").replace(" 0", " ")


REPORT_MIN_SUBMISSIONS = int(os.getenv("REPORT_MIN_SUBMISSIONS", "100"))
REPORT_REFRESH_SECONDS = 300          # 5 min, safely inside Telegram edit limits
BROADCAST_BATCH = 20                  # messages drained per tick
BROADCAST_TICK_SECONDS = 5            # ~4 messages/sec, well under the cap

# ---------------------------------------------------------------
# Exam constants, Advt. No. 36C/SSSC/HR/2026
# ---------------------------------------------------------------
EXAM_DATES = [
    "2026-08-24",
    "2026-08-25",
    "2026-08-26",
    "2026-08-31",
    "2026-09-01",
    "2026-09-02",
    "2026-09-04",
    "2026-09-07",
]

DATE_LABELS = {
    "2026-08-24": "24 Aug",
    "2026-08-25": "25 Aug",
    "2026-08-26": "26 Aug",
    "2026-08-31": "31 Aug",
    "2026-09-01": "1 Sep",
    "2026-09-02": "2 Sep",
    "2026-09-04": "4 Sep",
    "2026-09-07": "7 Sep",
}

SHIFTS = [1, 2, 3]

CENTRES = [
    "Amritsar",
    "Bathinda",
    "Ludhiana",
    "Mohali",
    "Patiala",
    "Jalandhar",
    "Faridabad",
    "Gurugram",
    "Ambala",
]

CATEGORIES = ["Gen", "SC", "BC-A", "BC-B", "EWS", "ESM"]

# Paper pattern. Change these two numbers if the 2026 corrigendum altered the
# split; every range, validation rule and report figure derives from them.
GK_QUESTIONS = 50
EN_QUESTIONS = 20
TOTAL_MARKS = GK_QUESTIONS + EN_QUESTIONS
NEGATIVE_MARK = 0.25

GK_MIN = -GK_QUESTIONS * NEGATIVE_MARK      # -12.5
GK_MAX = float(GK_QUESTIONS)                # 50.0
EN_MIN = -EN_QUESTIONS * NEGATIVE_MARK      # -5.0
EN_MAX = float(EN_QUESTIONS)                # 20.0

# ---------------------------------------------------------------
# Analytics tuning
# ---------------------------------------------------------------
TRIM_FRACTION = 0.05          # drop top and bottom 5% before taking the median
MIN_N_FOR_DIFFICULTY = 20     # below this a shift shows "Collecting data"
MIN_N_TO_FREEZE = 50          # difficulty label locks once a shift passes this
MIN_N_FOR_CUTOFF = 30         # below this a category shows no band
EASY_THRESHOLD = 3.0          # marks above overall median to call a shift Easy
HARD_THRESHOLD = -3.0         # marks below overall median to call a shift Hard
CUTOFF_BAND_PERCENTILES = (85, 92)

BRAND_NAME = "SelectionLab"
EXAM_NAME = "Haryana Court Clerk 2026"
