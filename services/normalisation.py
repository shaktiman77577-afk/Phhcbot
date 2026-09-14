"""Estimated shift adjustment.

This is NOT normalisation. Real normalisation needs every candidate who sat
the exam; this works from the few hundred or few thousand who submitted here.
What it does is bracket the likely adjustment using two independent methods
and report the range between them.

Method A - SSC-shaped linear map
    adjusted = factor * (raw - G) + G
    factor   = (overall_anchor - G) / (shift_anchor - G)
    G        = mean + 1 standard deviation of the whole pool
    anchor   = 95th percentile (the real formula uses the top 0.1%, which a
               sample this size cannot produce)

Method B - median equating
    adjusted = raw + (overall_median - shift_median)

The two disagree in a way worth understanding. Method A pivots around G and
stretches the distribution away from it, so in a hard shift it lifts
candidates above G and pushes those below G further down. Method B shifts
everyone by the same amount. Near the cutoff - which is the only region that
decides anything - both point the same way, and the spread between them is an
honest measure of how unsure the estimate is.
"""

import statistics

import config
from services import analytics

MIN_N = 25           # below this a shift gets no estimate at all
TOP_FRACTION = 0.10  # anchor = mean of the top 10%, standing in for top 0.1%
MIN_TOP_N = 5        # but always average at least this many scores
CLAMP = 10.0         # the linear map explodes near G; never report beyond this
MIN_SPREAD = 2.0     # anchor must clear G by this much or the factor is junk
FACTOR_BOUNDS = (0.5, 2.0)   # outside this the map has broken down
FLAT_BAND = 0.75     # adjustments smaller than this are reported as no change
WIDE_RANGE = 5.0     # a spread this wide gets an extra warning to the student


def top_mean(values: list[float]) -> float | None:
    """Mean of the top slice. More stable on small samples than a single
    percentile point, and closer in spirit to the official top 0.1% average."""
    if not values:
        return None
    ordered = sorted(values, reverse=True)
    take = max(MIN_TOP_N, int(round(len(ordered) * TOP_FRACTION)))
    slice_ = ordered[: min(take, len(ordered))]
    return round(statistics.mean(slice_), 3)


def pool_anchor(pool: analytics.Pool) -> tuple[float, float] | None:
    """Returns (G, overall_anchor), or None if the pool is too small."""
    if len(pool.totals) < MIN_N:
        return None
    mean = statistics.mean(pool.totals)
    sd = statistics.pstdev(pool.totals) if len(pool.totals) > 1 else 0.0
    g = mean + sd
    anchor = top_mean(pool.totals)
    if anchor is None:
        return None
    return round(g, 3), anchor


def _clamp(value: float) -> float:
    return max(-CLAMP, min(CLAMP, value))


