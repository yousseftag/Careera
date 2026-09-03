from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.auth.utils.auth import get_current_user
from app.career.model.path import (
    ArchiveResponse,
    CreatePathRequest,
    DeleteResponse,
    PathDetail,
    PathList,
    PathStatus,
    RestoreResponse,
)
from app.career.service import path as path_service

router = APIRouter(prefix="/careers", tags=["Career Paths"])


@router.post("/paths", response_model=PathDetail, status_code=201)
async def create_path(
    request: CreatePathRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
) -> PathDetail:
    """Create a career path from a recommendation."""
    return await path_service.create_path(
        user_id=current_user["user_id"],
        request=request,
        background_tasks=background_tasks,
    )


@router.get("/paths", response_model=PathList)
async def list_paths(
    status: Optional[PathStatus] = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> PathList:
    """List career paths for the current user."""
    return await path_service.list_paths(
        user_id=current_user["user_id"],
        status=status,
    )


@router.get("/paths/{path_id}", response_model=PathDetail)
async def get_path(
    path_id: str,
    current_user: dict = Depends(get_current_user),
) -> PathDetail:
    """Get full details of a specific career path."""
    return await path_service.get_path(
        user_id=current_user["user_id"],
        path_id=path_id,
    )


@router.patch("/paths/{path_id}/archive", response_model=ArchiveResponse)
async def archive_path(
    path_id: str,
    current_user: dict = Depends(get_current_user),
) -> ArchiveResponse:
    """Archive an active career path."""
    return await path_service.archive_path(
        user_id=current_user["user_id"],
        path_id=path_id,
    )


@router.delete("/paths/{path_id}", response_model=DeleteResponse)
async def delete_path(
    path_id: str,
    current_user: dict = Depends(get_current_user),
) -> DeleteResponse:
    """Soft delete a career path."""
    return await path_service.delete_path(
        user_id=current_user["user_id"],
        path_id=path_id,
    )


@router.patch("/paths/{path_id}/restore", response_model=RestoreResponse)
async def restore_path(
    path_id: str,
    current_user: dict = Depends(get_current_user),
) -> RestoreResponse:
    """Restore a soft-deleted career path."""
    return await path_service.restore_path(
        user_id=current_user["user_id"],
        path_id=path_id,
    )
