"""Live-drop resolution and granting.

A live's rewards come from a chain of masterdata:
    LiveSettingMaster.live_drop_frame_group_master_id
        -> LiveDropFrameGroupMaster.drop_frames  (the drop "frames" / slots)
            -> LiveDropFrameMaster.rewards        (the things that frame drops)

Each frame is gated by a FrameLotCondition (unconditional, or thresholds on stamina spent /
score / star-acts / achievement rate) and by its availability window. Every frame that is
currently available and whose condition is met drops its rewards. ``grant_frames`` collects
the rewards of one or many frames, consolidates identical resources, and batch-grants them
(see ``grant_things_consolidated``), returning the per-reward ``LiveDropThing`` list for the
result screen.
"""

from datetime import datetime, timezone

from helpers.cache import cache
from helpers.things import grant_things_consolidated
from models import LiveDropThing, ReceivedThing
from models.enums import FrameLotConditionTypes, LiveDropTypes

_SETTING: dict = {}
_FRAME_GROUP: dict = {}


def _build() -> None:
    if _SETTING:
        return
    _SETTING.update({m.id_: m for m in cache.live_setting_master})
    _FRAME_GROUP.update({m.id_: m for m in cache.live_drop_frame_group_master})


def _frame_available(frame, now: datetime) -> bool:
    """Whether a frame is inside its availability window -- start-inclusive, end-exclusive.

    A permanent frame carries no dates and always drops; a seasonal frame (a past New Year
    lottery ticket, an Easter egg, ...) only drops between its start and end, so an expired
    one no longer appears on normal results. Reward amounts and already-owned items are
    untouched -- this gates only whether the frame is offered at all.
    """

    def instant(value: str):
        if not value:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    try:
        start, end = instant(frame.start_date), instant(frame.end_date)
    except (ValueError, TypeError):
        return False
    return (start is None or start <= now) and (end is None or now < end)


def _frame_condition_met(
    frame,
    *,
    stamina_consumed: bool,
    score: int,
    star_act_count: int,
    achievement_rate: float,
) -> bool:
    cond = frame.frame_lot_condition
    value = frame.frame_lot_condition_value or 0
    if cond == FrameLotConditionTypes.None_:
        return True
    if cond == FrameLotConditionTypes.ConsumeStamina:
        return stamina_consumed
    if cond == FrameLotConditionTypes.ScoreWithConsumeStamina:
        return stamina_consumed and score >= value
    if cond == FrameLotConditionTypes.StarActCountWithConsumeStamina:
        return stamina_consumed and star_act_count >= value
    if cond == FrameLotConditionTypes.AchievementRateWithConsumeStamina:
        return stamina_consumed and achievement_rate >= value
    return False


def resolve_frames(
    live_setting_master_id: int,
    *,
    stamina_consumed: bool = True,
    score: int = 0,
    star_act_count: int = 0,
    achievement_rate: float = 0.0,
) -> list:
    """The drop frames a live awards -- every frame in its group whose lot condition is met."""
    _build()
    setting = _SETTING.get(live_setting_master_id)
    if setting is None:
        return []
    group = _FRAME_GROUP.get(setting.live_drop_frame_group_master_id)
    if group is None or not group.drop_frames:
        return []
    frames = sorted(group.drop_frames, key=lambda f: f.order)
    now = datetime.now(timezone.utc)
    return [
        f
        for f in frames
        if _frame_available(f, now)
        and _frame_condition_met(
            f,
            stamina_consumed=stamina_consumed,
            score=score,
            star_act_count=star_act_count,
            achievement_rate=achievement_rate,
        )
    ]


async def grant_frames(conn, user_id: int, frames) -> list[LiveDropThing]:
    """Grant the rewards of one or more drop frames (consolidated into as few writes as
    possible) and return the per-reward LiveDropThing list for the result."""
    things: list[tuple[int, int, int]] = []
    drops: list[LiveDropThing] = []
    order = 0
    for frame in frames:
        fixed = frame.frame_lot_condition == FrameLotConditionTypes.None_
        for reward in frame.rewards or []:
            things.append(
                (int(reward.thing_type), reward.thing_id, reward.thing_quantity)
            )
            drops.append(
                LiveDropThing(
                    received_thing=ReceivedThing(
                        type=int(reward.thing_type),
                        id_=reward.thing_id,
                        quantity=reward.thing_quantity,
                        sent_inbox=False,
                    ),
                    order=order,
                    live_drop_type=(
                        LiveDropTypes.Special
                        if reward.is_special_fall_thing
                        else LiveDropTypes.Normal
                    ),
                    is_fixed_drop=fixed,
                )
            )
            order += 1
    if things:
        await grant_things_consolidated(conn, user_id, things)
    return drops
