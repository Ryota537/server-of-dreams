"""Live rate (the per-chart / player rating for Stella-or-lower charts).

A chart's live rate = its level + an achievement-based adjustment. Charts with no live rate:
Olivier (an Olivier play only updates achievement_rate_result, the raw
best %, never the live rating) and any chart of a long-version song (MusicMaster.is_long_version).
For those, live_rate_result is 0/0 (best_ever and this_time) and the total rate is unchanged
regardless of the result. The player's total rate is the sum of the best live rate of their
top 30 charts.

Achievement-rate -> adjustment breakpoints, LINEARLY interpolated between them (they are
knots on a piecewise-linear curve, not a step function):
  101.00% +6.05 | 100.95% +6.00 | 100.75% +4.50 | 100.50% +3.00 | 100.25% +2.25
  100.00% +1.50 |  99.00% +0.75 |  98.00% +0.00 |  97.50% -1.00
Clamped at both ends: >=101% is +6.05, <=97.50% is -1.00 (lower brackets aren't published).

Interpolation confirmed against captures: two charts, two achievement rates each, all four
solving to the same integer level per chart (100.9933%/100.9559% -> level 29; 100.7306%/
100.3794% -> level 31). A step function would not reproduce any of the four.
"""

import math
from typing import Optional

from helpers.cache import cache
from models.enums import ClearLamps, MusicDifficulties

_TOP_N = 30
_ADJUSTMENTS = (
    (101.00, 6.05),
    (100.95, 6.00),
    (100.75, 4.50),
    (100.50, 3.00),
    (100.25, 2.25),
    (100.00, 1.50),
    (99.00, 0.75),
    (98.00, 0.00),
    (97.50, -1.00),
)

_BY_ID: dict = {}
_MUSIC: dict = {}


def _build() -> None:
    if not _BY_ID:
        _BY_ID.update({m.id_: m for m in cache.live_master})
        _MUSIC.update({m.id_: m for m in cache.music_master})


def _rated_chart(live_master_id: int):
    """The chart if it participates in live rate -- Stella-or-lower difficulty and not a
    long-version song -- else None."""
    _build()
    lm = _BY_ID.get(live_master_id)
    if lm is None or int(lm.difficulty) > int(MusicDifficulties.Stella):
        return None
    music = _MUSIC.get(lm.music_master_id)
    if music is not None and music.is_long_version:
        return None
    return lm


def _adjustment(rate: float) -> float:
    # piecewise-LINEAR interpolation between the breakpoints (not a step function):
    # e.g. 100.358% between 100.25 (+2.25) and 100.50 (+3.00) -> +2.574
    if rate >= _ADJUSTMENTS[0][0]:
        return _ADJUSTMENTS[0][1]  # clamp above the top breakpoint (>=101% -> +6.05)
    if rate <= _ADJUSTMENTS[-1][0]:
        return _ADJUSTMENTS[-1][
            1
        ]  # floor below the bottom breakpoint (<=97.5% -> -1.00)
    for (hi_r, hi_a), (lo_r, lo_a) in zip(_ADJUSTMENTS, _ADJUSTMENTS[1:]):
        if lo_r <= rate <= hi_r:
            return lo_a + (rate - lo_r) / (hi_r - lo_r) * (hi_a - lo_a)
    return _ADJUSTMENTS[-1][1]


def live_rate(level: int, rate: float) -> float:
    # TRUNCATED to 2dp, not rounded
    return math.floor((level + _adjustment(rate)) * 100) / 100


def chart_live_rate(live_master_id: int, rate: float) -> Optional[float]:
    """A chart's live rate, or None if it has none (Olivier / long-version / unknown chart)."""
    lm = _rated_chart(live_master_id)
    return None if lm is None else live_rate(lm.level, rate)


def total_rate(pairs) -> float:
    """Sum of the top 30 chart live rates. ``pairs`` = iterable of (live_master_id, rate)."""
    rates = sorted(
        (
            r
            for r in (chart_live_rate(mid, rate) for mid, rate in pairs)
            if r is not None
        ),
        reverse=True,
    )
    return round(sum(rates[:_TOP_N]), 2)


def chart_live_rate_result(
    live_master_id: int, this_rate: float, prev_rate: float
) -> tuple[float, float]:
    """(best_ever, this_time) live rate for the finished chart. A chart with no live rate
    (Olivier / long-version) is (0.0, 0.0). ``best_ever`` is the PAST best only (excludes this
    play) -- 0 when never played before."""
    lm = _rated_chart(live_master_id)
    if lm is None:
        return 0.0, 0.0
    best_ever = live_rate(lm.level, prev_rate) if prev_rate > 0 else 0.0
    return best_ever, live_rate(lm.level, this_rate)


