import asyncio
from datetime import datetime, timezone
import pytest
from fastapi import BackgroundTasks
from bson import ObjectId

from app.career.model.analysis import AnalysisStatus
from app.career.model.path import CreatePathRequest, PathStatus, NodeStatus
from app.career.service import path as path_service
from app.share.api.errors import AppError

LLM_PATH_RESULT = {
    "title": "Backend Engineer Career Path",
    "description": "Step-by-step roadmap to master backend engineering.",
    "tags": ["Backend", "Python"],
    "missing_skills": ["Docker", "System Design"],
    "nodes": [
        {
            "title": "Python & API Fundamentals",
            "description": "Master Python syntax and REST design.",
            "type": "LEARNING",
            "difficulty": "EASY",
            "tags": ["Python", "APIs"],
        },
        {
            "title": "Scalable API Project",
            "description": "Build a production-grade API.",
            "type": "PROJECT",
            "difficulty": "MEDIUM",
            "tags": ["Project"],
        },
    ],
}


@pytest.fixture(autouse=True)
def mock_path_llm(monkeypatch):
    async def _fake_generate_json(**kwargs):
        return LLM_PATH_RESULT

    monkeypatch.setattr("app.career.service.path.generate_json", _fake_generate_json)


@pytest.mark.anyio
async def test_create_path_success(fake_db):
    user_id = str(ObjectId())
    user_oid = ObjectId(user_id)
    analysis_id = str(ObjectId())
    analysis_oid = ObjectId(analysis_id)

    # Insert READY analysis with 1 recommendation
    await fake_db.analyses.insert_one(
        {
            "_id": analysis_oid,
            "user_id": user_oid,
            "status": AnalysisStatus.READY.value,
            "created_at": datetime.now(timezone.utc),
            "recommendations": [
                {
                    "rec_index": 0,
                    "title": "Backend Engineer",
                    "description": "Build scalable APIs",
                    "match_score": 90,
                    "reasoning": "Strong Python skills",
                    "missing_skills": ["Docker"],
                    "tags": ["Backend"],
                    "is_expanded": False,
                    "linked_path_id": None,
                }
            ],
        }
    )

    bg_tasks = BackgroundTasks()
    request = CreatePathRequest(analysis_id=analysis_id, rec_index=0)
    detail1 = await path_service.create_path(
        user_id=user_id, request=request, background_tasks=bg_tasks
    )

    assert detail1.title == "Backend Engineer Career Path"
    assert detail1.analysis_id == analysis_id
    assert detail1.status == PathStatus.ACTIVE

    # Check analysis doc updated
    updated_analysis = await fake_db.analyses.find_one({"_id": analysis_oid})
    assert updated_analysis["recommendations"][0]["is_expanded"] is True
    assert str(updated_analysis["recommendations"][0]["linked_path_id"]) == detail1.path_id

    # Idempotent re-creation call returns identical existing path without duplicate insertion
    detail2 = await path_service.create_path(
        user_id=user_id, request=request, background_tasks=bg_tasks
    )
    assert detail2.path_id == detail1.path_id


@pytest.mark.anyio
async def test_create_path_analysis_not_found(fake_db):
    user_id = str(ObjectId())
    fake_analysis_id = str(ObjectId())
    bg_tasks = BackgroundTasks()
    request = CreatePathRequest(analysis_id=fake_analysis_id, rec_index=0)

    with pytest.raises(AppError) as exc_info:
        await path_service.create_path(
            user_id=user_id, request=request, background_tasks=bg_tasks
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "ANALYSIS_NOT_FOUND"


@pytest.mark.anyio
async def test_create_path_recommendation_not_found(fake_db):
    user_id = str(ObjectId())
    user_oid = ObjectId(user_id)
    analysis_id = str(ObjectId())
    analysis_oid = ObjectId(analysis_id)

    await fake_db.analyses.insert_one(
        {
            "_id": analysis_oid,
            "user_id": user_oid,
            "status": AnalysisStatus.READY.value,
            "recommendations": [],
        }
    )

    bg_tasks = BackgroundTasks()
    request = CreatePathRequest(analysis_id=analysis_id, rec_index=5)

    with pytest.raises(AppError) as exc_info:
        await path_service.create_path(
            user_id=user_id, request=request, background_tasks=bg_tasks
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "RECOMMENDATION_NOT_FOUND"


@pytest.mark.anyio
async def test_list_paths_calculates_progress(fake_db):
    user_id = str(ObjectId())
    user_oid = ObjectId(user_id)

    await fake_db.career_paths.insert_one(
        {
            "user_id": user_oid,
            "title": "Path 1",
            "status": PathStatus.ACTIVE.value,
            "created_at": datetime.now(timezone.utc),
            "total_nodes": 4,
            "nodes": [
                {"step": 0, "type": "LEARNING", "difficulty": "EASY", "status": "COMPLETED"},
                {"step": 1, "type": "LEARNING", "difficulty": "MEDIUM", "status": "UNLOCKED"},
                {"step": 2, "type": "PROJECT", "difficulty": "MEDIUM", "status": "LOCKED"},
                {"step": 3, "type": "INTERVIEW", "difficulty": "HARD", "status": "LOCKED"},
            ],
        }
    )

    paths_list = await path_service.list_paths(user_id=user_id)
    assert len(paths_list.paths) == 1
    assert paths_list.paths[0].progress.completed_nodes == 1
    assert paths_list.paths[0].progress.percentage == 25


@pytest.mark.anyio
async def test_archive_delete_restore_lifecycle(fake_db):
    user_id = str(ObjectId())
    user_oid = ObjectId(user_id)

    res = await fake_db.career_paths.insert_one(
        {
            "user_id": user_oid,
            "title": "Path Lifecycle",
            "status": PathStatus.ACTIVE.value,
            "created_at": datetime.now(timezone.utc),
            "total_nodes": 1,
            "nodes": [],
        }
    )
    path_id = str(res.inserted_id)

    # Archive
    arch_res = await path_service.archive_path(user_id=user_id, path_id=path_id)
    assert arch_res.status == PathStatus.ARCHIVED

    # Cannot restore non-deleted path
    with pytest.raises(AppError) as exc_info:
        await path_service.restore_path(user_id=user_id, path_id=path_id)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "PATH_NOT_DELETED"

    # Soft delete
    del_res = await path_service.delete_path(user_id=user_id, path_id=path_id)
    assert del_res.status == PathStatus.DELETED
    assert del_res.deleted_at is not None

    # Cannot archive an already deleted path -> 404 PATH_NOT_FOUND
    with pytest.raises(AppError) as exc_info:
        await path_service.archive_path(user_id=user_id, path_id=path_id)
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "PATH_NOT_FOUND"

    # List paths excludes soft deleted by default
    paths_list = await path_service.list_paths(user_id=user_id)
    assert len(paths_list.paths) == 0

    # Restore
    rest_res = await path_service.restore_path(user_id=user_id, path_id=path_id)
    assert rest_res.status == PathStatus.ACTIVE
    assert rest_res.deleted_at is None
