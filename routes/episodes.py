from fastapi import APIRouter, Request, Response
from starlette.exceptions import HTTPException

from helpers.cache import cache
from helpers.character_enhance import character_master
from helpers.episodes import (
    _local_meta,
    episode_read_reward_things,
    episode_readall_reward_things,
    episode_result,
    episode_scene_bin,
    scene_bin_name,
)
from helpers.game_state import Rejected, character_progress, transaction
from helpers.msgpack import respond
from models import *

router = APIRouter(tags=["Episodes"])


async def read_story(request: Request, eid: int, read_all: bool):
    """Grant an episode's read reward once (ReadAll additionally grants the read-all reward).
    Character episodes are gated on the character having the episode released, and advance the
    character's reading progress + character mission on first read."""
    try:
        async with transaction(request) as s:
            relation = next(
                (
                    e
                    for e in cache.character_episode_master
                    if e.episode_master_id == eid
                ),
                None,
            )
            char = None
            if relation:
                char = await s.one(
                    "Character", characterMasterId=relation.character_master_id
                )
                if not char or char["releasedEpisodeOrder"] < int(
                    relation.episode_order
                ):
                    raise Rejected()
            existing = await s.one("Episode", episodeMasterId=eid)
            rewards: list = []
            if not existing:
                rewards += episode_read_reward_things(eid)
                if read_all:
                    rewards += episode_readall_reward_things(eid)
                await s.insert(
                    "Episode", id=eid, episodeMasterId=eid, hasReadAll=read_all
                )
                if char:
                    order = max(char["readEpisodeOrder"], int(relation.episode_order))
                    await s.update("Character", char, readEpisodeOrder=order)
                    cm = character_master(relation.character_master_id)
                    await character_progress(s, cm.character_base_master_id, 4, 1)
            elif read_all and not existing["hasReadAll"]:
                rewards += episode_readall_reward_things(eid)
                await s.update("Episode", existing, hasReadAll=True)
            result = await s.grant(rewards)
        return respond(result, present=s.present())
    except Rejected:
        return respond([])


# Scene script blob: EpisodeDetailResult[] packed to msgpack, served as the .bin the client
# downloads (from an EpisodeResult.EpisodeDetailAssetSource)
@router.get("/master-data/production/scenes/{filename}", name="Episodes_SceneBin")
async def episodes_scene_bin(request: Request, filename: str) -> Response:
    if not filename.endswith(".bin"):
        raise HTTPException(status_code=404)
    name = filename[:-4]  # "<id>_<hash>"
    try:
        episode_id = int(name.split("_", 1)[0])
    except ValueError:
        raise HTTPException(status_code=404)
    if name != scene_bin_name(episode_id):  # id + hash must match the manifest exactly
        raise HTTPException(status_code=404)
    data = episode_scene_bin(episode_id)
    if data is None:
        raise HTTPException(status_code=404)
    return Response(content=data, media_type="application/octet-stream")


# /api/Episodes/{episodeMasterId}/Read  (read by skipping -> has_read_all = false)
@router.post("/api/Episodes/{episodeMasterId}/Read", name="Episodes_CompleteRead")
async def episodes_complete_read(request: Request, episodeMasterId: int):
    return await read_story(request, episodeMasterId, False)


# /api/Episodes/{episodeMasterId}/ReadAll  (read all the text -> has_read_all = true)
@router.post("/api/Episodes/{episodeMasterId}/ReadAll", name="Episodes_CompleteReadAll")
async def episodes_complete_read_all(request: Request, episodeMasterId: int):
    return await read_story(request, episodeMasterId, True)


# /api/Episodes/{episodeMasterId}/GetDetails
@router.post(
    "/api/Episodes/{episodeMasterId}/GetDetails", name="Episodes_GetEpisodeDetail"
)
async def episodes_get_episode_detail(request: Request, episodeMasterId: int):
    # Returns a single EpisodeResult (title/storyType/order + EpisodeDetailAssetSource); the
    # client downloads that asset source to get the EpisodeDetailResult[] script. Local
    # metadata fills in the title/order/story type when available.
    result = episode_result(episodeMasterId)
    metadata = _local_meta(episodeMasterId)
    if result and metadata:
        result.episode_title, result.episode_order, result.story_type = metadata
    return respond(result if result is not None else EpisodeResult())