# --- Olivier star badge (SpRate) ---------------------------------------------------------
#
# Olivier charts (difficulty 5, levels 101-110 = ★1..★10) award star-badge points (SpRate)
# instead of a live rate. Points = base (by achievement rate x star level) + bonus (up to +8).
# The player's total SpRate is the sum of their best points per chart.

# base points, highest achievement-rate threshold first; columns are ★1..★10
_SP_RATE_BASE = (
    (100.95, (60, 70, 80, 90, 100, 110, 120, 130, 140, 150)),
    (100.90, (59, 69, 79, 89, 99, 109, 118, 128, 138, 148)),
    (100.85, (58, 68, 78, 88, 98, 108, 116, 126, 136, 146)),
    (100.80, (57, 67, 77, 87, 97, 106, 114, 124, 134, 144)),
    (100.75, (56, 66, 76, 86, 96, 104, 112, 122, 132, 142)),
    (100.70, (55, 65, 75, 85, 94, 102, 110, 120, 130, 140)),
    (100.60, (54, 64, 74, 84, 92, 100, 108, 118, 128, 138)),
    (100.50, (53, 63, 73, 82, 90, 98, 106, 116, 126, 135)),
    (100.40, (52, 62, 72, 80, 88, 96, 104, 114, 124, 132)),
    (100.30, (51, 61, 70, 78, 86, 94, 102, 112, 121, 129)),
    (100.20, (50, 60, 68, 76, 84, 92, 100, 110, 118, 126)),
    (100.10, (49, 58, 66, 74, 82, 90, 98, 107, 115, 123)),
    (100.00, (48, 56, 64, 72, 80, 88, 96, 104, 112, 120)),
    (99.00, (43, 50, 57, 64, 71, 78, 85, 92, 99, 106)),
    (98.00, (41, 48, 55, 62, 68, 75, 82, 89, 96, 102)),
    (97.00, (36, 42, 48, 54, 59, 65, 71, 77, 83, 88)),
    (96.00, (34, 40, 46, 52, 56, 62, 68, 74, 80, 84)),
    (95.00, (32, 38, 44, 50, 53, 59, 65, 71, 77, 81)),
    (94.00, (27, 32, 37, 42, 44, 49, 54, 59, 64, 67)),
    (93.00, (25, 30, 35, 40, 42, 46, 51, 56, 61, 64)),
    (92.00, (23, 28, 33, 38, 40, 43, 48, 53, 58, 61)),
    (91.00, (21, 26, 31, 36, 38, 40, 45, 50, 55, 58)),
    (90.00, (19, 24, 29, 34, 36, 38, 42, 47, 52, 55)),
    (89.00, (14, 18, 22, 26, 27, 28, 31, 35, 39, 41)),
    (80.00, (5, 6, 7, 8, 9, 10, 11, 12, 13, 14)),
)
# loss-count (notes judged below PERFECT*) thresholds, +1 for each the play is at or under
_SP_RATE_LOSS_THRESHOLDS = (10, 30, 50, 75, 100)


def _sp_rate_base(stella_lv: int, rate: float) -> int:
    for threshold, points in _SP_RATE_BASE:
        if rate >= threshold:
            return points[stella_lv - 1]
    return 0  # below the lowest bracket earns no base points


def _sp_rate_bonus(clear_lamp: int, loss_count: int) -> int:
    bonus = 0
    if clear_lamp >= int(ClearLamps.AllPerfect):
        bonus += 3
    elif clear_lamp >= int(ClearLamps.FullCombo):
        bonus += 2
    bonus += sum(1 for t in _SP_RATE_LOSS_THRESHOLDS if loss_count <= t)
    return bonus


def olivier_sp_rate_points(
    live_master_id: int, rate: float, clear_lamp: int, loss_count: int
) -> Optional[int]:
    """Star-badge points for an Olivier (difficulty 5) clear, or None if the chart isn't an
    Olivier chart. ``loss_count`` is the number of notes judged below PERFECT*."""
    _build()
    lm = _BY_ID.get(live_master_id)
    if lm is None or int(lm.difficulty) != int(MusicDifficulties.Olivier):
        return None
    stella_lv = lm.level - 100
    if not 1 <= stella_lv <= 10:
        return None
    return _sp_rate_base(stella_lv, rate) + _sp_rate_bonus(clear_lamp, loss_count)
