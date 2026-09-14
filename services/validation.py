"""Marks validation.

With 0.25 negative marking:

    marks = correct - 0.25 * wrong
          = correct - 0.25 * (attempted - correct)
          = 1.25 * correct - 0.25 * attempted

So for a given number of attempted questions only a fixed set of scores is
arithmetically possible. Anything else is a typo or a fake entry, and it is
rejected at the point of entry rather than cleaned up later.
"""

from typing import Optional

import config

STEP = config.NEGATIVE_MARK          # 0.25
FACTOR = 1 + config.NEGATIVE_MARK    # 1.25


def parse_number(raw: str) -> Optional[float]:
    raw = raw.strip().replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def validate_attempted(value: float, max_q: int) -> Optional[str]:
    if value != int(value):
        return "Attempted questions must be a whole number."
    if not (0 <= int(value) <= max_q):
        return "range"
    return None


def correct_from_marks(marks: float, attempted: int) -> Optional[int]:
    """Return the implied number of correct answers, or None if impossible."""
    raw = (marks + STEP * attempted) / FACTOR
    nearest = round(raw)
    if abs(raw - nearest) > 1e-6:
        return None
    if not (0 <= nearest <= attempted):
        return None
    return int(nearest)


def possible_scores(attempted: int) -> list[float]:
    """Every score achievable with this many attempts, low to high."""
    return [
        round(FACTOR * c - STEP * attempted, 2) for c in range(0, attempted + 1)
    ]


def nearest_possible(marks: float, attempted: int, how_many: int = 3) -> list[float]:
    scores = possible_scores(attempted)
    scores.sort(key=lambda s: abs(s - marks))
    picked = sorted(scores[:how_many])
    return picked


def validate_marks(marks: float, attempted: int, section: str) -> Optional[str]:
    """Return an error key, or None when the score is valid.

    Error keys: 'step', 'range', 'impossible'
    """
    lo, hi = (
        (config.GK_MIN, config.GK_MAX)
        if section == "gk"
        else (config.EN_MIN, config.EN_MAX)
    )

    if abs((marks / STEP) - round(marks / STEP)) > 1e-6:
        return "step"

    if not (lo - 1e-9 <= marks <= hi + 1e-9):
        return "range"

    if correct_from_marks(marks, attempted) is None:
        return "impossible"

    return None


def fmt(value: float) -> str:
    """Trim trailing zeros: 38.00 -> 38, 38.25 -> 38.25."""
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text if text else "0"
