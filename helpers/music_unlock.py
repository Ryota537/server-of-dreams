"""Stella / Olivier chart unlocks, derived from the user's live clears + live records.

Everything except an actual purchase is *derived* from the user's `live` rows against the
current live_master data, so a rerate (a chart's difficulty level changing between versions)
is handled automatically the next time we recompute.

Stella release (music.stellaReleased), driven by the Stella chart's own
LiveMaster.unlock_condition:
- LiveUnlockConditionTypes.None_ -> open from the start for any owned song (50 songs).
- LiveUnlockConditionTypes.ExtraGoodCount -> UnlockConditionMaster spells this one out:
  "楽曲を解放した上で以下のいずれかの条件を満たす / ・難易度EXTRAでGOOD以下を10個以内でクリア
  / ・任意の楽曲のOLIVIER譜面を20個解放" -- own the song, then either clear its Extra chart
  with at most unlock_value (10 everywhere in masterdata) GOOD-or-worse judgements, or have
  20 Olivier charts released across all songs, which opens every owned song's Stella at once.
  The GOOD count only exists on the finish that produced it -- the live row keeps a clear
  lamp, not a judgement breakdown -- so that route is granted by the finish and then kept,
  which the stickiness below makes safe.
- Sticky: once released it stays released.

Olivier release (music.olivierReleaseStatus, OlivierReleaseStatuses):
- Released (purchased) is sticky -- a rerate never revokes it.
- Nothing else happens while the song's Stella is still locked. Olivier is bought from the
  notation shop (LiveUnlockConditionTypes.NotationShop) and that shop only ever lists songs
  the user has already taken past Stella; offering it earlier lets a song be bought and
  played straight over its Stella chart.
- Otherwise a song's Olivier is Purchasable iff its CURRENT level is <= the highest Olivier
  level the user has cleared. So clearing an Olivier at level N makes every Olivier of level
  <= N purchasable at once (future grants included); a rerate above that level drops back.
- Otherwise, S-rank (or better) on the song's Stella chart makes its Olivier Challengeable.
- Otherwise None.
"""

from typing import Optional

from db.user import get_lives, get_musics, update_music_releases, upsert_music
from helpers.cache import cache
from models.enums import (
    AchievementRateGrades,
    ClearLamps,
    LiveUnlockConditionTypes,
    MusicDifficulties,
    MusicUnlockConditionTypes,
    OlivierReleaseStatuses,
)

# Budget for a Stella chart that asks for ExtraGoodCount without naming one; every such row
# in masterdata carries 10.
DEFAULT_EXTRA_GOOD_BUDGET = 10

# Olivier charts released before every owned song's Stella opens (UnlockConditionMaster 13).
OLIVIER_STELLA_THRESHOLD = 20

_BY_ID: dict = {}
_BY_MUSIC: dict = {}


def _build() -> None:
    if _BY_ID:
        return
    for m in cache.live_master:
        _BY_ID[m.id_] = m
        _BY_MUSIC.setdefault(m.music_master_id, {})[m.difficulty] = m


def _live_master(live_master_id: int):
    _build()
    return _BY_ID.get(live_master_id)


def _chart(music_master_id: int, difficulty: MusicDifficulties):
    _build()
    return _BY_MUSIC.get(music_master_id, {}).get(difficulty)


def _cleared(row) -> bool:
    return row.clearLamp >= int(ClearLamps.Clear)


_UNLOCK_DIFFICULTIES = (
    MusicDifficulties.Extra,
    MusicDifficulties.Stella,
    MusicDifficulties.Olivier,
)


def affects_unlocks(live_master_id: int) -> bool:
    """Whether finishing this chart could change any Stella/Olivier release state. Only Extra
    (stella), Stella (olivier challengeable) and Olivier (purchasable / 10-clear stella) can;
    Normal/Hard never do, so those finishes skip the whole re-derivation."""
    lm = _live_master(live_master_id)
    return lm is not None and lm.difficulty in _UNLOCK_DIFFICULTIES


