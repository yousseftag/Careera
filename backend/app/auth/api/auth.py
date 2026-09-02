from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.model.user import (
    GoogleLoginRequest,
    LoginResponse,
    LogoutRequest,
    LogoutResponse,
    RefreshTokenRequest,
    RefreshResponse,
)
from app.auth.service import auth as auth_service
from app.auth.utils.auth import get_current_user, security

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse, status_code=200)
async def login_with_google(body: GoogleLoginRequest) -> LoginResponse:
    """Validate Google ID token, upsert user, and issue access + refresh tokens."""
    return await auth_service.login_with_google(body.id_token)


@router.post("/login/dev", response_model=LoginResponse, status_code=200)
async def dev_login(
    email: str = "dev@test.com", name: str = "Test Developer"
) -> LoginResponse:
    """DEV ONLY - Quick login without Google OAuth."""
    return await auth_service.dev_login(email=email, name=name)


@router.post("/refresh", response_model=RefreshResponse, status_code=200)
async def refresh_token(body: RefreshTokenRequest) -> RefreshResponse:
    """Exchange a valid refresh token for a new access token and rotated refresh token."""
    return await auth_service.refresh_access_token(body.refresh_token)


@router.post("/logout", response_model=LogoutResponse, status_code=200)
async def logout(
    body: LogoutRequest,
    current_user: dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> LogoutResponse:
    """Invalidate current access and refresh tokens."""
    return await auth_service.logout(
        current_user=current_user,
        access_token=credentials.credentials,
        refresh_token=body.refresh_token,
    )

