import logging
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from config.settings import settings
from core.email import send_otp_email
from core.exceptions import (
    AccountInactive,
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidToken,
    OTPExpired,
    OTPInvalid,
    OTPNotFound,
    OTPResendCooldown,
    OTPTooManyAttempts,
    UserNotFound,
    UsernameAlreadyTaken,
)
from core.jwt_handler import create_access_token, create_refresh_token, decode_token
from core.security import hash_password, verify_password
from modules.authentication.model import new_otp_doc, new_user_doc
from modules.authentication.repository import OTPRepository, UserRepository
from modules.authentication.schema import (
    AuthSuccessResponse,
    LoginRequest,
    SignupRequest,
    SignupResponse,
    TokenPair,
    UserPublic,
    VerifyOTPRequest,
)
from modules.authentication.utils import generate_otp

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.users = UserRepository(db)
        self.otps = OTPRepository(db)

    # ---------- helpers ----------
    @staticmethod
    def _user_public(user_doc: dict) -> UserPublic:
        return UserPublic(
            id=str(user_doc["_id"]),
            email=user_doc["email"],
            username=user_doc["username"],
            is_verified=user_doc.get("is_verified", False),
            is_active=user_doc.get("is_active", True),
            created_at=user_doc["created_at"],
            updated_at=user_doc["updated_at"],
        )

    @staticmethod
    def _issue_tokens(user_id: str) -> TokenPair:
        return TokenPair(
            access_token=create_access_token(user_id),
            refresh_token=create_refresh_token(user_id),
        )

    # ---------- signup ----------
    async def signup(self, payload: SignupRequest) -> SignupResponse:
        # Uniqueness checks first — return 409 before doing any work.
        if await self.users.exists_email(payload.email):
            existing = await self.users.get_by_email(payload.email)
            # If they signed up but never verified, allow re-issuing an OTP.
            if existing and not existing.get("is_verified", False):
                await self._issue_and_send_otp(payload.email, existing["username"])
                return SignupResponse(
                    message="A new verification code has been sent.",
                    email=payload.email,
                    otp_expires_in_minutes=settings.OTP_EXPIRY_MINUTES,
                )
            raise EmailAlreadyRegistered()

        if await self.users.exists_username(payload.username):
            raise UsernameAlreadyTaken()

        # Pre-create the user as unverified, then send OTP.
        user_doc = new_user_doc(
            email=payload.email,
            username=payload.username,
            hashed_password=hash_password(payload.password),
            is_verified=False,
        )
        await self.users.create(user_doc)
        await self._issue_and_send_otp(payload.email, payload.username)

        return SignupResponse(
            message="Verification code sent. Please check your email.",
            email=payload.email,
            otp_expires_in_minutes=settings.OTP_EXPIRY_MINUTES,
        )

    async def _issue_and_send_otp(self, email: str, username: str) -> None:
        # Cooldown check based on the most recent OTP record.
        latest = await self.otps.get_latest(email)
        if latest is not None:
            created_at = latest["created_at"]
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()
            if elapsed < settings.OTP_RESEND_COOLDOWN_SECONDS:
                raise OTPResendCooldown(
                    f"Please wait {int(settings.OTP_RESEND_COOLDOWN_SECONDS - elapsed)}s "
                    "before requesting another code."
                )

        code = generate_otp()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.OTP_EXPIRY_MINUTES
        )
        await self.otps.upsert(
            email=email,
            doc=new_otp_doc(
                email=email,
                otp_code_hash=hash_password(code),
                expires_at=expires_at,
            ),
        )

        try:
            await send_otp_email(email, username, code)
        except Exception:
            # If email fails, scrub the OTP record so the user isn't stuck
            # with a code they never received.
            await self.otps.delete_for_email(email)
            raise

    # ---------- resend ----------
    async def resend_otp(self, email: str) -> None:
        user = await self.users.get_by_email(email)
        if user is None:
            raise UserNotFound()
        if user.get("is_verified", False):
            # Idempotent no-op: don't reveal verification state explicitly.
            return
        await self._issue_and_send_otp(email, user["username"])

    # ---------- verify ----------
    async def verify_otp(self, payload: VerifyOTPRequest) -> AuthSuccessResponse:
        user = await self.users.get_by_email(payload.email)
        if user is None:
            raise UserNotFound()

        otp = await self.otps.get_latest(payload.email)
        if otp is None:
            raise OTPNotFound()

        expires_at = otp["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            await self.otps.delete_for_email(payload.email)
            raise OTPExpired()

        if otp["attempts"] >= settings.OTP_MAX_ATTEMPTS:
            await self.otps.delete_for_email(payload.email)
            raise OTPTooManyAttempts()

        if not verify_password(payload.otp_code, otp["otp_code"]):
            await self.otps.increment_attempts(otp["_id"])
            raise OTPInvalid()

        # Success — mark user verified, clear OTPs.
        await self.users.mark_verified(user["_id"])
        await self.otps.delete_for_email(payload.email)

        refreshed = await self.users.get_by_id(user["_id"])
        assert refreshed is not None
        return AuthSuccessResponse(
            user=self._user_public(refreshed),
            tokens=self._issue_tokens(str(refreshed["_id"])),
        )

    # ---------- login ----------
    async def login(self, payload: LoginRequest) -> AuthSuccessResponse:
        user = await self.users.get_by_email(payload.email)
        if user is None or not verify_password(payload.password, user["hashed_password"]):
            raise InvalidCredentials()
        if not user.get("is_active", True):
            raise AccountInactive()
        if not user.get("is_verified", False):
            # Re-send OTP so they can complete the flow.
            try:
                await self._issue_and_send_otp(payload.email, user["username"])
            except OTPResendCooldown:
                pass
            raise InvalidCredentials(
                "Please verify your email. A new code has been sent if eligible."
            )
        return AuthSuccessResponse(
            user=self._user_public(user),
            tokens=self._issue_tokens(str(user["_id"])),
        )

    # ---------- refresh ----------
    async def refresh(self, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, token_type="refresh")
        user_id = payload["sub"]
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise InvalidToken("Token subject not found.")
        if not user.get("is_active", True):
            raise AccountInactive()
        return self._issue_tokens(str(user["_id"]))
