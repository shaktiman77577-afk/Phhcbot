"""Statistics over submitted scores.

Two deliberate choices:

1. Trimmed medians, not means. The top and bottom 5% of each shift are
   dropped before computing. A handful of joke entries at 69/70 then cannot
   move a shift's difficulty label.

2. Percentile within shift, not a normalised score. Real normalisation needs
   the full candidate population, which we will never have. Percentile is the
   honest version of the same idea.
"""

import datetime as dt
import statistics
from collections import defaultdict

import config
import db


def ist_date(iso: str | None) -> str | None:
    """Stored timestamps are UTC ISO strings. Report in IST."""
    if not iso:
        return None
    try:
        stamp = dt.datetime.fromisoformat(iso)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return stamp.astimezone(config.IST).date().isoformat()


def trimmed(values: list[float], frac: float = config.TRIM_FRACTION) -> list[float]:
    if len(values) < 10:
        return sorted(values)
    ordered = sorted(values)
    cut = int(len(ordered) * frac)
    if cut == 0:
        return ordered
    return ordered[cut:-cut] or ordered


def trimmed_median(values: list[float]) -> float | None:
    data = trimmed(values)
    if not data:
        return None
    return round(statistics.median(data), 2)


def percentile_of(values: list[float], score: float) -> float:
    """Percent of the pool scoring at or below `score`."""
    if not values:
        return 0.0
    at_or_below = sum(1 for v in values if v <= score)
    return round(100.0 * at_or_below / len(values), 1)


def percentile_value(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round((pct / 100.0) * (len(ordered) - 1)))
    return round(ordered[max(0, min(idx, len(ordered) - 1))], 2)


