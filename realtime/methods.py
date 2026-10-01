"""MagicOnion method ids for the realtime hubs.

MagicOnion derives a method's id from its NAME, not its position in the
interface::

    id = FNV1A32(methodName) reinterpreted as a signed 32-bit int
    h  = 2166136261
    for byte in name.encode(): h = ((byte ^ h) * 16777619) & 0xFFFFFFFF

Source of truth: ``MagicOnion.Client.SourceGenerator/Internal/FNV1A32.cs`` and
``CodeAnalysis/MethodCollector.cs`` (which falls back to that hash when the
method carries no ``[MethodId]`` attribute).

Two consequences worth remembering:

* The name hashed is the BARE declaration -- no namespace, no interface prefix,
  and the ``Async`` suffix KEPT. Receiver callbacks keep their ``On`` prefix.
* A method id does NOT identify a hub on its own. ``JoinAsync`` hashes to the
  same value in ``ICircleHub`` and ``ICommonHub``; ``OnJoin`` likewise in both
  receivers. Always pair an id with the hub it arrived on.

The tables below mirror the client's hub interfaces. ``_METHOD_NAMES`` is built by hashing
them, so the ids are computed rather than copied -- a stale literal cannot drift.
"""

from __future__ import annotations

_MASK = 0xFFFFFFFF


def fnv1a32(name: str) -> int:
    """MagicOnion's method id for a bare method name, as a signed int32."""
    h = 2166136261
    for byte in name.encode("utf-8"):
        h = ((byte ^ h) * 16777619) & _MASK
    return h - 2**32 if h >= 2**31 else h


# --------------------------------------------------------------------------- #
# Method tables (from the client's hub interfaces)
# --------------------------------------------------------------------------- #
MULTI_LIVE_HUB = [
    "CreatePrivateHallAsync",
    "JoinPrivateHallFromInviteAsync",
    "JoinPrivateHallWithKeyCodeAsync",
    "JoinPublicHallAsync",
    "OpenPrivateRoomAsync",
    "NotifyCircleMemberAsync",
    "NotifyFriendsAsync",
    "ReadyForDecideMember",
    "DecideMemberAsync",
    "SelectMusicAsync",
    "SelectStampAsync",
    "SelectDifficultyAsync",
    "FetchUsersAsync",
    "ReadyGameAsync",
    "BeforeGameCalculateAsync",
    "StartGameAsync",
    "ExitGameAsync",
    "EntryFinalResultAsync",
    "ContinuePlayAsync",
    "SelectGoalDifficultyForTeamChallengeAsync",
    "SelectMusicDifficultyAndPartyForTeamChallengeAsync",
    "SyncInGameStatusAsync",
]

MULTI_LIVE_RECEIVER = [
    "OnJoin",
    "OnLeaveAnyOne",
    "OnCountDownDecideMember",
    "OnReadyDecideMember",
    "OnReadyGroup",
    "OnSelectMusic",
    "OnSelectStamp",
    "OnSelectDifficulty",
    "OnLotMusic",
    "OnGoGame",
    "OnBeforeGameCalculate",
    "OnPlayGame",
    "OnExitGameAnyOne",
    "OnExitAllGames",
    "OnSyncGameResult",
    "OnDestroy",
    "OnJoinedRoom",
    "OnLotMusicFaultStatus",
    "OnForceDisconnected",
    "OnSelectDifficultyAndPartyForTeamChallenge",
    "OnStartSessionForTeamChallenge",
    "OnExitAllGamesForTeamChallenge",
    "OnSyncInGameStatus",
]

CIRCLE_HUB = [
    "JoinAsync",
    "TrySendChatAsync",
    "GetChatsAsync",
    "GetReadChatAsync",
    "SaveReadChatAsync",
    "DeleteChatAsync",
    "GetActivityLogsAsync",
]

CIRCLE_RECEIVER = [
    "OnJoin",
    "OnJoinStatus",
    "OnReceiveChat",
    "OnNotifyFriendRequest",
    "OnNotifyMultiLiveRequest",
    "OnDeleteChat",
    "OnReceiveReadChat",
    "OnReceiveActivityLog",
]

