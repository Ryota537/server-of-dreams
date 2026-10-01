"""Lesson/course lifecycles and player-rank / daily-usage accounting.

Unknown limits are not enforced; lesson star points and rank XP per stamina are explicit
policy constants (``constants.yml``), not a reverse engineering of every modifier.
"""

import time

from helpers.cache import cache
from helpers.constants import constants
from helpers.daily import most_recent_reset
from helpers.game_state import (
    Rejected,
    State,
    character_progress,
    master,
    mission_progress,
    star_points,
)
from helpers.live_result import achievement_rate, clear_lamp, play_totals
from helpers.stamina import adjust_and_check_stamina, max_stamina
from models import LessonResult, PlayerRankPointResult


def rules() -> dict:
    return constants


async def daily(s: State, now: int | None = None) -> dict:
    now = now if now is not None else time.time_ns() // 1000
    row = await s.one("DailyLimit")
    zero = dict(
        autoPlayTimes=0,
        dailyLessonTimes=0,
        musicCourseFreeChallengeTimes=0,
        lastRefreshedAt=now,
    )
    if not row:
        return await s.insert("DailyLimit", **zero)
    if (row["lastRefreshedAt"] or 0) < most_recent_reset(now):
        await s.update("DailyLimit", row, **zero)
    return row


async def use_daily(s: State, field: str) -> None:
    row = await daily(s)
    if not rules()["unlimited_attempts"]:
        await s.update("DailyLimit", row, **{field: row[field] + 1})


async def context(s: State, mode: str, ident: int, extra: dict) -> None:
    await s.conn.conn.execute(
        'DELETE FROM preservation_live_context WHERE "userId"=$1', s.uid
    )
    await s.conn.conn.execute(
        'INSERT INTO preservation_live_context ("userId",mode,"masterId",extra) '
        "VALUES ($1,$2,$3,$4)",
        s.uid,
        mode,
        ident,
        extra,
    )


def lesson_slots(row) -> list:
    return [
        (x["position"], x.get("setCharacterId")) if isinstance(x, dict) else tuple(x)
        for x in row["setCharacters"] or []
    ]


def stored_slots(slots) -> list:
    return [dict(position=i, setCharacterId=cid) for i, cid in sorted(slots)]


async def lesson_party(s: State, base: int) -> dict:
    if not await s.one("CharacterBase", characterBaseMasterId=base):
        raise Rejected("Character not owned")
    row = await s.one("CharacterLesson", characterBaseMasterId=base)
    if row:
        return row
    owned = [
        r
        for r in await s.rows("Character")
        if master("character_master", r["characterMasterId"]).character_base_master_id
        == base
    ]
    owned.sort(key=lambda c: (c["level"], c["awakeningPhase"], c["id"]), reverse=True)
    if not owned:
        raise Rejected("No lesson actors")
    slots = [[i + 1, owned[i]["id"] if i < len(owned) else None] for i in range(5)]
    return await s.insert(
        "CharacterLesson",
        characterBaseMasterId=base,
        setCharacters=stored_slots(slots),
        bestScore=0,
        leaderPosition=0,
        rewardReceivedHighScore=0,
    )


async def rank_xp(s: State, amount: int) -> PlayerRankPointResult:
    row = await s.one("User")
    before = row["playerRank"]
    old = row["currentRankPoint"]
    stamina = row["currentStamina"]
    rank = before
    balance = old + amount
    levels = {x.rank: x for x in cache.player_rank_master}
    cap = min(
        row["playerRankLimit"],
        max(x.rank for x in cache.player_rank_master if x.is_released_rank),
    )
    restore = 0
    while rank < cap:
        m = levels.get(rank)
        if (
            not m
            or m.point_to_level_up <= 0
            or balance < m.point_to_level_up
            or rank + 1 not in levels
        ):
            break
        balance -= m.point_to_level_up
        rank += 1
        restore += max_stamina(rank)
    await s.update("User", row, playerRank=rank, currentRankPoint=balance)
    if restore:
        await adjust_and_check_stamina(s.conn, s.uid, restore, rank)
        s.tables.pop("User", None)
        row = await s.one("User")
        s.dirty[("User", row["id"])] = row.copy()
    if rank != before:
        for ident in (1000, 1100):
            await mission_progress(s, ident, absolute=rank)
    return PlayerRankPointResult(
        rank_before=before,
        rank_after=rank,
        rank_point_before=old,
        rank_point_after=balance,
        rank_point_acquired=amount,
        stamina_before=stamina,
    )