def estimate(
    pool: analytics.Pool, date: str, shift: int, raw: float | None = None
) -> dict:
    """Estimated adjustment for one shift, optionally at one candidate's score."""
    result = {
        "status": "insufficient",
        "date": date,
        "shift": shift,
        "n": 0,
        "direction": "flat",
    }

    values = pool.by_shift.get((date, shift), [])
    result["n"] = len(values)
    if len(values) < MIN_N:
        return result

    base = pool_anchor(pool)
    if base is None:
        return result
    g, overall_anchor = base

    shift_anchor = top_mean(values)
    shift_median = analytics.trimmed_median(values)
    overall_median = pool.overall_median
    if shift_anchor is None or shift_median is None or overall_median is None:
        return result

    result.update(
        {
            "g": g,
            "overall_anchor": overall_anchor,
            "shift_anchor": shift_anchor,
            "shift_median": shift_median,
            "overall_median": overall_median,
            "gap": round(shift_median - overall_median, 2),
        }
    )

    # Method B works regardless; method A needs the shift anchor clear of G.
    equate = round(overall_median - shift_median, 2)
    result["equate"] = equate

    # The map divides by (shift_anchor - G). If a shift is brutal enough that
    # even its top slice falls to or below G, that denominator goes small or
    # negative and the whole thing inverts. Catch it rather than clamp it.
    spread_ok = (shift_anchor - g) >= MIN_SPREAD and (overall_anchor - g) >= MIN_SPREAD
    factor = (
        (overall_anchor - g) / (shift_anchor - g) if spread_ok else None
    )
    factor_ok = factor is not None and FACTOR_BOUNDS[0] <= factor <= FACTOR_BOUNDS[1]

    if not factor_ok:
        # Only equating survives. Report a band around that value rather than
        # stretching from zero, which would produce a uselessly wide range.
        result["status"] = "unreliable"
        result["factor"] = round(factor, 4) if factor is not None else None
        margin = max(1.0, abs(equate) * 0.3)
        result["low"] = round(_clamp(equate - margin), 2)
        result["high"] = round(_clamp(equate + margin), 2)
    else:
        result["factor"] = round(factor, 4)
        result["status"] = "ok"

        def method_a(score: float) -> float:
            return _clamp(factor * (score - g) + g - score)

        result["adj_at_median"] = round(method_a(shift_median), 2)
        cutoff_zone = analytics.percentile_value(pool.totals, 90) or shift_median
        result["adj_at_cutoff"] = round(method_a(cutoff_zone), 2)
        result["cutoff_zone"] = cutoff_zone

        point = raw if raw is not None else cutoff_zone
        a = method_a(point)
        b = _clamp(equate)
        result["low"] = round(min(a, b), 2)
        result["high"] = round(max(a, b), 2)

    low, high = result["low"], result["high"]
    midpoint = (low + high) / 2

    # A range straddling zero means the two methods disagree on direction.
    # Saying "up" on that would be inventing confidence we do not have.
    if low < -FLAT_BAND and high > FLAT_BAND:
        result["direction"] = "unclear"
    elif midpoint > FLAT_BAND:
        result["direction"] = "up"
    elif midpoint < -FLAT_BAND:
        result["direction"] = "down"
    else:
        result["direction"] = "flat"

    return result


def all_estimates(pool: analytics.Pool) -> list[dict]:
    out = []
    for date in config.EXAM_DATES:
        for shift in config.SHIFTS:
            row = estimate(pool, date, shift)
            if row["n"]:
                out.append(row)
    out.sort(key=lambda r: -(r.get("high") or 0))
    return out


def student_line(result: dict) -> str:
    """One short, honest paragraph for the candidate's result card."""
    if result["status"] == "insufficient":
        return (
            "\n\nShift adjustment: not enough submissions from your shift yet. "
            "Check back later as more candidates submit."
        )

    gap = abs(result["gap"])
    side = "below" if result["gap"] < 0 else "above"
    if result["gap"] == 0:
        side = "level with"

    lines = [
        "\n\nShift adjustment estimate",
        f"Your shift's median was {gap} marks {side} the overall median across "
        "all shifts. SSSC normalises scores across shifts for exactly this "
        "reason.",
    ]

    low, high = result["low"], result["high"]
    lo_s, hi_s = sorted((abs(low), abs(high)))
    if result["direction"] == "up":
        lines.append(
            f"Based on the data submitted so far, your score is more likely to "
            f"be adjusted upward than downward, by roughly {lo_s:.1f} to "
            f"{hi_s:.1f} marks."
        )
    elif result["direction"] == "down":
        lines.append(
            f"Your shift scored above average, so an adjustment downward is "
            f"more likely than upward, by roughly {lo_s:.1f} to {hi_s:.1f} marks."
        )
    elif result["direction"] == "unclear":
        lines.append(
            "The two ways of estimating this disagree on your shift, so no "
            "direction can be given honestly. More submissions from your shift "
            "will settle it."
        )
    else:
        lines.append(
            "Your shift sat close to the overall average, so the adjustment "
            "either way is likely to be small."
        )

    if result["status"] == "unreliable":
        lines.append(
            "Only one of the two estimating methods worked on your shift, so "
            "treat this as a rough indication rather than a figure."
        )
    elif (high - low) > WIDE_RANGE:
        lines.append(
            "The range is wide, which means the estimate is not yet settled. "
            "It will narrow as more candidates from your shift submit."
        )

    lines.append(
        "This is an estimate from submitted data only, not a prediction. The "
        "official calculation uses every candidate who sat the exam and will "
        "differ from this."
    )
    return "\n".join(lines)
