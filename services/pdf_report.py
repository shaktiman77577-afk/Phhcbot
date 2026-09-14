"""SelectionLab branded PDF report.

PDFs get forwarded on WhatsApp far more than Telegram posts do, so this is
the version with the real reach.
"""

import datetime as dt
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import config
import db
from services import analytics
from services.validation import fmt

BRAND = colors.HexColor("#1B4965")
ACCENT = colors.HexColor("#5FA8D3")
LIGHT = colors.HexColor("#EAF2F8")

DIFFICULTY_COLOUR = {
    "Easy": colors.HexColor("#2E7D32"),
    "Moderate": colors.HexColor("#EF6C00"),
    "Hard": colors.HexColor("#C62828"),
    "Collecting data": colors.HexColor("#9E9E9E"),
}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], textColor=BRAND, fontSize=20, spaceAfter=4
        ),
        "sub": ParagraphStyle(
            "s",
            parent=base["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#555555"),
            alignment=1,
            spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "h",
            parent=base["Heading2"],
            textColor=BRAND,
            fontSize=13,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=9.5, leading=13),
        "note": ParagraphStyle(
            "n",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#777777"),
            leading=11,
        ),
    }


async def build(single_shift: tuple[str, int] | None = None) -> tuple[bytes, str]:
    """Returns (pdf_bytes, filename)."""
    pool = await analytics.load_pool()
    frozen = await db.get_config("frozen_difficulty", {}) or {}
    keys = await db.answer_key_slots()
    st = _styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"{config.EXAM_NAME} Score Report",
        author=config.BRAND_NAME,
    )

    story = [
        Paragraph(f"{config.BRAND_NAME}", st["title"]),
        Paragraph(
            f"{config.EXAM_NAME} - Score Report<br/>"
            f"{pool.n} submissions  |  generated "
            f"{dt.datetime.now(config.IST).strftime('%d %b %Y, %I:%M %p')} IST",
            st["sub"],
        ),
    ]

    overall = pool.overall_median
    if overall is not None:
        story.append(Paragraph("Overall", st["h2"]))
        story.append(
            Paragraph(
                f"Median score across all shifts: <b>{fmt(overall)} / 70</b>",
                st["body"],
            )
        )

    # --- shift table ---
    story.append(Paragraph("Shift wise breakdown", st["h2"]))

    targets = (
        [single_shift]
        if single_shift
        else [(d, s) for d in config.EXAM_DATES for s in config.SHIFTS]
    )

    head = ["Date", "Shift", "Entries", "Median", "High", "Low", "Avg Att.", "Level"]
    rows = [head]
    colour_rows = []
    for idx, (date, shift) in enumerate(targets, start=1):
        stats = pool.shift_stats(date, shift)
        if stats["n"] == 0 and not single_shift:
            continue
        label = pool.difficulty(date, shift, frozen)
        colour_rows.append((idx, label))
        rows.append(
            [
                config.DATE_LABELS[date],
                f"S{shift}",
                str(stats["n"]),
                fmt(stats["median"]) if stats["median"] is not None else "-",
                fmt(stats["high"]) if stats["high"] is not None else "-",
                fmt(stats["low"]) if stats["low"] is not None else "-",
                str(stats["avg_attempted"]) if stats["avg_attempted"] else "-",
                label,
            ]
        )

    if len(rows) == 1:
        story.append(Paragraph("No submissions recorded yet.", st["body"]))
    else:
        table = Table(rows, repeatRows=1, hAlign="LEFT")
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for row_idx, label in colour_rows:
            if row_idx < len(rows):
                style.append(
                    ("TEXTCOLOR", (7, row_idx), (7, row_idx), DIFFICULTY_COLOUR[label])
                )
                style.append(
                    ("FONTNAME", (7, row_idx), (7, row_idx), "Helvetica-Bold")
                )
        table.setStyle(TableStyle(style))
        story.append(table)

    # --- category bands ---
    story.append(Paragraph("Expected cutoff band by category", st["h2"]))
    band_rows = [["Category", "Entries", "Median", "Expected band"]]
    for cat in config.CATEGORIES:
        vals = pool.by_category.get(cat, [])
        band = pool.category_band(cat)
        median = pool.category_median(cat)
        band_rows.append(
            [
                cat,
                str(len(vals)),
                fmt(median) if median is not None else "-",
                f"{fmt(band[0])} - {fmt(band[1])}" if band else "Not enough data",
            ]
        )
    band_table = Table(band_rows, repeatRows=1, hAlign="LEFT")
    band_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(band_table)

    story.append(Paragraph("Answer key coverage", st["h2"]))
    story.append(
        Paragraph(
            f"{len(keys)} of {len(config.EXAM_DATES) * len(config.SHIFTS)} "
            "shift wise answer keys received.",
            st["body"],
        )
    )

    story.append(Spacer(1, 14))
    story.append(
        Paragraph(
            "<b>How to read this report.</b> All figures come from candidates who "
            "submitted their own marks in the bot, so the sample is not a random "
            "cross section of all candidates and tends to run above the true "
            "population average. Medians are trimmed, with the top and bottom 5 "
            "per cent of each shift removed, so a few extreme entries cannot "
            "distort a shift. SSSC normalises marks across shifts before preparing "
            "merit, and that calculation needs the full candidate population, so no "
            "normalised score can be computed here. The cutoff band is indicative "
            "only and is not a prediction of the official cutoff.",
            st["note"],
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"Prepared by {config.BRAND_NAME}. Not affiliated with SSSC or the "
            "High Court of Punjab and Haryana.",
            st["note"],
        )
    )

    doc.build(story)
    buf.seek(0)

    if single_shift:
        date, shift = single_shift
        name = f"SelectionLab_Clerk_{config.DATE_LABELS[date].replace(' ', '')}_S{shift}.pdf"
    else:
        name = (
            "SelectionLab_Haryana_Clerk_2026_Score_Report_"
            f"{dt.datetime.now(config.IST).strftime('%d%b_%H%M')}.pdf"
        )
    return buf.read(), name
