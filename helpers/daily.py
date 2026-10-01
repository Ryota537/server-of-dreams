"""Daily-usage reset at 05:00 JST. ``DailyLimit`` tracks how many times each capped action
was used today (autoplay, lessons, free course challenges); when a data-fetch happens after
the day's reset boundary, those usage counters go back to zero and lastRefreshedAt advances.
"""

import datetime
import time

from db.user import get_daily_limits, update_daily_limit

_JST = datetime.timezone(datetime.timedelta(hours=9))
_MICRO = 1_000_000

# usage counters reset to zero at 05:00 JST
_USAGE_FIELDS = ("autoPlayTimes", "dailyLessonTimes", "musicCourseFreeChallengeTimes")


def most_recent_reset(now_micros: int) -> int:
    """Epoch-micros of the most recent 05:00 JST boundary at or before ``now``."""
    now = datetime.datetime.fromtimestamp(now_micros / _MICRO, _JST)
    boundary = now.replace(hour=5, minute=0, second=0, microsecond=0)
    if now < boundary:
        boundary -= datetime.timedelta(days=1)
    return int(boundary.timestamp() * _MICRO)


async def refresh_daily_limits(app, user_id) -> None:
    """Zero the caller's daily usage counters if the 05:00 JST reset has passed since the
    last refresh. No-op without a user / DailyLimit row, or if already refreshed.
    """
    if user_id is None:
        return
    now = int(time.time() * _MICRO)
    async with app.acquire_db() as conn:
        row = await conn.fetchrow(get_daily_limits(user_id))
        if row is None or (row.lastRefreshedAt or 0) >= most_recent_reset(now):
            return
        data = row.model_dump()
        for field in _USAGE_FIELDS:
            data[field] = 0
        data["lastRefreshedAt"] = now
        await conn.execute(update_daily_limit(user_id, data))
