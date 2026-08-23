import asyncio
from datetime import datetime, timezone
import pytest
from bson import ObjectId

from app.profile.model.profile import Interests
from app.profile.service.profile import (
    extract_pdf_text,
    get_full_user,
    get_profile,
    update_preferences,
    upload_cv,
    upload_linkedin,
)
from app.share.api.errors import AppError

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


def test_get_profile_reads_users_document(fake_db):
    fake_db.users.docs.append(
        {
            "_id": ObjectId(USER_ID),
            "profile": {
                "cv_parsed_text": "Python backend",
                "linkedin_parsed_text": "API work",
                "interests": {"roles": ["Backend Engineer"], "focus_areas": ["AI"]},
            },
        }
    )

    profile = asyncio.run(get_profile(USER_ID))

    assert profile.cv_parsed_text == "Python backend"
    assert profile.linkedin_parsed_text == "API work"
    assert profile.interests == {"roles": ["Backend Engineer"], "focus_areas": ["AI"]}


def test_get_profile_missing_user_returns_empty_profile(fake_db):
    profile = asyncio.run(get_profile(str(ObjectId())))
    assert profile.cv_parsed_text is None
    assert profile.linkedin_parsed_text is None
    assert profile.interests is None


def test_get_full_user_success(fake_db):
    user_id = ObjectId()
    now = datetime.now(timezone.utc)
    fake_db.users.docs.append(
        {
            "_id": user_id,
            "email": "sarah@careera.io",
            "name": "Sarah Connor",
            "avatar": "https://careera.io/sarah.png",
            "created_at": now,
            "last_login": now,
            "profile": {
                "cv_parsed_text": "Full stack engineer",
                "linkedin_parsed_text": "Lead dev",
                "interests": {"roles": ["Full Stack"], "focus_areas": ["Web"]},
            },
            "gamification": {"total_xp": 500, "level": 2},
        }
    )

    resp = asyncio.run(get_full_user(str(user_id)))

    assert resp.id == str(user_id)
    assert resp.email == "sarah@careera.io"
    assert resp.name == "Sarah Connor"
    assert resp.avatar == "https://careera.io/sarah.png"
    assert resp.gamification.total_xp == 500
    assert resp.gamification.level == 2
    assert resp.profile.cv_parsed_text == "Full stack engineer"


def test_get_full_user_not_found_raises_404(fake_db):
    with pytest.raises(AppError) as exc_info:
        asyncio.run(get_full_user(str(ObjectId())))
    assert exc_info.value.code == "USER_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_extract_pdf_text_valid():
    text = extract_pdf_text(SAMPLE_PDF_BYTES, "resume.pdf")
    assert "John Doe" in text
    assert "Python Engineer" in text


def test_extract_pdf_text_invalid_extension():
    with pytest.raises(AppError) as exc_info:
        extract_pdf_text(SAMPLE_PDF_BYTES, "resume.docx")
    assert exc_info.value.code == "INVALID_FILE_TYPE"
    assert exc_info.value.status_code == 400


def test_extract_pdf_text_file_too_large():
    too_large_bytes = b"0" * (6 * 1024 * 1024)
    with pytest.raises(AppError) as exc_info:
        extract_pdf_text(too_large_bytes, "large.pdf")
    assert exc_info.value.code == "FILE_TOO_LARGE"
    assert exc_info.value.status_code == 413


def test_upload_cv_persists_in_mongodb(fake_db):
    user_id = ObjectId()
    fake_db.users.docs.append(
        {
            "_id": user_id,
            "email": "alex@careera.io",
            "name": "Alex",
            "profile": {},
        }
    )

    resp = asyncio.run(upload_cv(str(user_id), SAMPLE_PDF_BYTES, "cv.pdf"))

    assert resp.message == "CV parsed successfully"
    assert resp.data_preview.file_name == "cv.pdf"
    assert "John Doe" in resp.data_preview.snippet

    # Verify document in fake_db
    user_doc = fake_db.users.docs[0]
    assert "John Doe" in user_doc["profile"]["cv_parsed_text"]


