from fastapi import HTTPException, status


class AppException(HTTPException):
    """Base application exception. Subclass to define domain-specific errors."""

    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=status_code, detail=detail)


# ---- Auth / user ----
class EmailAlreadyRegistered(AppException):
    def __init__(self, detail: str = "Email is already registered."):
        super().__init__(detail, status.HTTP_409_CONFLICT)


class UsernameAlreadyTaken(AppException):
    def __init__(self, detail: str = "Username is already taken."):
        super().__init__(detail, status.HTTP_409_CONFLICT)


class InvalidCredentials(AppException):
    def __init__(self, detail: str = "Invalid email or password."):
        super().__init__(detail, status.HTTP_401_UNAUTHORIZED)


class UserNotFound(AppException):
    def __init__(self, detail: str = "User not found."):
        super().__init__(detail, status.HTTP_404_NOT_FOUND)


class AccountNotVerified(AppException):
    def __init__(self, detail: str = "Account email is not verified."):
        super().__init__(detail, status.HTTP_403_FORBIDDEN)


class AccountInactive(AppException):
    def __init__(self, detail: str = "Account is inactive."):
        super().__init__(detail, status.HTTP_403_FORBIDDEN)


# ---- OTP ----
class OTPNotFound(AppException):
    def __init__(self, detail: str = "No active OTP found. Please request a new one."):
        super().__init__(detail, status.HTTP_404_NOT_FOUND)


class OTPExpired(AppException):
    def __init__(self, detail: str = "OTP has expired. Please request a new one."):
        super().__init__(detail, status.HTTP_410_GONE)


class OTPInvalid(AppException):
    def __init__(self, detail: str = "Invalid OTP code."):
        super().__init__(detail, status.HTTP_400_BAD_REQUEST)


class OTPTooManyAttempts(AppException):
    def __init__(self, detail: str = "Too many invalid attempts. Please request a new OTP."):
        super().__init__(detail, status.HTTP_429_TOO_MANY_REQUESTS)


class OTPResendCooldown(AppException):
    def __init__(self, detail: str = "Please wait before requesting another OTP."):
        super().__init__(detail, status.HTTP_429_TOO_MANY_REQUESTS)


# ---- JWT ----
class InvalidToken(AppException):
    def __init__(self, detail: str = "Invalid or expired token."):
        super().__init__(detail, status.HTTP_401_UNAUTHORIZED)


# ---- Profile ----
class ProfileAlreadyExists(AppException):
    def __init__(self, detail: str = "Profile already exists for this user."):
        super().__init__(detail, status.HTTP_409_CONFLICT)


class ProfileNotFound(AppException):
    def __init__(self, detail: str = "Profile not found."):
        super().__init__(detail, status.HTTP_404_NOT_FOUND)
