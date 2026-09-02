from datetime import datetime, timezone
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.utils.auth import get_current_user
from app.profile.api.profile import router
from app.share.api.errors import register_error_handler

USER_ID = str(ObjectId())

SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
    b"4 0 obj << /Length 55 >> stream\n"
    b"BT /F1 12 Tf 100 700 Td (John Doe Senior Python Engineer) Tj ET\n"
    b"endstream\nendobj\n"
    b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
    b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000244 00000 n \n0000000350 00000 n \n"
    b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n428\n%%EOF\n"
)


def _make_client(user_id: str | None = USER_ID) -> TestClient:
    app = FastAPI()
    register_error_handler(app)
    app.include_router(router, prefix="/api/v1")
    if user_id:
        app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id}
    return TestClient(app)


def test_api_get_my_profile_success(fake_db):
    now = datetime.now(timezone.utc)
    fake_db.users.docs.append(
        {
            "_id": ObjectId(USER_ID),
            "email": "sarah@careera.io",
            "name": "Sarah",
            "avatar": "https://careera.io/avatar.png",
            "created_at": now,
            "last_login": now,
            "profile": {
                "cv_parsed_text": "Experienced Python Engineer",
                "linkedin_parsed_text": "Lead Backend Dev",
                "interests": {"roles": ["Backend"], "focus_areas": ["APIs"]},
            },
            "gamification": {"total_xp": 100, "level": 1},
        }
    )

    client = _make_client()
    resp = client.get("/api/v1/users/me")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == USER_ID
    assert data["email"] == "sarah@careera.io"
    assert data["name"] == "Sarah"
    assert data["profile"]["cv_parsed_text"] == "Experienced Python Engineer"
    assert data["gamification"]["total_xp"] == 100


def test_api_get_my_profile_unauthorized(fake_db):
    client = _make_client(user_id=None)
    resp = client.get("/api/v1/users/me")
    assert resp.status_code == 401


def test_api_upload_cv_success(fake_db):
    fake_db.users.docs.append(
        {
            "_id": ObjectId(USER_ID),
            "email": "sarah@careera.io",
            "name": "Sarah",
            "profile": {},
        }
    )

    client = _make_client()
    resp = client.post(
        "/api/v1/users/me/upload-cv",
        files={"file": ("resume.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "CV parsed successfully"
    assert data["data_preview"]["file_name"] == "resume.pdf"
    assert "John Doe" in data["data_preview"]["snippet"]

    # Verify MongoDB record updated
    assert "John Doe" in fake_db.users.docs[0]["profile"]["cv_parsed_text"]


def test_api_upload_cv_invalid_extension(fake_db):
    fake_db.users.docs.append(
        {"_id": ObjectId(USER_ID), "email": "sarah@careera.io", "profile": {}}
    )

    client = _make_client()
    resp = client.post(
        "/api/v1/users/me/upload-cv",
        files={"file": ("resume.txt", b"plain text", "text/plain")},
    )

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"] == "INVALID_FILE_TYPE"
    assert data["status_code"] == 400


def test_api_upload_linkedin_success(fake_db):
    fake_db.users.docs.append(
        {
            "_id": ObjectId(USER_ID),
            "email": "sarah@careera.io",
            "name": "Sarah",
            "profile": {},
        }
    )

    client = _make_client()
    resp = client.post(
        "/api/v1/users/me/upload-linkedin",
        files={"file": ("profile.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "LinkedIn profile parsed successfully"
    assert "John Doe" in fake_db.users.docs[0]["profile"]["linkedin_parsed_text"]


def test_api_update_preferences_success(fake_db):
    fake_db.users.docs.append(
        {
            "_id": ObjectId(USER_ID),
            "email": "sarah@careera.io",
            "name": "Sarah",
            "profile": {},
        }
    )

    client = _make_client()
    resp = client.patch(
        "/api/v1/users/me/preferences",
        json={
            "interests": {
                "roles": ["DevOps Engineer", "Cloud Architect"],
                "focus_areas": ["Kubernetes", "AWS"],
            }
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "Preferences updated successfully"
    assert data["interests"]["roles"] == ["DevOps Engineer", "Cloud Architect"]
    assert data["interests"]["focus_areas"] == ["Kubernetes", "AWS"]

    # Verify MongoDB record updated
    assert fake_db.users.docs[0]["profile"]["interests"]["roles"] == [
        "DevOps Engineer",
        "Cloud Architect",
    ]