def extra_good_budget(music_master_id: int) -> Optional[int]:
    """GOOD-or-worse judgements an Extra clear may carry and still release this song's
    Stella, or None when the Stella chart isn't gated on that at all."""
    stella = _chart(music_master_id, MusicDifficulties.Stella)
    if (
        stella is None
        or stella.unlock_condition != LiveUnlockConditionTypes.ExtraGoodCount
    ):
        return None
    value = stella.unlock_value
    return DEFAULT_EXTRA_GOOD_BUDGET if value is None else int(value)


def _stella_open_by_default(music_master_id: int) -> bool:
    stella = _chart(music_master_id, MusicDifficulties.Stella)
    return stella is not None and (
        stella.unlock_condition == LiveUnlockConditionTypes.None_
    )


def stella_unlocked_by(
    live_master_id: int, is_cleared: bool, good_or_worse: int
) -> Optional[int]:
    """The music_master_id whose Stella a just-finished play releases, or None.

    Only a song's own Extra chart can, and only when the clear stayed inside that song's
    GOOD budget. It has to be answered from the finish itself -- by the time unlocks are
    re-derived from the user's live records the judgement counts are gone.
    """
    lm = _live_master(live_master_id)
    if lm is None or lm.difficulty != MusicDifficulties.Extra or not is_cleared:
        return None
    budget = extra_good_budget(lm.music_master_id)
    if budget is None or good_or_worse > budget:
        return None
    return lm.music_master_id


class MusicProgress:
    """Aggregates of a user's live records, used to resolve per-song unlock state.

    ``stella_unlock`` is the one song (if any) whose Stella the finish currently being
    processed just earned -- see :func:`stella_unlocked_by` for why it can't come out of
    ``lives`` like everything else here.
    """

    def __init__(self, lives, musics, stella_unlock: Optional[int] = None) -> None:
        self.stella_unlock = stella_unlock
        self.all_stella = (
            sum(
                1
                for m in musics
                if m.olivierReleaseStatus == int(OlivierReleaseStatuses.Released)
            )
            >= OLIVIER_STELLA_THRESHOLD
        )
        self.max_cleared_olivier_level = 0
        self.stella_s_ranked: set[int] = set()
        for r in lives:
            lm = _live_master(r.liveMasterId)
            if lm is None:
                continue
            if lm.difficulty == MusicDifficulties.Olivier and _cleared(r):
                self.max_cleared_olivier_level = max(
                    self.max_cleared_olivier_level, lm.level
                )
            elif lm.difficulty == MusicDifficulties.Stella and r.rateGrade >= int(
                AchievementRateGrades.S
            ):
                self.stella_s_ranked.add(lm.music_master_id)

    def stella_released(
        self, music_master_id: int, is_possession: bool, stored: bool
    ) -> bool:
        if stored:
            return True  # sticky once released
        if is_possession and (
            self.all_stella or _stella_open_by_default(music_master_id)
        ):
            return True
        return music_master_id == self.stella_unlock

    def olivier_status(
        self, music_master_id: int, stored: int, stella_released: bool
    ) -> int:
        if stored == int(OlivierReleaseStatuses.Released):
            return int(
                OlivierReleaseStatuses.Released
            )  # purchased -> sticky across rerates
        if not stella_released:
            return int(OlivierReleaseStatuses.None_)  # never offered ahead of Stella
        olivier = _chart(music_master_id, MusicDifficulties.Olivier)
        if olivier is None:
            return int(OlivierReleaseStatuses.None_)
        # Purchasable outranks Challengeable deliberately: once an Olivier clear puts a chart
        # in the shop it has to be bought there, and the hold-the-Stella-button challenge
        # that Challengeable offers is withdrawn (see build_live_unit's intro flag).
        if olivier.level <= self.max_cleared_olivier_level:
            return int(OlivierReleaseStatuses.Purchasable)
        if music_master_id in self.stella_s_ranked:
            return int(OlivierReleaseStatuses.Challengeable)
        return int(OlivierReleaseStatuses.None_)


async def load_progress(
    conn, user_id: int, stella_unlock: Optional[int] = None
) -> MusicProgress:
    return MusicProgress(
        await conn.fetch(get_lives(user_id)),
        await conn.fetch(get_musics(user_id)),
        stella_unlock,
    )


