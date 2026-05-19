from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from config.database import get_database
from config.settings import settings
from core.exceptions import (
    AccountInactive,
    AccountNotVerified,
    InvalidToken,
    UserNotFound,
)
from core.jwt_handler import decode_token

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login/form", auto_error=True
)

DBDep = Annotated[AsyncIOMotorDatabase, Depends(get_database)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DBDep,
) -> dict:
    """
    Resolve the current user from the access token. Returns the raw user
    document (without password). Raises 401/403/404 on any problem.
    """
    payload = decode_token(token, token_type="access")
    user_id = payload.get("sub")
    if not user_id:
        raise InvalidToken()

    from bson import ObjectId  # local import keeps bson out of module top-level

    try:
        oid = ObjectId(user_id)
    except Exception as exc:
        raise InvalidToken("Malformed user id in token.") from exc

    user = await db["users"].find_one({"_id": oid}, {"hashed_password": 0})
    if user is None:
        raise UserNotFound()
    if not user.get("is_active", True):
        raise AccountInactive()
    return user


async def get_current_verified_user(
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    if not user.get("is_verified", False):
        raise AccountNotVerified()
    return user


CurrentUser = Annotated[dict, Depends(get_current_user)]
CurrentVerifiedUser = Annotated[dict, Depends(get_current_verified_user)]
