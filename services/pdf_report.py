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
from services import analytics, normalisation
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


# ===============================================================
# Detailed internal report
#
# Admin only. Carries the full analysis but no candidate identity:
# no names, no roll numbers, no Telegram ids. A PDF gets forwarded,
# a CSV does not, so the identified data stays in the CSV export.
# ===============================================================
def _table(rows: list[list[str]], header_colour=BRAND, font_size: float = 8.5) -> Table:
    table = Table(rows, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_colour),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ]
        )
    )
    return table


def _bar(value: float, peak: float, width: int = 22) -> str:
    if peak <= 0:
        return ""
    return "#" * max(1, int(round(width * value / peak))) if value else ""


async def build_detailed() -> tuple[bytes, str]:
    """Full internal analysis. Returns (pdf_bytes, filename)."""
    pool = await analytics.load_pool()
    frozen = await db.get_config("frozen_difficulty", {}) or {}
    keys = await db.answer_key_slots()
    registered = await db.count_where()
    anonymised = await db.anonymised_count()
    flagged = await db.flagged_rows()
    st = _styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"{config.EXAM_NAME} Internal Analysis",
        author=config.BRAND_NAME,
    )

    warning = ParagraphStyle(
        "warn",
        fontSize=11,
        textColor=colors.white,
        backColor=colors.HexColor("#C62828"),
        alignment=1,
        borderPadding=6,
        spaceAfter=12,
        fontName="Helvetica-Bold",
    )

    story = [
        Paragraph("INTERNAL - NOT FOR CIRCULATION", warning),
        Paragraph(config.BRAND_NAME, st["title"]),
        Paragraph(
            f"{config.EXAM_NAME} - Detailed Analysis<br/>"
            f"{dt.datetime.now(config.IST).strftime('%d %b %Y, %I:%M %p')} IST",
            st["sub"],
        ),
    ]

    # --- 1. headline numbers ---
    story.append(Paragraph("1. Summary", st["h2"]))
    story.append(
        _table(
            [
                ["Metric", "Value"],
                ["Registered", str(registered)],
                ["Submitted", str(pool.n)],
                [
                    "Submission rate",
                    f"{round(100.0 * pool.n / registered, 1)}%" if registered else "-",
                ],
                [
                    "Overall median",
                    fmt(pool.overall_median) if pool.overall_median is not None else "-",
                ],
                ["Shifts with data", str(len([1 for k, v in pool.by_shift.items() if v]))],
                [
                    "Answer keys",
                    f"{len(keys)} / {len(config.EXAM_DATES) * len(config.SHIFTS)}",
                ],
                ["Anonymised on request", str(anonymised)],
                ["Excluded as outliers", str(len(flagged))],
            ],
            font_size=9,
        )
    )

    # --- 2. shift ranking ---
    story.append(Paragraph("2. Shift ranking, hardest first", st["h2"]))
    ranking = pool.shift_ranking(frozen)
    if not ranking:
        story.append(Paragraph("Not enough data in any shift yet.", st["body"]))
    else:
        rows = [["Rank", "Date", "Shift", "n", "Median", "vs overall", "Avg att.", "Level"]]
        for i, r in enumerate(ranking, start=1):
            rows.append(
                [
                    str(i),
                    config.DATE_LABELS[r["date"]],
                    f"S{r['shift']}",
                    str(r["n"]),
                    fmt(r["median"]),
                    f"{'+' if r['delta'] > 0 else ''}{fmt(r['delta'])}",
                    str(r["avg_attempted"] or "-"),
                    r["difficulty"],
                ]
            )
        story.append(_table(rows))
        story.append(Spacer(1, 5))
        story.append(
            Paragraph(
                "Average attempted is the second signal. A shift where "
                "candidates attempted fewer questions was usually harder, even "
                "when the median looks ordinary, because a difficult paper makes "
                "people leave questions rather than risk the negative mark.",
                st["note"],
            )
        )

    # --- 3. distribution ---
    story.append(Paragraph("3. Score distribution", st["h2"]))
    dist = pool.score_distribution()
    peak = max((n for _, n, _ in dist), default=0)
    story.append(
        _table(
            [["Range", "Candidates", "Share", ""]]
            + [[label, str(n), f"{pct}%", _bar(n, peak)] for label, n, pct in dist],
            header_colour=ACCENT,
            font_size=9,
        )
    )

    # --- 4. category x shift ---
    story.append(Paragraph("4. Category median by shift", st["h2"]))
    matrix = pool.shift_category_matrix()
    if not matrix:
        story.append(Paragraph("No shift has enough category data yet.", st["body"]))
    else:
        rows = [["Date", "Shift", "n"] + config.CATEGORIES]
        for r in matrix:
            rows.append(
                [config.DATE_LABELS[r["date"]], f"S{r['shift']}", str(r["n"])]
                + [fmt(r[c]) if r[c] is not None else "-" for c in config.CATEGORIES]
            )
        story.append(_table(rows, font_size=8))
        story.append(Spacer(1, 5))
        story.append(
            Paragraph(
                "A dash means fewer than 5 entries for that category in that "
                "shift, which is too thin to report.",
                st["note"],
            )
        )

    # --- 5. centres ---
    story.append(Paragraph("5. Centre wise", st["h2"]))
    centres = pool.centre_stats()
    if not centres:
        story.append(
            Paragraph(
                "No centre data. The centre question is optional and asked "
                "after registration completes.",
                st["body"],
            )
        )
    else:
        peak_n = max(r["n"] for r in centres)
        story.append(
            _table(
                [["Centre", "Entries", "Median", "High", ""]]
                + [
                    [
                        r["centre"],
                        str(r["n"]),
                        fmt(r["median"]) if r["median"] is not None else "-",
                        fmt(r["high"]),
                        _bar(r["n"], peak_n, 16),
                    ]
                    for r in centres
                ],
                header_colour=ACCENT,
                font_size=9,
            )
        )

    # --- 6. timeline ---
    story.append(Paragraph("6. Submissions by day", st["h2"]))
    timeline = pool.daily_timeline()
    if not timeline:
        story.append(Paragraph("No submissions recorded yet.", st["body"]))
    else:
        peak_d = max(n for _, n in timeline)
        story.append(
            _table(
                [["Date (IST)", "Submissions", ""]]
                + [
                    [
                        dt.date.fromisoformat(day).strftime("%d %b"),
                        str(n),
                        _bar(n, peak_d),
                    ]
                    for day, n in timeline
                ],
                header_colour=ACCENT,
                font_size=9,
            )
        )

    # --- 7. estimated shift adjustment ---
    story.append(Paragraph("7. Estimated shift adjustment", st["h2"]))
    base = normalisation.pool_anchor(pool)
    norm_rows = normalisation.all_estimates(pool)
    usable = [r for r in norm_rows if r["status"] != "insufficient"]

    if base is None or not usable:
        story.append(
            Paragraph(
                "Too few submissions to anchor an estimate. A shift needs at "
                f"least {normalisation.MIN_N} entries.",
                st["body"],
            )
        )
    else:
        g, anchor = base
        story.append(
            Paragraph(
                f"Pivot G (mean + 1 SD): <b>{fmt(g)}</b> &nbsp;&nbsp; "
                f"Overall top-decile anchor: <b>{fmt(anchor)}</b>",
                st["body"],
            )
        )
        story.append(Spacer(1, 5))
        rows = [
            ["Date", "Shift", "n", "Gap", "Factor", "At median", "At cutoff", "Range", "Lean"]
        ]
        for r in usable:
            rows.append(
                [
                    config.DATE_LABELS[r["date"]],
                    f"S{r['shift']}",
                    str(r["n"]),
                    f"{r['gap']:+}",
                    fmt(r["factor"]) if r.get("factor") else "-",
                    f"{r['adj_at_median']:+}" if r.get("adj_at_median") is not None else "-",
                    f"{r['adj_at_cutoff']:+}" if r.get("adj_at_cutoff") is not None else "-",
                    f"{r['low']:+} to {r['high']:+}",
                    r["direction"].upper(),
                ]
            )
        story.append(_table(rows, font_size=7.5))
        story.append(Spacer(1, 5))
        story.append(
            Paragraph(
                "<b>At median and At cutoff can carry opposite signs.</b> The "
                "linear map pivots around G and stretches the distribution away "
                "from it, so in a hard shift it lifts candidates above G while "
                "pushing those below G further down. Only the cutoff region "
                "decides selection, so At cutoff is the column that matters. "
                "Range is the spread between the SSC-shaped map and plain median "
                "equating; a wide spread means the estimate is not settled. A "
                "shift marked with a dash in Factor failed the sanity check - "
                "usually because even its strongest candidates fell to or below "
                "G - and is estimated from equating alone.",
                st["note"],
            )
        )

    # --- 8. key coverage ---
    story.append(Paragraph("8. Answer key coverage", st["h2"]))
    rows = [["Date"] + [f"Shift {s}" for s in config.SHIFTS]]
    for date in config.EXAM_DATES:
        rows.append(
            [config.DATE_LABELS[date]]
            + ["received" if (date, s) in keys else "missing" for s in config.SHIFTS]
        )
    story.append(_table(rows, font_size=9))

    story.append(Spacer(1, 14))
    story.append(
        Paragraph(
            "<b>Scope and limits.</b> Every figure comes from candidates who "
            "submitted their own marks, so this is not a random sample of all "
            "candidates and runs above the true population average. Medians are "
            "trimmed at 5 per cent each end. Entries that fail the arithmetic "
            "check for their attempt count are rejected at entry and never reach "
            "this report. SSSC normalises across shifts using the full candidate "
            "population, which cannot be reconstructed here, so no figure in this "
            "document is a predicted official score or cutoff.",
            st["note"],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "This document deliberately contains no candidate names, roll "
            "numbers or account identifiers. For identified data use the CSV "
            "export, which is not meant to leave the admin team.",
            st["note"],
        )
    )

    doc.build(story)
    buf.seek(0)
    name = (
        "INTERNAL_SelectionLab_Clerk_Analysis_"
        f"{dt.datetime.now(config.IST).strftime('%d%b_%H%M')}.pdf"
    )
    return buf.read(), name
