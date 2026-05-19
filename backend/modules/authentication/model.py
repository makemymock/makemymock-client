"""
Domain-level dataclass models for the authentication module.

Mongo documents are dict-shaped at the boundary, but we centralize the
allowed keys here so repository / service code stays consistent.
"""

from datetime import datetime, timezone
from typing import Any


def new_user_doc(
    *,
    email: str,
    username: str,
    hashed_password: str,
    is_verified: bool = False,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "email": email.lower().strip(),
        "username": username.strip(),
        "hashed_password": hashed_password,
        "is_verified": is_verified,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def new_otp_doc(
    *,
    email: str,
    otp_code_hash: str,
    expires_at: datetime,
) -> dict[str, Any]:
    return {
        "email": email.lower().strip(),
        "otp_code": otp_code_hash,  # stored hashed, never in plaintext
        "attempts": 0,
        "expires_at": expires_at,
        "created_at": datetime.now(timezone.utc),
    }
