"""Account link / takeover: password, linkage code and confirmation code.

Three endpoints cooperate:

* ``POST /api/Account/RegisterTakeOverPassword`` (authenticated) -- stores the takeover
  password and hands back the 10 digit ``linkage_code`` the player writes down.
* ``POST /api/Account/GetConfirmationCode`` (authenticated) -- issues the 6 digit code the
  player reads to support, valid for :data:`CONFIRMATION_TTL_SECONDS`.
* ``POST /api/Account/GetTakeOverAccount`` (UNAUTHENTICATED) -- the other half of the
  pairing: ``linkage_code`` + ``password`` from a fresh install returns the account and a
  ``login_token``, which is what the client then feeds to ``/api/Account/Authenticate``.

The captured client traffic fixes the contract:

* ``RegisterTakeOverPassword`` -> ``[true, "5663103796"]`` plus a ``ConnectWithPassword``
  present whose ``id`` is the ``connect_with_password`` row id.
* ``GetConfirmationCode`` -> ``["977516", 593]`` (six digits, ~600 s left).
* ``GetTakeOverAccount`` -> ``[true, "5170960127", "良太", 169, "<jwt>"]`` where the id is
  ``hash_id(userId)`` and the token is a plain login token (the capture's claims were
  ``uid``/``nbf``/``exp``/``iat``/``iss``/``aud``, exactly what :func:`make_jwt` emits).

Only the *hash* of the takeover password is stored, and the confirmation code is not sent
back by ``RegisterTakeOverPassword`` -- a wrong password therefore cannot be distinguished
from an unknown linkage code by reading the response alone.
"""

import secrets
import time
from typing import Optional

from db.user.create import (
    set_connect_with_password_confirmation,
    upsert_connect_with_password,
)
from db.user.get import (
    get_connect_with_password_by_linkage_code,
    get_connect_with_passwords,
    get_user_profiles,
    get_users,
)
from helpers.auth import make_jwt
from helpers.password import hash_password, verify_password
from helpers.user_hash import hash_id
from models import TakeOverAccountResult, TakeOverCodeResult, TimedConfirmationCode

# the confirmation code is a 6 digit code that stays valid for about ten minutes
CONFIRMATION_TTL_SECONDS = 600
_LINKAGE_CODE_DIGITS = 10
_CONFIRMATION_CODE_DIGITS = 6


def _code(digits: int) -> str:
    """A numeric code with no leading zero, so it always prints `digits` wide."""
    low = 10 ** (digits - 1)
    return str(low + secrets.randbelow(9 * low))


def _hash_column(user_id: int) -> int:
    """The row id stored in ``connect_with_password.id``.

    The captured response carried a six digit ``id`` (``480126``) for a nine digit
    ``userId``, so the column is not simply the user id. Derive it from the user instead of
    allocating a sequence: it stays stable across re-registration and is unique per user.
    """
    return int(str(hash_id(user_id))[-_CONFIRMATION_CODE_DIGITS:])


async def _unique_linkage_code(conn, user_id: int) -> str:
    """A linkage code no other account currently holds."""
    for _ in range(20):
        code = _code(_LINKAGE_CODE_DIGITS)
        existing = await conn.fetchrow(get_connect_with_password_by_linkage_code(code))
        if existing is None or existing.userId == user_id:
            return code
    raise RuntimeError("could not allocate a unique linkage code")


async def register_take_over_password(
    app, user_id: Optional[int], password: str
) -> tuple[TakeOverCodeResult, Optional[int]]:
    """Store the takeover password and return the linkage code to show the player.

    Returns the result plus the ``connect_with_password`` row id, or ``None`` when the
    caller is not authenticated (there is no account to attach the password to).
    """
    if user_id is None or not password:
        return TakeOverCodeResult(), None
    async with app.acquire_db() as conn:
        # The linkage code is the player's durable account address -- they write it down and
        # quote it on a new device. Re-registering the password must NOT invalidate it, so
        # reuse the existing code and only allocate one on first registration.
        existing = await conn.fetchrow(get_connect_with_passwords(user_id))
        linkage_code = existing.linkageCode if existing is not None else None
        if not linkage_code:
            linkage_code = await _unique_linkage_code(conn, user_id)
        row_id = _hash_column(user_id)
        await conn.execute(
            upsert_connect_with_password(
                user_id,
                {
                    "id": row_id,
                    "passwordHash": hash_password(password),
                    "linkageCode": linkage_code,
                },
            )
        )
    return TakeOverCodeResult(is_success=True, linkage_code=linkage_code), row_id


async def get_confirmation_code(app, user_id: Optional[int]) -> TimedConfirmationCode:
    """Issue (or re-issue) the short-lived confirmation code for support.

    The code lives in its own column rather than being derived on the fly: it has to
    survive until it expires, so support and the player can compare the same value.
    """
    if user_id is None:
        return TimedConfirmationCode()
    now = int(time.time())
    async with app.acquire_db() as conn:
        existing = await conn.fetchrow(get_connect_with_passwords(user_id))
        if existing is None:
            # the client only reaches this after registering a password, so a missing row
            # means there is nothing to confirm yet
            return TimedConfirmationCode()
        code = existing.confirmationCode
        expires_at = existing.confirmationExpiresAt
        if not code or expires_at <= now:
            code = _code(_CONFIRMATION_CODE_DIGITS)
            expires_at = now + CONFIRMATION_TTL_SECONDS
            await conn.execute(
                set_connect_with_password_confirmation(user_id, code, expires_at)
            )
    return TimedConfirmationCode(
        confirmation_code=code, remaining_seconds=expires_at - now
    )


async def get_take_over_account(
    app, linkage_code: str, password: str
) -> TakeOverAccountResult:
    """Resolve ``linkage_code`` + ``password`` to the account and a fresh login token.

    Runs without authentication, so it is the one place a wrong password must be rejected:
    the caller gets the same empty result whether the code is unknown or the password is
    wrong.
    """
    if not linkage_code or not password:
        return TakeOverAccountResult()
    async with app.acquire_db() as conn:
        row = await conn.fetchrow(
            get_connect_with_password_by_linkage_code(linkage_code)
        )
        if row is None or not row.passwordHash:
            return TakeOverAccountResult()
        if not verify_password(password, row.passwordHash):
            return TakeOverAccountResult()
        account = await conn.fetchrow(get_users(row.userId))
        profile = await conn.fetchrow(get_user_profiles(row.userId))
    if account is None:
        return TakeOverAccountResult()
    return TakeOverAccountResult(
        is_success=True,
        user_id=hash_id(row.userId),
        name=profile.name if profile is not None else None,
        rank=account.playerRank,
        login_token=make_jwt(row.userId),
    )
