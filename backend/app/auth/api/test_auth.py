import asyncio
from datetime import datetime, timezone
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.api.auth import router
from app.auth.utils.auth import (
    blacklist_token,
    create_access_token,
    create_refresh_token,
    generate_token_pair,
    is_token_blacklisted,
)

from app.share.api.errors import register_error_handler


def _make_client() -> TestClient:
    app = FastAPI()
    register_error_handler(app)
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_api_google_login_success(fake_db, monkeypatch):
    monkeypatch.setattr(
        "app.auth.service.auth.verify_google_token",
        lambda token: {
            "email": "user@careera.io",
            "name": "Careera User",
            "avatar": "https://careera.io/avatar.png",
        },
    )

    client = _make_client()
    resp = client.post("/api/v1/auth/login", json={"id_token": "valid-google-token"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "Login successful"
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["email"] == "user@careera.io"
    assert data["user"]["name"] == "Careera User"
    assert data["user"]["avatar"] == "https://careera.io/avatar.png"


def test_api_google_login_missing_token(fake_db):
    client = _make_client()
    resp = client.post("/api/v1/auth/login", json={"id_token": "   "})

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"] == "MISSING_TOKEN"
    assert data["status_code"] == 400


def test_api_google_login_invalid_token(fake_db, monkeypatch):
    def _fail_verify(token):
        raise ValueError("Invalid signature")

    monkeypatch.setattr("app.auth.service.auth.verify_google_token", _fail_verify)

    client = _make_client()
    resp = client.post("/api/v1/auth/login", json={"id_token": "bad-token"})

    assert resp.status_code == 401
    data = resp.json()
    assert data["error"] == "INVALID_TOKEN"
    assert data["status_code"] == 401


def test_api_dev_login(fake_db):
    client = _make_client()
    resp = client.post(
        "/api/v1/auth/login/dev?email=developer@careera.io&name=SuperDev"
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["email"] == "developer@careera.io"
    assert data["user"]["name"] == "SuperDev"
    assert data["access_token"]
    assert data["refresh_token"]


def test_api_refresh_token_success(fake_db):
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

    refresh_token = create_refresh_token(
        {"sub": str(user_id), "email": "sarah@careera.io"}
    )

    client = _make_client()
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 900
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["refresh_token"] != refresh_token


def test_api_refresh_token_revoked(fake_db):
    user_id = ObjectId()
    refresh_token = create_refresh_token(
        {"sub": str(user_id), "email": "sarah@careera.io"}
    )

    asyncio.run(blacklist_token(refresh_token, token_type="refresh"))

    client = _make_client()
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    assert resp.status_code == 401
    data = resp.json()
    assert data["error"] == "INVALID_REFRESH"
    assert data["status_code"] == 401


def test_api_logout_success(fake_db):
    access_tok, refresh_tok = generate_token_pair({"sub": "user-123", "email": "test@careera.io"})

    client = _make_client()
    resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_tok}"},
        json={"refresh_token": refresh_tok},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "Successfully logged out"

    assert asyncio.run(is_token_blacklisted(access_tok)) is True
    assert asyncio.run(is_token_blacklisted(refresh_tok)) is True


def test_api_logout_unauthorized_without_bearer(fake_db):
    client = _make_client()
    resp = client.post("/api/v1/auth/logout", json={"refresh_token": "some-refresh"})
    assert resp.status_code == 401


def test_api_logout_missing_refresh_token(fake_db):
    access_tok, _ = generate_token_pair({"sub": "user-123", "email": "test@careera.io"})

    client = _make_client()
    resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_tok}"},
        json={"refresh_token": "   "},
    )

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"] == "MISSING_TOKEN"
    assert data["status_code"] == 400


def test_api_logout_invalid_refresh_token_string(fake_db):
    access_tok, _ = generate_token_pair({"sub": "user-123", "email": "test@careera.io"})

    client = _make_client()
    resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_tok}"},
        json={"refresh_token": "string"},
    )

    assert resp.status_code == 401
    data = resp.json()
    assert data["error"] == "INVALID_REFRESH"
    assert data["status_code"] == 401


def test_api_logout_cross_user_refresh_token(fake_db):
    access_tok, _ = generate_token_pair({"sub": "user-123", "email": "test@careera.io"})
    _, other_refresh_tok = generate_token_pair({"sub": "user-456", "email": "other@careera.io"})

    client = _make_client()
    resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_tok}"},
        json={"refresh_token": other_refresh_tok},
    )

    assert resp.status_code == 403
    data = resp.json()
    assert data["error"] == "INVALID_REFRESH"
    assert data["status_code"] == 403


def test_api_logout_session_mismatch(fake_db):
    access_tok_1, _ = generate_token_pair({"sub": "user-123", "email": "test@careera.io"})
    _, refresh_tok_2 = generate_token_pair({"sub": "user-123", "email": "test@careera.io"})

    client = _make_client()
    resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_tok_1}"},
        json={"refresh_token": refresh_tok_2},
    )

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"] == "SESSION_MISMATCH"
    assert data["status_code"] == 400


def test_api_logout_already_revoked_token(fake_db):
    access_tok, refresh_tok = generate_token_pair({"sub": "user-123", "email": "test@careera.io"})
    fake_db.refresh_tokens.docs.append({"token": refresh_tok, "type": "refresh"})

    client = _make_client()
    resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_tok}"},
        json={"refresh_token": refresh_tok},
    )

    assert resp.status_code == 401
    data = resp.json()
    assert data["error"] == "INVALID_REFRESH"
    assert data["status_code"] == 401


