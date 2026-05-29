"""Service layer for the "battle a friend via invite" flow.

REST surface (orchestrated here, exposed in `controller.py`):
    POST   /battle/invites              create
    GET    /battle/invites/{code}       info
    DELETE /battle/invites/{code}       cancel

The actual battle pairing happens over WebSocket when both sides connect
with `?invite_code=...` — see `matchmaker.claim_invite()`. The REST
endpoints are thin: they create / read / cancel records in
`battle_invites`. They never touch the matchmaker queue.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.exceptions import AppException
from modules.battle.model import (
    INVITE_TTL_MINUTES,
    make_invite_code,
    new_battle_invite_doc,
)
from modules.battle.repository import BattleInviteRepository
from modules.battle.schema import (
    AcceptInviteResponse,
    CreateInviteResponse,
    InviteInfoResponse,
)

logger = logging.getLogger(__name__)


class InviteNotFound(AppException):
    def __init__(self, detail: str = "Invite not found."):
        super().__init__(detail, status_code=404)


class InviteExpired(AppException):
    def __init__(self, detail: str = "This invite has expired or already been used."):
        super().__init__(detail, status_code=410)  # Gone


class InviteNotOwned(AppException):
    def __init__(self, detail: str = "Only the inviter can cancel this invite."):
        super().__init__(detail, status_code=403)


class SelfInviteError(AppException):
    def __init__(self, detail: str = "You can't accept your own invite."):
        super().__init__(detail, status_code=400)


def _resolve_status(doc: dict) -> str:
    """Compute the effective status. A pending invite past `expires_at`
    is treated as expired even before the TTL sweep gets to it."""
    now = datetime.now(timezone.utc)
    if doc.get("status") == "pending" and doc.get("expires_at") and doc["expires_at"] <= now:
        return "expired"
    return doc.get("status", "pending")


class BattleInviteService:
    # How many times to retry on the (vanishingly unlikely) code collision
    # before giving up. 6-char × 32-alphabet ≈ 1B combos; we only have
    # tens of pending invites at a time.
    _CODE_RETRIES = 5

    def __init__(self, db: AsyncIOMotorDatabase):
        self.repo = BattleInviteRepository(db)

    async def create(self, inviter: dict) -> CreateInviteResponse:
        """Generate a fresh invite owned by `inviter`. Returns the bare
        code + expiry; the frontend builds the shareable URL."""
        for _ in range(self._CODE_RETRIES):
            code = make_invite_code()
            doc = new_battle_invite_doc(
                code=code,
                inviter_user_id=inviter["_id"],
                inviter_username=inviter.get("username") or "Player",
            )
            try:
                await self.repo.insert(doc)
                return CreateInviteResponse(
                    code=code,
                    expires_at=doc["expires_at"],
                )
            except Exception as exc:  # noqa: BLE001 — likely DuplicateKeyError
                # Retry on the unique-index collision; bubble everything else.
                msg = str(exc).lower()
                if "duplicate" not in msg and "e11000" not in msg:
                    raise
                logger.warning("Invite code collision on %s; retrying.", code)
        # Astronomically unlikely to land here.
        raise AppException("Could not generate a unique invite code. Try again.")

    async def get_info(self, code: str, viewer: dict) -> InviteInfoResponse:
        """Public-ish read for the join page. Returns the effective status
        (including computed `expired`) so the frontend can branch on stale
        links without needing to know the TTL."""
        doc = await self.repo.get_by_code(code)
        if doc is None:
            raise InviteNotFound()
        return InviteInfoResponse(
            code=doc["code"],
            inviter_username=doc.get("inviter_username") or "Player",
            status=_resolve_status(doc),
            expires_at=doc["expires_at"],
            is_own_invite=str(doc.get("inviter_user_id")) == str(viewer["_id"]),
        )

    async def cancel(self, code: str, inviter: dict) -> None:
        """Mark a pending invite as cancelled. Idempotent — calling on
        an already-cancelled or accepted invite is a no-op (404 only when
        the code never existed)."""
        doc = await self.repo.get_by_code(code)
        if doc is None:
            raise InviteNotFound()
        if str(doc.get("inviter_user_id")) != str(inviter["_id"]):
            raise InviteNotOwned()
        # `mark_cancelled` will simply not match if the invite already
        # transitioned out of pending — that's fine, idempotent.
        await self.repo.mark_cancelled(code, inviter["_id"])

    async def precheck_accept(self, code: str, invitee: dict) -> AcceptInviteResponse:
        """Lightweight read used by the join page right before it opens
        the WebSocket. Verifies the invite is still claimable + isn't a
        self-invite. Doesn't actually mark anything accepted yet — that
        happens when the WS pair-up succeeds in `matchmaker.claim_invite`."""
        doc = await self.repo.get_by_code(code)
        if doc is None:
            raise InviteNotFound()
        if str(doc.get("inviter_user_id")) == str(invitee["_id"]):
            raise SelfInviteError()
        status = _resolve_status(doc)
        if status != "pending":
            raise InviteExpired()
        return AcceptInviteResponse(code=code, ready=True)