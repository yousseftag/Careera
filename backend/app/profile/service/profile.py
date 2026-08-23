import io
from typing import Any, Optional
from bson import ObjectId
import pypdf

from app.database.connection import get_database
from app.profile.model.profile import (
    DataPreview,
    Interests,
    PreferencesUpdateResponse,
    ProfileData,
    UploadResponse,
    UserGamification,
    UserProfileResponse,
)
from app.share.api.errors import api_error

MAX_PDF_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


async def get_profile(user_id: str) -> ProfileData:
    """Return the user's parsed profile fields.

    A missing user document yields an empty ProfileData; callers such
    as career analysis surface the documented PROFILE_INCOMPLETE error.
    """
    db = await get_database()
    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        user = None

    if user is None:
        return ProfileData()

    profile = user.get("profile") or {}
    return ProfileData(
        cv_parsed_text=profile.get("cv_parsed_text"),
        linkedin_parsed_text=profile.get("linkedin_parsed_text"),
        interests=profile.get("interests"),
    )


async def get_full_user(user_id: str) -> UserProfileResponse:
    """Retrieve full user profile with gamification stats.

    Raises 404 USER_NOT_FOUND if user does not exist.
    """
    db = await get_database()
    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        user = None

    if not user:
        api_error(
            code="USER_NOT_FOUND",
            message="User profile not found.",
            status_code=404,
        )

    profile_doc = user.get("profile") or {}
    gamification_doc = user.get("gamification") or {}

    profile = ProfileData(
        cv_parsed_text=profile_doc.get("cv_parsed_text"),
        linkedin_parsed_text=profile_doc.get("linkedin_parsed_text"),
        interests=profile_doc.get("interests"),
    )

    gamification = UserGamification(
        total_xp=gamification_doc.get("total_xp", 0),
        level=gamification_doc.get("level", 1),
    )

    return UserProfileResponse(
        id=str(user["_id"]),
        email=user.get("email", ""),
        name=user.get("name", ""),
        avatar=user.get("avatar"),
        created_at=user.get("created_at"),
        last_login=user.get("last_login"),
        profile=profile,
        gamification=gamification,
    )


def extract_pdf_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from an in-memory PDF file.

    Validates extension, size limits, and non-empty text extraction.
    """
    if not filename.lower().endswith(".pdf"):
        api_error(
            code="INVALID_FILE_TYPE",
            message="Only PDF files are supported.",
            status_code=400,
        )

    if len(file_bytes) > MAX_PDF_SIZE_BYTES:
        api_error(
            code="FILE_TOO_LARGE",
            message="File size exceeds maximum limit of 5MB.",
            status_code=413,
        )

    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        extracted_text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                extracted_text += page_text + "\n"
        extracted_text = extracted_text.strip()
    except Exception as exc:
        api_error(
            code="INVALID_FILE_TYPE",
            message=f"Could not parse PDF document: {exc}",
            status_code=400,
        )

    if not extracted_text:
        api_error(
            code="UNREADABLE_PDF",
            message="Could not extract text from the PDF. Please ensure the document is not an empty or scanned image.",
            status_code=400,
        )

    return extracted_text


async def upload_cv(user_id: str, file_bytes: bytes, filename: str) -> UploadResponse:
    """Extract text from CV PDF and save to users.profile.cv_parsed_text."""
    text = extract_pdf_text(file_bytes, filename)
    db = await get_database()

    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        user = None

    if not user:
        api_error(
            code="USER_NOT_FOUND",
            message="User profile not found.",
            status_code=404,
        )

    profile_data = user.get("profile")
    if not isinstance(profile_data, dict):
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "profile": {
                        "cv_parsed_text": text,
                        "linkedin_parsed_text": None,
                        "interests": {"roles": [], "focus_areas": []},
                    }
                }
            },
        )
    else:
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"profile.cv_parsed_text": text}},
        )

    preview = DataPreview(
        file_name=filename,
        text_length=len(text),
        snippet=text[:200] + ("..." if len(text) > 200 else ""),
    )

    return UploadResponse(
        message="CV parsed successfully",
        data_preview=preview,
    )


async def upload_linkedin(
    user_id: str, file_bytes: bytes, filename: str
) -> UploadResponse:
    """Extract text from LinkedIn PDF and save to users.profile.linkedin_parsed_text."""
    text = extract_pdf_text(file_bytes, filename)
    db = await get_database()

    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        user = None

    if not user:
        api_error(
            code="USER_NOT_FOUND",
            message="User profile not found.",
            status_code=404,
        )

    profile_data = user.get("profile")
    if not isinstance(profile_data, dict):
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "profile": {
                        "cv_parsed_text": None,
                        "linkedin_parsed_text": text,
                        "interests": {"roles": [], "focus_areas": []},
                    }
                }
            },
        )
    else:
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"profile.linkedin_parsed_text": text}},
        )

    preview = DataPreview(
        file_name=filename,
        text_length=len(text),
        snippet=text[:200] + ("..." if len(text) > 200 else ""),
    )

    return UploadResponse(
        message="LinkedIn profile parsed successfully",
        data_preview=preview,
    )


async def update_preferences(
    user_id: str, interests: Interests
) -> PreferencesUpdateResponse:
    """Update career preferences in users.profile.interests."""
    db = await get_database()

    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        user = None

    if not user:
        api_error(
            code="USER_NOT_FOUND",
            message="User profile not found.",
            status_code=404,
        )

    profile_data = user.get("profile")
    if not isinstance(profile_data, dict):
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "profile": {
                        "cv_parsed_text": None,
                        "linkedin_parsed_text": None,
                        "interests": interests.model_dump(),
                    }
                }
            },
        )
    else:
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"profile.interests": interests.model_dump()}},
        )

    return PreferencesUpdateResponse(
        message="Preferences updated successfully",
        interests=interests,
    )

