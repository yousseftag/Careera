import asyncio
from datetime import datetime, timezone
import pytest
from bson import ObjectId

from app.auth.service.auth import (
    dev_login,
    login_with_google,
    logout,
    refresh_access_token,
)
from app.auth.utils.auth import (
    blacklist_token,
    create_access_token,
    create_refresh_token,
    generate_token_pair,
    is_token_blacklisted,
    verify_token,
)

from app.share.api.errors import AppError


def test_login_with_google_missing_token_raises_400(fake_db):
    async def scenario():
        with pytest.raises(AppError) as exc_info:
            await login_with_google("")
        assert exc_info.value.code == "MISSING_TOKEN"
        assert exc_info.value.status_code == 400

    asyncio.run(scenario())


def test_login_with_google_invalid_token_raises_401(fake_db, monkeypatch):
    def _mock_verify_fail(token):
        raise ValueError("Invalid Google signature")

    monkeypatch.setattr("app.auth.service.auth.verify_google_token", _mock_verify_fail)

    async def scenario():
        with pytest.raises(AppError) as exc_info:
            await login_with_google("invalid-id-token")
        assert exc_info.value.code == "INVALID_TOKEN"
        assert exc_info.value.status_code == 401

    asyncio.run(scenario())


def test_login_with_google_creates_new_user(fake_db, monkeypatch):
    monkeypatch.setattr(
        "app.auth.service.auth.verify_google_token",
        lambda token: {
            "email": "alex@careera.io",
            "name": "Alex Smith",
            "avatar": "https://careera.io/avatar.png",
            "google_id": "google-12345",
        },
    )

    async def scenario():
        resp = await login_with_google("valid-token")

        assert resp.message == "Login successful"
        assert resp.token_type == "bearer"
        assert resp.user.email == "alex@careera.io"
        assert resp.user.name == "Alex Smith"
        assert resp.user.avatar == "https://careera.io/avatar.png"
        assert resp.access_token
        assert resp.refresh_token

        # Verify user was saved in database
        user_doc = fake_db.users.docs[0]
        assert user_doc["email"] == "alex@careera.io"
        assert user_doc["gamification"]["total_xp"] == 0
        assert user_doc["gamification"]["level"] == 1
        assert user_doc["profile"]["cv_parsed_text"] is None

        # Verify generated access token is valid
        decoded = verify_token(resp.access_token, token_type="access")
        assert decoded["sub"] == str(user_doc["_id"])
        assert decoded["email"] == "alex@careera.io"

    asyncio.run(scenario())


def test_login_with_google_updates_existing_user(fake_db, monkeypatch):
    user_id = ObjectId()
    old_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fake_db.users.docs.append(
        {
            "_id": user_id,
            "email": "alex@careera.io",
            "name": "Alex",
            "avatar": None,
            "created_at": old_time,
            "last_login": old_time,
            "profile": {"cv_parsed_text": "Experienced Dev", "interests": {}},
            "gamification": {"total_xp": 100, "level": 1},
        }
    )

    monkeypatch.setattr(
        "app.auth.service.auth.verify_google_token",
        lambda token: {
            "email": "alex@careera.io",
            "name": "Alex",
            "avatar": "https://careera.io/new-avatar.png",
        },
    )

    async def scenario():
        resp = await login_with_google("valid-token")

        assert resp.user.id == str(user_id)
        assert resp.user.avatar == "https://careera.io/new-avatar.png"
        assert len(fake_db.users.docs) == 1
        assert fake_db.users.docs[0]["last_login"] > old_time

    asyncio.run(scenario())


def test_dev_login_creates_and_retrieves_user(fake_db):
    async def scenario():
        resp1 = await dev_login("developer@careera.io", "Dev One")
        assert resp1.user.email == "developer@careera.io"
        assert resp1.user.name == "Dev One"
        assert len(fake_db.users.docs) == 1

        resp2 = await dev_login("developer@careera.io", "Dev One")
        assert resp2.user.id == resp1.user.id
        assert len(fake_db.users.docs) == 1

    asyncio.run(scenario())


def test_refresh_access_token_success_with_rotation(fake_db):
    user_id = ObjectId()
    fake_db.users.docs.append(
        {
            "_id": user_id,
            "email": "sarah@careera.io",
            "name": "Sarah",
            "created_at": datetime.now(timezone.utc),
            "last_login": datetime.now(timezone.utc),
        }
    )

    token_data = {"sub": str(user_id), "email": "sarah@careera.io"}
    refresh_token = create_refresh_token(token_data)

    async def scenario():
        resp = await refresh_access_token(refresh_token)

        assert resp.token_type == "bearer"
        assert resp.expires_in == 900
        assert resp.access_token
        assert resp.refresh_token
        assert resp.refresh_token != refresh_token

        # Verify newly generated access token
        access_payload = verify_token(resp.access_token, token_type="access")
        assert access_payload["sub"] == str(user_id)
        assert access_payload["email"] == "sarah@careera.io"

        # Verify newly generated rotated refresh token
        refresh_payload = verify_token(resp.refresh_token, token_type="refresh")
        assert refresh_payload["sub"] == str(user_id)
        assert refresh_payload["email"] == "sarah@careera.io"

        # Verify old refresh token is now blacklisted
        assert await is_token_blacklisted(refresh_token) is True

        # Replay attempt with old refresh token should fail with 401
        with pytest.raises(AppError) as exc_info:
            await refresh_access_token(refresh_token)
        assert exc_info.value.code == "INVALID_REFRESH"
        assert exc_info.value.status_code == 401

        # But new rotated refresh token should work!
        resp2 = await refresh_access_token(resp.refresh_token)
        assert resp2.access_token
        assert resp2.refresh_token != resp.refresh_token

    asyncio.run(scenario())