async def finish_lesson(s: State, base: int, p, result) -> None:
    row = await lesson_party(s, base)
    score, cleared = play_totals(p)
    before = row["bestScore"]
    things = []
    for threshold in cache.character_lesson_score_reward_master:
        if (
            threshold.character_base_master_id == base
            and row["rewardReceivedHighScore"] < threshold.required_score <= score
        ):
            group = master(
                "lesson_score_reward_group_master",
                threshold.lesson_score_group_master_id,
            )
            things.extend(
                (int(x.thing_type), x.thing_id, x.thing_quantity)
                for x in group.rewards or []
            )
    received = await s.grant(things)
    await s.update(
        "CharacterLesson",
        row,
        bestScore=max(before, score),
        rewardReceivedHighScore=max(row["rewardReceivedHighScore"], score),
    )
    await use_daily(s, "dailyLessonTimes")
    # generous preservation fallback, not an exact formula (constants.yml)
    points = rules()["lesson_star_points"] if cleared else 0
    star = await star_points(s, base, points)
    bases = {base} | {
        master(
            "character_master", a["characterMasterId"]
        ).secondary_character_base_master_id
        for a in await s.rows("Character")
        if any(a["id"] == cid for _, cid in lesson_slots(row))
    }
    for ident in bases:
        if ident:
            await character_progress(s, ident, 1, 1)
    await mission_progress(s, 100200, create=True)
    result.lesson_result = LessonResult(
        character_base_master_id=base,
        star_point_result=star,
        high_score_rewards=received,
        high_score_before=before,
        high_score_after=max(before, score),
    )


def find_course(detail_id: int):
    for m in cache.music_course_master:
        details = sorted(m.details or [], key=lambda d: d.set_list_number)
        for i, d in enumerate(details):
            if d.id_ == detail_id:
                return m, details, i
    raise Rejected("Unknown course stage")


async def finish_course(s: State, ident: int, p, result) -> None:
    course, details, index = find_course(ident)
    run = await s.conn.conn.fetchrow(
        'SELECT * FROM preservation_course_run WHERE "userId"=$1', s.uid
    )
    if not run or run["data"]["next"] != index:
        raise Rejected("Missing course session")
    data = run["data"]
    score, cleared = play_totals(p)
    if data["started_at"] < most_recent_reset(time.time_ns() // 1000):
        raise Rejected("Course crossed daily reset")
    data["rates"].append(round(achievement_rate(p.base_score_blocks), 4))
    data["lamps"].append(int(clear_lamp(cleared, p.base_score_blocks)))
    data["next"] = index + 1
    result.player_rank_point_result = None
    if not cleared or index == len(details) - 1:
        old = await s.one("MusicCourse", musicCourseMasterId=course.id_)
        grade = (
            (3 if data["gauge"] == 1 else 2)
            if cleared and all(data["lamps"]) and index == len(details) - 1
            else 1
        )
        lamp = min(data["lamps"]) if grade > 1 else 0
        total = round(sum(data["rates"]), 4)
        beforegrade = old["certificationGrade"] if old else 0
        best = float(old["totalAchievementRatePercentRecord"] or 0) if old else 0
        values = dict(
            clearLamp=max(old["clearLamp"] if old else 0, lamp),
            certificationGrade=max(beforegrade, grade),
            totalAchievementRatePercentRecord=str(max(best, total)),
        )
        if old:
            await s.update("MusicCourse", old, **values)
        else:
            await s.insert("MusicCourse", musicCourseMasterId=course.id_, **values)
        # master rewards apply once when a new certification grade is attained
        things = []
        for group in cache.music_course_reward_group_master:
            if (
                group.music_course_master_id == course.id_
                and beforegrade < int(group.required_certification_grade) <= grade
            ):
                things.extend(
                    (int(x.thing_type), x.thing_id, x.thing_quantity)
                    for x in group.rewards or []
                )
        await s.grant(things)
        await s.conn.conn.execute(
            'DELETE FROM preservation_course_run WHERE "userId"=$1', s.uid
        )
    else:
        await s.conn.conn.execute(
            'UPDATE preservation_course_run SET data=$2 WHERE "userId"=$1', s.uid, data
        )


async def finish_context(s: State, context_row, p, result) -> None:
    mode = context_row["mode"]
    extra = context_row["extra"] or {}
    if mode == "course":
        await finish_course(s, context_row["masterId"], p, result)
        return
    if mode == "lesson":
        await finish_lesson(s, context_row["masterId"], p, result)
    if extra.get("auto"):
        await use_daily(s, "autoPlayTimes")
    if extra.get("rank_xp", 0) > 0:
        result.player_rank_point_result = await rank_xp(s, extra["rank_xp"])
    score, cleared = play_totals(p)
    await mission_progress(s, 1600)
    if cleared:
        await mission_progress(s, 1800)
    await mission_progress(s, 3600, len(p.base_score_blocks or []))