async def apply_unlocks(conn, user_id: int, stella_unlock: Optional[int] = None):
    """Re-derive every owned song's release state, write what moved, return those rows.

    Callers push the returned music rows into their present so the client's song list
    reflects the change. Both triggers land here: finishing an Extra/Stella/Olivier chart,
    and buying an Olivier -- the 20th purchase opens every owned song's Stella, so the shop
    has to re-derive too or that release waits for the next live to be noticed.
    """
    progress = await load_progress(conn, user_id, stella_unlock)
    changed: list = []
    changes: list[tuple[int, bool, int]] = []
    for music in await conn.fetch(get_musics(user_id)):
        new_stella = progress.stella_released(
            music.musicMasterId, music.isPossession, music.stellaReleased
        )
        new_status = progress.olivier_status(
            music.musicMasterId, music.olivierReleaseStatus, new_stella
        )
        if (
            new_stella != music.stellaReleased
            or new_status != music.olivierReleaseStatus
        ):
            music.stellaReleased = new_stella
            music.olivierReleaseStatus = new_status
            changes.append((music.id, new_stella, new_status))
            changed.append(music)
    if changes:
        await conn.execute(update_music_releases(user_id, changes))
    return changed


async def granted_music_state(
    conn, user_id: int, music_master_id: int
) -> tuple[bool, int]:
    """(stellaReleased, olivierReleaseStatus) a freshly granted, possessed song starts at,
    given the user's current progress (so a song earned after the thresholds is born unlocked).
    """
    progress = await load_progress(conn, user_id)
    stella = progress.stella_released(music_master_id, True, False)
    return (
        stella,
        progress.olivier_status(
            music_master_id, int(OlivierReleaseStatuses.None_), stella
        ),
    )


# The dummy song and hidden entries are excluded; everything else of this type is owned from
# the start.
DEFAULT_MUSIC_UNLOCK_TYPE = int(MusicUnlockConditionTypes.Default)
DUMMY_MUSIC_ID = 9999

_DEFAULT_MUSIC_IDS: set[int] = set()


def default_music_master_ids() -> set[int]:
    """Songs the client treats as owned from the start (MusicUnlockConditionTypes.Default).

    The game lets these be played without a Music row, but Stella/Olivier release is derived
    from Music rows, so a default song that has none can never release its Stella. These are
    the ids whose rows :func:`ensure_default_music` backfills.
    """
    if not _DEFAULT_MUSIC_IDS:
        _DEFAULT_MUSIC_IDS.update(
            m.id_
            for m in cache.music_master
            if int(m.unlock_condition_type) == DEFAULT_MUSIC_UNLOCK_TYPE
            and not m.invisible
            and m.id_ != DUMMY_MUSIC_ID
        )
    return _DEFAULT_MUSIC_IDS


async def ensure_default_music(app, user_id) -> None:
    """Materialize a Music row for every default song the user is missing one for.

    Runs on data fetch under the per-account advisory lock, so new, existing and imported
    accounts all get backfilled -- without this, clearing a default song's Extra chart has no
    Music row to flip, so its Stella release is computed and then dropped. Each new row starts
    at the release state the user's current progress has already earned for it.
    """
    if user_id is None:
        return
    ids = default_music_master_ids()
    if not ids:
        return
    async with app.acquire_db() as conn, conn.transaction():
        await conn.conn.execute("SELECT pg_advisory_xact_lock($1)", user_id)
        musics = await conn.fetch(get_musics(user_id))
        missing = ids - {m.musicMasterId for m in musics}
        if not missing:
            return
        progress = MusicProgress(await conn.fetch(get_lives(user_id)), musics)
        next_id = max((m.id for m in musics), default=0) + 1
        sql = None
        args_seq = []
        for offset, music_master_id in enumerate(sorted(missing)):
            stella = progress.stella_released(music_master_id, True, False)
            query = upsert_music(
                user_id,
                {
                    "id": next_id + offset,
                    "musicMasterId": music_master_id,
                    "stellaReleased": stella,
                    "vocalVersion": 0,
                    "olivierReleaseStatus": progress.olivier_status(
                        music_master_id, int(OlivierReleaseStatuses.None_), stella
                    ),
                    "isPossession": True,
                },
            )
            sql = query.sql
            args_seq.append(query.args)
        if sql is not None:
            await conn.execute_batch(sql, args_seq)