def test_refresh_access_token_blacklisted_raises_401(fake_db):
    user_id = ObjectId()
    token_data = {"sub": str(user_id), "email": "sarah@careera.io"}
    refresh_token = create_refresh_token(token_data)

    async def scenario():
        await blacklist_token(refresh_token, token_type="refresh")

        with pytest.raises(AppError) as exc_info:
            await refresh_access_token(refresh_token)
        assert exc_info.value.code == "INVALID_REFRESH"
        assert exc_info.value.status_code == 401

    asyncio.run(scenario())


def test_refresh_access_token_wrong_type_raises_401(fake_db):
    user_id = ObjectId()
    token_data = {"sub": str(user_id), "email": "sarah@careera.io"}
    access_token = create_access_token(token_data)

    async def scenario():
        with pytest.raises(AppError) as exc_info:
            await refresh_access_token(access_token)
        assert exc_info.value.code == "INVALID_REFRESH"
        assert exc_info.value.status_code == 401

    asyncio.run(scenario())


def test_refresh_access_token_unknown_user_raises_401(fake_db):
    token_data = {"sub": str(ObjectId()), "email": "ghost@careera.io"}
    refresh_token = create_refresh_token(token_data)

    async def scenario():
        with pytest.raises(AppError) as exc_info:
            await refresh_access_token(refresh_token)
        assert exc_info.value.code == "INVALID_REFRESH"
        assert exc_info.value.status_code == 401

    asyncio.run(scenario())


def test_logout_missing_refresh_token_raises_400(fake_db):
    async def scenario():
        with pytest.raises(AppError) as exc_info:
            await logout(
                current_user={"user_id": "user-1"},
                access_token="any-token",
                refresh_token="",
            )
        assert exc_info.value.code == "MISSING_TOKEN"
        assert exc_info.value.status_code == 400

    asyncio.run(scenario())


def test_logout_malformed_refresh_token_raises_401(fake_db):
    async def scenario():
        with pytest.raises(AppError) as exc_info:
            await logout(
                current_user={"user_id": "user-1"},
                access_token="any-token",
                refresh_token="string",
            )
        assert exc_info.value.code == "INVALID_REFRESH"
        assert exc_info.value.status_code == 401

    asyncio.run(scenario())


def test_logout_cross_user_refresh_token_raises_403(fake_db):
    other_user_refresh_tok = create_refresh_token({"sub": "user-2", "email": "other@careera.io"})
    async def scenario():
        with pytest.raises(AppError) as exc_info:
            await logout(
                current_user={"user_id": "user-1"},
                access_token="any-token",
                refresh_token=other_user_refresh_tok,
            )
        assert exc_info.value.code == "INVALID_REFRESH"
        assert exc_info.value.status_code == 403

    asyncio.run(scenario())


def test_logout_session_mismatch_raises_400(fake_db):
    access_tok_1, _ = generate_token_pair({"sub": "user-1", "email": "test@careera.io"})
    _, refresh_tok_2 = generate_token_pair({"sub": "user-1", "email": "test@careera.io"})

    async def scenario():
        with pytest.raises(AppError) as exc_info:
            await logout(
                current_user={"user_id": "user-1"},
                access_token=access_tok_1,
                refresh_token=refresh_tok_2,
            )
        assert exc_info.value.code == "SESSION_MISMATCH"
        assert exc_info.value.status_code == 400

    asyncio.run(scenario())


def test_logout_already_blacklisted_token_raises_401(fake_db):
    access_tok, refresh_tok = generate_token_pair({"sub": "user-1", "email": "test@careera.io"})
    fake_db.refresh_tokens.docs.append({"token": refresh_tok, "type": "refresh"})

    async def scenario():
        with pytest.raises(AppError) as exc_info:
            await logout(
                current_user={"user_id": "user-1"},
                access_token=access_tok,
                refresh_token=refresh_tok,
            )
        assert exc_info.value.code == "INVALID_REFRESH"
        assert exc_info.value.status_code == 401

    asyncio.run(scenario())


def test_logout_blacklists_both_tokens(fake_db):
    access_tok, refresh_tok = generate_token_pair({"sub": "user-1", "email": "test@careera.io"})

    async def scenario():
        resp = await logout(
            current_user={"user_id": "user-1"},
            access_token=access_tok,
            refresh_token=refresh_tok,
        )
        assert resp.message == "Successfully logged out"

        assert await is_token_blacklisted(access_tok) is True
        assert await is_token_blacklisted(refresh_tok) is True
        assert len(fake_db.refresh_tokens.docs) == 2

    asyncio.run(scenario())