COMMON_HUB = [
    "JoinAsync",
    "GetMultiLiveInvitationsFromFriendAsync",
]

COMMON_RECEIVER = [
    "OnJoin",
    "OnNotifyInviteMultiLiveFromFriend",
]

# Hub interface name -> (client -> server methods, server -> client methods)
HUBS = {
    "IMultiLiveHub": (MULTI_LIVE_HUB, MULTI_LIVE_RECEIVER),
    "ICircleHub": (CIRCLE_HUB, CIRCLE_RECEIVER),
    "ICommonHub": (COMMON_HUB, COMMON_RECEIVER),
}

# The service segment of the gRPC path. The client dials /<Interface>/Connect,
# so this is what the :path looks like on the wire.
HUB_PATH = {name: f"/{name}/Connect" for name in HUBS}


def _build_reverse() -> dict[int, str]:
    """method id -> name, over every hub's request AND receiver methods.

    Ambiguity is expected and fine: a name that appears in two interfaces hashes
    to one id. Callers that need certainty should look the name up in the hub the
    frame arrived on, not in this flat map.
    """
    out: dict[int, str] = {}
    for requests, receivers in HUBS.values():
        for name in requests + receivers:
            out.setdefault(fnv1a32(name), name)
    # Method id 0 is the reserved CONNECT frame, and it is NOT a hash of anything.
    # The client sends ``[0, 0]`` as the first frame of every hub stream (verified in
    # the captured session: it follows the server's marker on /ICircleHub/Connect), and
    # the real server answers it with NOTHING -- it just starts accepting requests.
    # Leaving 0 unregistered made the dispatcher treat it as an unknown method and
    # reply with an error frame, which the client has no case for.
    out[0] = "Connect"
    return out


# The reserved id MagicOnion uses for the connect frame. It is not derived from a name.
CONNECT_METHOD_ID = 0


METHOD_NAMES: dict[int, str] = _build_reverse()

# method id -> name, scoped per hub interface (unambiguous lookups)
METHOD_NAMES_BY_HUB: dict[str, dict[int, str]] = {
    hub: {fnv1a32(n): n for n in requests + receivers}
    for hub, (requests, receivers) in HUBS.items()
}

# The reverse direction: name -> id, per hub, for writing responses.
METHOD_IDS_BY_HUB: dict[str, dict[str, int]] = {
    hub: {n: fnv1a32(n) for n in requests + receivers}
    for hub, (requests, receivers) in HUBS.items()
}


def hub_for_path(path: str) -> str | None:
    """``/IMultiLiveHub/Connect`` -> ``IMultiLiveHub``."""
    parts = (path or "").strip("/").split("/")
    if parts and parts[0] in HUBS:
        return parts[0]
    return None


def method_name(method_id: int, hub: str | None = None) -> str | None:
    """Resolve a method id to a name, preferring the hub it arrived on."""
    if hub and hub in METHOD_NAMES_BY_HUB:
        found = METHOD_NAMES_BY_HUB[hub].get(method_id)
        if found:
            return found
    return METHOD_NAMES.get(method_id)


def method_id(name: str, hub: str | None = None) -> int | None:
    if hub and hub in METHOD_IDS_BY_HUB:
        found = METHOD_IDS_BY_HUB[hub].get(name)
        if found is not None:
            return found
    for table in METHOD_IDS_BY_HUB.values():
        if name in table:
            return table[name]
    return None


__all__ = [
    "CIRCLE_HUB",
    "CIRCLE_RECEIVER",
    "COMMON_HUB",
    "COMMON_RECEIVER",
    "HUBS",
    "HUB_PATH",
    "METHOD_IDS_BY_HUB",
    "METHOD_NAMES",
    "METHOD_NAMES_BY_HUB",
    "MULTI_LIVE_HUB",
    "MULTI_LIVE_RECEIVER",
    "fnv1a32",
    "hub_for_path",
    "method_id",
    "method_name",
]
