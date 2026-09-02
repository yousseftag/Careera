from fastapi import APIRouter, Depends, File, UploadFile

from app.auth.utils.auth import get_current_user
from app.profile.model.profile import (
    PreferencesUpdateRequest,
    PreferencesUpdateResponse,
    UploadResponse,
    UserProfileResponse,
)
from app.profile.service import profile as profile_service

router = APIRouter(prefix="/users", tags=["Profile"])


@router.get("/me", response_model=UserProfileResponse, status_code=200)
async def get_current_user_profile(
    current_user: dict = Depends(get_current_user),
) -> UserProfileResponse:
    """Retrieve current authenticated user's profile and gamification stats."""
    return await profile_service.get_full_user(current_user["user_id"])


@router.post("/me/upload-cv", response_model=UploadResponse, status_code=200)
async def upload_cv(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> UploadResponse:
    """Upload and parse Resume/CV PDF into users.profile.cv_parsed_text."""
    file_bytes = await file.read()
    return await profile_service.upload_cv(
        user_id=current_user["user_id"],
        file_bytes=file_bytes,
        filename=file.filename or "cv.pdf",
    )


@router.post("/me/upload-linkedin", response_model=UploadResponse, status_code=200)
async def upload_linkedin(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> UploadResponse:
    """Upload and parse LinkedIn PDF export into users.profile.linkedin_parsed_text."""
    file_bytes = await file.read()
    return await profile_service.upload_linkedin(
        user_id=current_user["user_id"],
        file_bytes=file_bytes,
        filename=file.filename or "linkedin.pdf",
    )


@router.patch("/me/preferences", response_model=PreferencesUpdateResponse, status_code=200)
async def update_preferences(
    body: PreferencesUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> PreferencesUpdateResponse:
    """Update user career interests and focus areas."""
    return await profile_service.update_preferences(
        user_id=current_user["user_id"],
        interests=body.interests,
    )
