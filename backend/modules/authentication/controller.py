from fastapi import APIRouter, status

from core.dependencies import CurrentUser, DBDep
from modules.authentication.schema import (
    AuthSuccessResponse,
    LoginRequest,
    MessageResponse,
    RefreshTokenRequest,
    ResendOTPRequest,
    SignupRequest,
    SignupResponse,
    TokenPair,
    UserPublic,
    VerifyOTPRequest,
)
from modules.authentication.service import AuthService

from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Depends

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user and trigger email OTP",
)
async def signup(payload: SignupRequest, db: DBDep) -> SignupResponse:
    return await AuthService(db).signup(payload)


@router.post(
    "/verify-otp",
    response_model=AuthSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify the OTP and issue access + refresh tokens",
)
async def verify_otp(payload: VerifyOTPRequest, db: DBDep) -> AuthSuccessResponse:
    return await AuthService(db).verify_otp(payload)


@router.post(
    "/resend-otp",
    response_model=MessageResponse,
    summary="Resend an OTP to the user's email",
)
async def resend_otp(payload: ResendOTPRequest, db: DBDep) -> MessageResponse:
    await AuthService(db).resend_otp(payload.email)
    return MessageResponse(message="If the account exists, a new code has been sent.")


@router.post(
    "/login",
    response_model=AuthSuccessResponse,
    summary="Authenticate with email + password",
)
async def login(payload: LoginRequest, db: DBDep) -> AuthSuccessResponse:
    return await AuthService(db).login(payload)


@router.post(
    "/refresh-token",
    response_model=TokenPair,
    summary="Exchange a refresh token for a new token pair",
)
async def refresh_token(payload: RefreshTokenRequest, db: DBDep) -> TokenPair:
    return await AuthService(db).refresh(payload.refresh_token)


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Get the currently authenticated user",
)
async def me(current_user: CurrentUser) -> UserPublic:
    return UserPublic(
        id=str(current_user["_id"]),
        email=current_user["email"],
        username=current_user["username"],
        is_verified=current_user.get("is_verified", False),
        is_active=current_user.get("is_active", True),
        created_at=current_user["created_at"],
        updated_at=current_user["updated_at"],
    )


@router.post("/login/form", response_model=TokenPair, include_in_schema=False)
async def login_form(
    form: OAuth2PasswordRequestForm = Depends(),
    db: DBDep = None,
):
    result = await AuthService(db).login(
        LoginRequest(email=form.username, password=form.password)
    )
    return result.tokens