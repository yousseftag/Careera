from datetime import datetime, timezone
from app.profile.model.profile import (
    DataPreview,
    Interests,
    PreferencesUpdateRequest,
    PreferencesUpdateResponse,
    ProfileData,
    UploadResponse,
    UserGamification,
    UserProfileResponse,
)


def test_user_profile_response_serialization():
    now = datetime.now(timezone.utc)
    profile = ProfileData(
        cv_parsed_text="Software engineer with Python experience",
        linkedin_parsed_text="Backend developer",
        interests={"roles": ["Backend Engineer"], "focus_areas": ["AI", "APIs"]},
    )
    gamification = UserGamification(total_xp=250, level=2)

    user_resp = UserProfileResponse(
        id="60d5ec49f1b2c8b1f8e4e1a1",
        email="alex@careera.io",
        name="Alex Smith",
        avatar="https://avatar.url/alex.png",
        created_at=now,
        last_login=now,
        profile=profile,
        gamification=gamification,
    )

    data = user_resp.model_dump()
    assert data["id"] == "60d5ec49f1b2c8b1f8e4e1a1"
    assert data["email"] == "alex@careera.io"
    assert data["profile"]["cv_parsed_text"] == "Software engineer with Python experience"
    assert data["profile"]["interests"]["roles"] == ["Backend Engineer"]
    assert data["profile"]["interests"]["focus_areas"] == ["AI", "APIs"]
    assert data["gamification"]["total_xp"] == 250
    assert data["gamification"]["level"] == 2


def test_user_profile_response_defaults():
    user_resp = UserProfileResponse(
        id="user-123",
        email="dev@careera.io",
        name="Dev",
    )

    assert user_resp.avatar is None
    assert user_resp.profile.cv_parsed_text is None
    assert user_resp.gamification.total_xp == 0
    assert user_resp.gamification.level == 1


def test_upload_response_model():
    preview = DataPreview(
        file_name="resume.pdf",
        text_length=1500,
        snippet="John Doe, Senior Python Developer...",
    )
    resp = UploadResponse(
        message="CV parsed successfully",
        data_preview=preview,
    )

    data = resp.model_dump()
    assert data["message"] == "CV parsed successfully"
    assert data["data_preview"]["file_name"] == "resume.pdf"
    assert data["data_preview"]["text_length"] == 1500
    assert "John Doe" in data["data_preview"]["snippet"]


def test_preferences_update_request_and_response():
    req = PreferencesUpdateRequest(
        interests=Interests(
            roles=["DevOps Engineer", "Cloud Architect"],
            focus_areas=["Kubernetes", "Terraform"],
        )
    )
    assert req.interests.roles == ["DevOps Engineer", "Cloud Architect"]
    assert req.interests.focus_areas == ["Kubernetes", "Terraform"]

    resp = PreferencesUpdateResponse(interests=req.interests)
    assert resp.message == "Preferences updated successfully"
    assert resp.interests.roles == ["DevOps Engineer", "Cloud Architect"]