class Pool:
    """One pass over all submissions, sliced every way the bot needs."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.totals = [float(r["total_marks"]) for r in rows if r.get("total_marks") is not None]

        self.by_shift: dict[tuple[str, int], list[float]] = defaultdict(list)
        self.by_category: dict[str, list[float]] = defaultdict(list)
        self.attempts_by_shift: dict[tuple[str, int], list[int]] = defaultdict(list)
        self.by_centre: dict[str, list[float]] = defaultdict(list)
        self.by_shift_category: dict[tuple[str, int, str], list[float]] = defaultdict(list)
        self.by_day: dict[str, int] = defaultdict(int)

        for r in rows:
            if r.get("total_marks") is None:
                continue
            total = float(r["total_marks"])
            if r.get("exam_date") and r.get("shift"):
                key = (str(r["exam_date"]), int(r["shift"]))
                self.by_shift[key].append(total)
                att = (r.get("gk_attempted") or 0) + (r.get("en_attempted") or 0)
                self.attempts_by_shift[key].append(att)
            if r.get("category"):
                self.by_category[r["category"]].append(total)
            if r.get("centre"):
                self.by_centre[r["centre"]].append(total)
            if r.get("exam_date") and r.get("shift") and r.get("category"):
                self.by_shift_category[
                    (str(r["exam_date"]), int(r["shift"]), r["category"])
                ].append(total)
            day = ist_date(r.get("created_at"))
            if day:
                self.by_day[day] += 1

    @property
    def n(self) -> int:
        return len(self.totals)

    @property
    def overall_median(self) -> float | None:
        return trimmed_median(self.totals)

    def shift_stats(self, date: str, shift: int) -> dict:
        vals = self.by_shift.get((date, shift), [])
        return {
            "date": date,
            "shift": shift,
            "n": len(vals),
            "median": trimmed_median(vals),
            "high": round(max(vals), 2) if vals else None,
            "low": round(min(vals), 2) if vals else None,
            "avg_attempted": (
                round(statistics.mean(self.attempts_by_shift[(date, shift)]), 1)
                if self.attempts_by_shift.get((date, shift))
                else None
            ),
        }

    def all_shift_stats(self) -> list[dict]:
        out = []
        for date in config.EXAM_DATES:
            for shift in config.SHIFTS:
                out.append(self.shift_stats(date, shift))
        return out

    def difficulty(self, date: str, shift: int, frozen: dict | None = None) -> str:
        key = f"{date}|{shift}"
        if frozen and key in frozen:
            return frozen[key]

        stats = self.shift_stats(date, shift)
        if stats["n"] < config.MIN_N_FOR_DIFFICULTY or stats["median"] is None:
            return "Collecting data"

        overall = self.overall_median
        if overall is None:
            return "Collecting data"

        delta = stats["median"] - overall
        if delta >= config.EASY_THRESHOLD:
            return "Easy"
        if delta <= config.HARD_THRESHOLD:
            return "Hard"
        return "Moderate"

    def shift_ranking(self, frozen: dict | None = None, min_n: int = 5) -> list[dict]:
        """Every shift with a usable sample, hardest first."""
        out = []
        for date in config.EXAM_DATES:
            for shift in config.SHIFTS:
                stats = self.shift_stats(date, shift)
                if stats["n"] < min_n or stats["median"] is None:
                    continue
                stats["difficulty"] = self.difficulty(date, shift, frozen)
                overall = self.overall_median or stats["median"]
                stats["delta"] = round(stats["median"] - overall, 2)
                out.append(stats)
        out.sort(key=lambda r: r["median"])
        return out

    def score_distribution(self) -> list[tuple[str, int, float]]:
        """Bucketed counts. Returns (label, count, percent_of_pool)."""
        edges = [0, 10, 20, 30, 40, 50, 60, config.TOTAL_MARKS]
        buckets: list[tuple[str, int]] = []
        below = sum(1 for v in self.totals if v < 0)
        if below:
            buckets.append(("below 0", below))
        for lo, hi in zip(edges, edges[1:]):
            count = sum(1 for v in self.totals if lo <= v < hi)
            buckets.append((f"{lo} - {hi}", count))
        top = sum(1 for v in self.totals if v >= config.TOTAL_MARKS)
        if top:
            buckets.append((f"{config.TOTAL_MARKS}", top))

        total = len(self.totals) or 1
        return [(label, n, round(100.0 * n / total, 1)) for label, n in buckets]

    def centre_stats(self) -> list[dict]:
        out = []
        for centre in config.CENTRES:
            vals = self.by_centre.get(centre, [])
            if not vals:
                continue
            out.append(
                {
                    "centre": centre,
                    "n": len(vals),
                    "median": trimmed_median(vals),
                    "high": round(max(vals), 2),
                }
            )
        out.sort(key=lambda r: -r["n"])
        return out

    def shift_category_matrix(self, min_n: int = 5) -> list[dict]:
        """Per shift, the median for each category that has enough entries."""
        out = []
        for date in config.EXAM_DATES:
            for shift in config.SHIFTS:
                if not self.by_shift.get((date, shift)):
                    continue
                row = {"date": date, "shift": shift, "n": len(self.by_shift[(date, shift)])}
                for cat in config.CATEGORIES:
                    vals = self.by_shift_category.get((date, shift, cat), [])
                    row[cat] = trimmed_median(vals) if len(vals) >= min_n else None
                out.append(row)
        return out

    def daily_timeline(self) -> list[tuple[str, int]]:
        return sorted(self.by_day.items())

    def category_band(self, category: str) -> tuple[float, float] | None:
        vals = self.by_category.get(category, [])
        if len(vals) < config.MIN_N_FOR_CUTOFF:
            return None
        lo_pct, hi_pct = config.CUTOFF_BAND_PERCENTILES
        lo = percentile_value(vals, lo_pct)
        hi = percentile_value(vals, hi_pct)
        if lo is None or hi is None:
            return None
        return (lo, hi)

    def category_median(self, category: str) -> float | None:
        return trimmed_median(self.by_category.get(category, []))


async def load_pool() -> Pool:
    return Pool(await db.all_submissions())


async def freeze_stable_labels(pool: Pool) -> dict:
    """Lock a shift's difficulty label once its sample is large enough.

    Stops the public report flipping Hard -> Moderate -> Hard, which is the
    fastest way to lose the audience's trust in the numbers.
    """
    frozen = await db.get_config("frozen_difficulty", {}) or {}
    changed = False

    for date in config.EXAM_DATES:
        for shift in config.SHIFTS:
            key = f"{date}|{shift}"
            if key in frozen:
                continue
            stats = pool.shift_stats(date, shift)
            if stats["n"] >= config.MIN_N_TO_FREEZE:
                frozen[key] = pool.difficulty(date, shift)
                changed = True

    if changed:
        await db.set_config("frozen_difficulty", frozen)
    return frozen
