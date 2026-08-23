import os
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from app.auth.model.user import LoginResponse, LogoutResponse, RefreshResponse, UserResponse
from app.auth.utils.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    blacklist_token,
    create_access_token,
    create_refresh_token,
    is_token_blacklisted,
    verify_google_token,
    verify_token,
)
from app.database.connection import get_database
from app.share.api.errors import api_error


async def login_with_google(id_token: str) -> LoginResponse:
    """Validate Google ID token, upsert user in MongoDB, and issue JWTs."""
    if not id_token or not id_token.strip():
        api_error(
            code="MISSING_TOKEN",
            message="Google ID token is required.",
            status_code=400,
        )

    try:
        google_info = verify_google_token(id_token)
    except Exception as exc:
        api_error(
            code="INVALID_TOKEN",
            message=f"Invalid or expired Google ID token: {exc}",
            status_code=401,
        )

    email = google_info.get("email")
    if not email:
        api_error(
            code="INVALID_TOKEN",
            message="Google token does not contain a verified email address.",
            status_code=401,
        )

    name = google_info.get("name") or email.split("@")[0]
    avatar = google_info.get("avatar")

    db = await get_database()
    now = datetime.now(timezone.utc)

    user = await db.users.find_one({"email": email})
    if not user:
        new_user = {
            "email": email,
            "name": name,
            "avatar": avatar,
            "created_at": now,
            "last_login": now,
            "profile": {
                "cv_parsed_text": None,
                "linkedin_parsed_text": None,
                "interests": {"roles": [], "focus_areas": []},
            },
            "gamification": {"total_xp": 0, "level": 1},
        }
        res = await db.users.insert_one(new_user)
        user_id = str(res.inserted_id)
    else:
        update_fields: dict = {"last_login": now}
        if avatar and not user.get("avatar"):
            update_fields["avatar"] = avatar
        await db.users.update_one({"_id": user["_id"]}, {"$set": update_fields})
        user_id = str(user["_id"])
        name = user.get("name") or name
        avatar = user.get("avatar") or avatar

    token_data = {"sub": user_id, "email": email}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return LoginResponse(
        message="Login successful",
        token_type="bearer",
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(id=user_id, email=email, name=name, avatar=avatar),
    )


async def dev_login(
    email: str = "dev@test.com", name: str = "Test Developer"
) -> LoginResponse:
    """Dev-only login without Google OAuth verification."""
    db = await get_database()
    now = datetime.now(timezone.utc)

    user = await db.users.find_one({"email": email})
    if not user:
        new_user = {
            "email": email,
            "name": name,
            "avatar": None,
            "created_at": now,
            "last_login": now,
            "profile": {
                "cv_parsed_text": None,
                "linkedin_parsed_text": None,
                "interests": {"roles": [], "focus_areas": []},
            },
            "gamification": {"total_xp": 0, "level": 1},
        }
        res = await db.users.insert_one(new_user)
        user_id = str(res.inserted_id)
    else:
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {"last_login": now}},
        )
        user_id = str(user["_id"])
        name = user.get("name", name)

    token_data = {"sub": user_id, "email": email}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return LoginResponse(
        message="DEV login successful",
        token_type="bearer",
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(id=user_id, email=email, name=name, avatar=None),
    )


async def refresh_access_token(refresh_token: str) -> RefreshResponse:
    """Validate a refresh token, rotate it (sliding 7 days), and issue a new access token."""
    if not refresh_token or not refresh_token.strip():
        api_error(
            code="INVALID_REFRESH",
            message="Refresh token is required.",
            status_code=401,
        )

    if await is_token_blacklisted(refresh_token):
        api_error(
            code="INVALID_REFRESH",
            message="Refresh token has been revoked.",
            status_code=401,
        )

    try:
        payload = verify_token(refresh_token, token_type="refresh")
    except Exception as exc:
        api_error(
            code="INVALID_REFRESH",
            message=f"Invalid or expired refresh token: {exc}",
            status_code=401,
        )

    user_id = payload.get("sub")
    if not user_id:
        api_error(
            code="INVALID_REFRESH",
            message="Invalid token payload.",
            status_code=401,
        )

    db = await get_database()
    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        user = None

    if not user:
        api_error(
            code="INVALID_REFRESH",
            message="User associated with refresh token not found.",
            status_code=401,
        )

    token_data = {"sub": user_id, "email": user.get("email")}
    new_access_token = create_access_token(token_data)
    new_refresh_token = create_refresh_token(token_data)

    # Blacklist the old refresh token upon rotation
    await blacklist_token(refresh_token, token_type="refresh")

    return RefreshResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


async def logout(
    access_token: Optional[str] = None, refresh_token: Optional[str] = None
) -> LogoutResponse:
    """Invalidate active tokens by storing them in the MongoDB blacklist."""
    if not refresh_token or not refresh_token.strip():
        api_error(
            code="MISSING_TOKEN",
            message="Refresh token is required for logout.",
            status_code=400,
        )

    if access_token:
        await blacklist_token(access_token, token_type="access")
    await blacklist_token(refresh_token, token_type="refresh")

    return LogoutResponse(message="Successfully logged out")