def test_upload_cv_user_not_found_raises_404(fake_db):
    with pytest.raises(AppError) as exc_info:
        asyncio.run(upload_cv(str(ObjectId()), SAMPLE_PDF_BYTES, "cv.pdf"))
    assert exc_info.value.code == "USER_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_upload_linkedin_persists_in_mongodb(fake_db):
    user_id = ObjectId()
    fake_db.users.docs.append(
        {
            "_id": user_id,
            "email": "alex@careera.io",
            "name": "Alex",
            "profile": {},
        }
    )

    resp = asyncio.run(upload_linkedin(str(user_id), SAMPLE_PDF_BYTES, "linkedin.pdf"))

    assert resp.message == "LinkedIn profile parsed successfully"
    assert resp.data_preview.file_name == "linkedin.pdf"

    user_doc = fake_db.users.docs[0]
    assert "John Doe" in user_doc["profile"]["linkedin_parsed_text"]


def test_update_preferences_persists_in_mongodb(fake_db):
    user_id = ObjectId()
    fake_db.users.docs.append(
        {
            "_id": user_id,
            "email": "alex@careera.io",
            "name": "Alex",
            "profile": {},
        }
    )

    interests = Interests(
        roles=["DevOps Engineer", "Site Reliability Engineer"],
        focus_areas=["Kubernetes", "AWS"],
    )

    resp = asyncio.run(update_preferences(str(user_id), interests))

    assert resp.message == "Preferences updated successfully"
    assert resp.interests.roles == ["DevOps Engineer", "Site Reliability Engineer"]

    user_doc = fake_db.users.docs[0]
    assert user_doc["profile"]["interests"]["roles"] == [
        "DevOps Engineer",
        "Site Reliability Engineer",
    ]


def test_update_preferences_user_not_found_raises_404(fake_db):
    interests = Interests(roles=["AI Engineer"], focus_areas=["LLMs"])
    with pytest.raises(AppError) as exc_info:
        asyncio.run(update_preferences(str(ObjectId()), interests))
    assert exc_info.value.code == "USER_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_upload_cv_with_null_profile_initializes_structure(fake_db):
    user_id = ObjectId()
    fake_db.users.docs.append({"_id": user_id, "email": "nullprof@careera.io", "profile": None})

    resp = asyncio.run(upload_cv(str(user_id), SAMPLE_PDF_BYTES, "cv.pdf"))
    assert resp.message == "CV parsed successfully"
    user = asyncio.run(fake_db.users.find_one({"_id": user_id}))
    assert user["profile"]["cv_parsed_text"] == "John Doe Senior Python Engineer"


def test_upload_linkedin_with_null_profile_initializes_structure(fake_db):
    user_id = ObjectId()
    fake_db.users.docs.append({"_id": user_id, "email": "nullprof2@careera.io", "profile": None})

    resp = asyncio.run(upload_linkedin(str(user_id), SAMPLE_PDF_BYTES, "linkedin.pdf"))
    assert resp.message == "LinkedIn profile parsed successfully"
    user = asyncio.run(fake_db.users.find_one({"_id": user_id}))
    assert user["profile"]["linkedin_parsed_text"] == "John Doe Senior Python Engineer"


def test_update_preferences_with_null_profile_initializes_structure(fake_db):
    user_id = ObjectId()
    fake_db.users.docs.append({"_id": user_id, "email": "nullprof3@careera.io", "profile": None})
    interests = Interests(roles=["AI Engineer"], focus_areas=["FastAPI"])

    resp = asyncio.run(update_preferences(str(user_id), interests))
    assert resp.message == "Preferences updated successfully"
    user = asyncio.run(fake_db.users.find_one({"_id": user_id}))
    assert user["profile"]["interests"]["roles"] == ["AI Engineer"]


