"""Inline keyboards. Callback data format: namespace:action:value"""

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup as M

import config


def main_menu(is_registered: bool, submission_open: bool, is_admin: bool) -> M:
    rows = []
    if not is_registered:
        rows.append([B("Register", callback_data="menu:register")])
    else:
        label = "Submit My Marks" if submission_open else "Submit My Marks (opens 4 PM)"
        rows.append([B(label, callback_data="menu:submit")])
        rows.append([B("My Result", callback_data="menu:result")])
    rows.append([B("Live Stats", callback_data="menu:stats")])
    rows.append([B("Answer Keys", callback_data="menu:keys")])
    rows.append([B("Share", callback_data="menu:share")])
    if is_admin:
        rows.append([B("Admin Panel", callback_data="admin:home")])
    return M(rows)


def dates(ns: str) -> M:
    rows, row = [], []
    for d in config.EXAM_DATES:
        row.append(B(config.DATE_LABELS[d], callback_data=f"{ns}:date:{d}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([B("Cancel", callback_data="menu:cancel")])
    return M(rows)


def shifts(ns: str) -> M:
    return M(
        [
            [B(f"Shift {s}", callback_data=f"{ns}:shift:{s}") for s in config.SHIFTS],
            [B("Cancel", callback_data="menu:cancel")],
        ]
    )


def categories() -> M:
    rows, row = [], []
    for c in config.CATEGORIES:
        row.append(B(c, callback_data=f"reg:category:{c}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([B("Cancel", callback_data="menu:cancel")])
    return M(rows)


def centres() -> M:
    rows, row = [], []
    for c in config.CENTRES:
        row.append(B(c, callback_data=f"reg:centre:{c}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([B("Skip", callback_data="reg:centre:skip")])
    return M(rows)


def confirm_submission() -> M:
    return M(
        [
            [
                B("Confirm", callback_data="sub:confirm"),
                B("Start Over", callback_data="sub:restart"),
            ]
        ]
    )


def key_grid(slots: dict) -> M:
    """24 slot grid. Filled slots are ticked."""
    rows = []
    for d in config.EXAM_DATES:
        row = []
        for s in config.SHIFTS:
            mark = "+" if (d, s) in slots else "-"
            row.append(
                B(
                    f"{config.DATE_LABELS[d]} S{s} {mark}",
                    callback_data=f"key:slot:{d}:{s}",
                )
            )
        rows.append(row)
    rows.append([B("Back", callback_data="menu:home")])
    return M(rows)


def share_button(link: str) -> M:
    text = (
        f"I am tracking my {config.EXAM_NAME} score here. "
        "Add yours so the cutoff estimate gets accurate."
    )
    url = f"https://t.me/share/url?url={link}&text={text.replace(' ', '%20')}"
    return M([[B("Share with your batchmates", url=url)]])


def admin_home() -> M:
    return M(
        [
            [B("Dashboard", callback_data="admin:dashboard")],
            [B("Shift Difficulty", callback_data="admin:shifts")],
            [B("Category Bands", callback_data="admin:bands")],
            [B("Answer Key Coverage", callback_data="admin:keys")],
            [B("Outlier Queue", callback_data="admin:outliers")],
            [B("PDF Report", callback_data="admin:pdf")],
            [B("CSV Export", callback_data="admin:csv")],
            [B("Publish / Update Report", callback_data="admin:publish_home")],
            [B("Open Submission Now", callback_data="admin:open_submission")],
            [
                B("Backup Now", callback_data="admin:backup"),
                B("Restore", callback_data="admin:restore"),
            ],
            [B("Back", callback_data="menu:home")],
        ]
    )


def admin_publish(published: bool, auto: bool) -> M:
    rows = []
    if not published:
        rows.append([B("Preview Post", callback_data="admin:preview")])
        rows.append([B("Publish to Group", callback_data="admin:publish")])
    else:
        rows.append([B("Update Now", callback_data="admin:update_now")])
        rows.append(
            [
                B(
                    "Pause Auto Update" if auto else "Resume Auto Update",
                    callback_data="admin:toggle_auto",
                )
            ]
        )
        rows.append([B("Detach Post", callback_data="admin:detach")])
    rows.append([B("Back", callback_data="admin:home")])
    return M(rows)


def back_to(where: str = "menu:home") -> M:
    return M([[B("Back", callback_data=where)]])
