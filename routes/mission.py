from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request

from core import YumeApp
from helpers.game_state import Rejected, master, transaction
from helpers.msgpack import respond
from models import *

router = APIRouter(tags=["Mission"])


async def receive_missions(request, mission_id=None, category=None):
    """Claim rewards for every cleared, in-window mission (optionally filtered by id or
    category), advancing multi-stage missions to their next stage."""
    now = datetime.now(timezone.utc)

    def available(value, end=False):
        if not value:
            return True
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return now < date if end else date <= now

    try:
        async with transaction(request) as s:
            rewards = []
            for row in await s.rows("Mission"):
                m = master("mission_master", row["missionMasterId"])
                if (
                    not m
                    or (mission_id is not None and m.id_ != mission_id)
                    or (category is not None and int(m.mission_category) != category)
                    or row["isRewardReceived"]
                    or not row["isCleared"]
                    or not available(m.start_date)
                    or not available(m.end_date, end=True)
                ):
                    continue
                stages = sorted(m.stages or [], key=lambda x: x.mission_stage_order)
                stage = next(
                    (x for x in stages if x.id_ == row["currentMissionStageMasterId"]),
                    None,
                )
                if (
                    not stage
                    or row["missionCurrentCount"] < stage.stage_goal_value
                    or not available(stage.start_date)
                ):
                    continue
                rewards.extend(
                    (int(r.thing_type), r.thing_id, r.thing_quantity)
                    for r in stage.rewards or []
                )
                following = next(
                    (
                        x
                        for x in stages
                        if x.mission_stage_order > stage.mission_stage_order
                    ),
                    None,
                )
                if following:
                    await s.update(
                        "Mission",
                        row,
                        currentMissionStageMasterId=following.id_,
                        isCleared=row["missionCurrentCount"]
                        >= following.stage_goal_value,
                        isRewardReceived=False,
                    )
                else:
                    await s.update("Mission", row, isRewardReceived=True)
            received = await s.grant(rewards)
        return respond(received, present=s.present())
    except Rejected:
        return respond([])


# /api/Missions/PickupActor/bulkReceiveRewards/{mPickupCharacterMissionMasterId}
@router.post(
    "/api/Missions/PickupActor/bulkReceiveRewards/{mPickupCharacterMissionMasterId}",
    name="Mission_BulkReceivePiclupCharacterMissionRewards",
)
async def mission_bulk_receive_piclup_character_mission_rewards(
    request: Request, mPickupCharacterMissionMasterId: int
):
    app: YumeApp = request.app
    payload = {}  # no payload
    return respond([])


# /api/Missions/ExchangeMissionPoint?unit=
@router.post("/api/Missions/ExchangeMissionPoint", name="Mission_ExchangeMissionPoint")
async def mission_exchange_mission_point(request: Request, unit: Optional[int] = None):
    app: YumeApp = request.app
    payload = {}  # no payload
    return respond(BooleanResult())


# /api/Missions/receiveRewards?missionCategory=
@router.post("/api/Missions/receiveRewards", name="Mission_ReceiveAllCurrentReward")
async def mission_receive_all_current_reward(
    request: Request, missionCategory: Optional[int] = None
):
    if missionCategory is None:
        return respond([])
    return await receive_missions(request, category=missionCategory)


# /api/Missions/MissionPassReceiveRewards/{missionPassId}
@router.post(
    "/api/Missions/MissionPassReceiveRewards/{missionPassId}",
    name="Mission_ReceiveBulkMissionPassRewards",
)
async def mission_receive_bulk_mission_pass_rewards(
    request: Request, missionPassId: int
):
    app: YumeApp = request.app
    payload = {}  # no payload
    return respond(MissionPassRewardsResult())


# /api/Missions/{missionId}/receiveCurrentRewards
@router.post(
    "/api/Missions/{missionId}/receiveCurrentRewards",
    name="Mission_ReceiveCurrentReward",
)
async def mission_receive_current_reward(request: Request, missionId: int):
    return await receive_missions(request, mission_id=missionId)


# /api/Missions/PickupActor/receiveRewards/{mPickupCharacterMissionMasterId}/{mPickupCharacterMissionDetailMasterId}
@router.post(
    "/api/Missions/PickupActor/receiveRewards/{mPickupCharacterMissionMasterId}/{mPickupCharacterMissionDetailMasterId}",
    name="Mission_ReceivePiclupCharacterMissionRewards",
)
async def mission_receive_piclup_character_mission_rewards(
    request: Request,
    mPickupCharacterMissionMasterId: int,
    mPickupCharacterMissionDetailMasterId: int,
):
    app: YumeApp = request.app
    payload = {}  # no payload
    return respond([])
