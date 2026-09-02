from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class Interests(BaseModel):
    """User career and technical interest preferences."""

    roles: List[str] = Field(
        default_factory=list,
        description="Target job roles (e.g. ['Backend Engineer', 'DevOps'])",
    )
    focus_areas: List[str] = Field(
        default_factory=list,
        description="Technical focus domains (e.g. ['AI', 'Distributed Systems'])",
    )


class ProfileData(BaseModel):
    """Parsed user profile data extracted from documents and preferences."""

    cv_parsed_text: Optional[str] = None
    linkedin_parsed_text: Optional[str] = None
    interests: Optional[dict[str, Any]] = None



class UserGamification(BaseModel):
    """User gamification statistics."""

    total_xp: int = Field(default=0, ge=0)
    level: int = Field(default=1, ge=1)


class UserProfileResponse(BaseModel):
    """Full user profile response for GET /users/me."""

    id: str
    email: str
    name: str
    avatar: Optional[str] = None
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    profile: ProfileData = Field(default_factory=ProfileData)
    gamification: UserGamification = Field(default_factory=UserGamification)


class DataPreview(BaseModel):
    """Extracted text metadata returned to the client after document upload."""

    file_name: str
    text_length: int
    snippet: str


class UploadResponse(BaseModel):
    """Response returned upon successful PDF parsing."""

    message: str
    data_preview: DataPreview


class PreferencesUpdateRequest(BaseModel):
    """Payload for PATCH /users/me/preferences."""

    interests: Interests


class PreferencesUpdateResponse(BaseModel):
    """Response returned after updating user preferences."""

    message: str = "Preferences updated successfully"
    interests: Interests
