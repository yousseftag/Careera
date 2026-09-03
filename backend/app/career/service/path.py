import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks

from app.career.model.analysis import AnalysisStatus
from app.career.model.path import (
    ArchiveResponse,
    CareerPathLLMOutput,
    CreatePathRequest,
    DeleteResponse,
    NodeDifficulty,
    NodeStatus,
    NodeType,
    PathDetail,
    PathList,
    PathNode,
    PathProgress,
    PathStatus,
    PathSummary,
    RestoreResponse,
)
from app.career.utils.json import object_id_str, to_object_id
from app.database.connection import get_database
from app.share.api.errors import api_error
from app.share.service.llm import generate_json

logger = logging.getLogger(__name__)

PATH_SYSTEM_PROMPT = (
    "You are an expert career advisor. Generate a structured career path roadmap "
    "consisting of sequential milestone nodes (learning, project, and interview nodes)."
)


async def create_path(
    user_id: str,
    request: CreatePathRequest,
    background_tasks: BackgroundTasks,
) -> PathDetail:
    """Generate a career path from a recommendation in a READY analysis.

    Idempotent: If a career path has already been generated from this recommendation,
    returns the existing path detail instead of re-generating.
    """
    try:
        analysis_oid = to_object_id(request.analysis_id)
    except ValueError:
        api_error(
            code="ANALYSIS_NOT_FOUND",
            message="Analysis not found.",
            status_code=404,
        )

    user_oid = to_object_id(user_id)
    db = await get_database()
    analysis = await db.analyses.find_one({"_id": analysis_oid, "user_id": user_oid})
    if not analysis:
        api_error(
            code="ANALYSIS_NOT_FOUND",
            message="Analysis not found.",
            status_code=404,
        )

    if analysis.get("status") != AnalysisStatus.READY.value:
        api_error(
            code="INVALID_REQUEST",
            message="Analysis is not ready yet.",
            status_code=400,
        )

    recommendations = analysis.get("recommendations") or []
    if request.rec_index < 0 or request.rec_index >= len(recommendations):
        api_error(
            code="RECOMMENDATION_NOT_FOUND",
            message="Recommendation not found at specified index.",
            status_code=404,
        )

    rec = recommendations[request.rec_index]

    # Idempotency check: if path already exists for this recommendation, return it
    if rec.get("is_expanded") and rec.get("linked_path_id"):
        existing_path_id = object_id_str(rec["linked_path_id"])
        if existing_path_id:
            try:
                return await get_path(user_id, existing_path_id)
            except Exception:
                pass  # Fallback to re-creation if referenced path was hard-deleted

    prompt_user = (
        f"Target Role: {rec.get('title', '')}\n"
        f"Description: {rec.get('description', '')}\n"
        f"Missing Skills: {', '.join(rec.get('missing_skills') or [])}\n"
        f"Tags: {', '.join(rec.get('tags') or [])}\n"
        "Generate a structured career path matching the 'career path' schema."
    )

    llm_result = await generate_json(
        system=PATH_SYSTEM_PROMPT,
        user=prompt_user,
        response_model=CareerPathLLMOutput,
    )
    output = CareerPathLLMOutput.model_validate(llm_result)

    nodes: list[PathNode] = []
    for index, draft in enumerate(output.nodes):
        nodes.append(
            PathNode(
                step=index,
                title=draft.title,
                description=draft.description,
                type=draft.type,
                difficulty=draft.difficulty,
                tags=draft.tags,
                status=NodeStatus.UNLOCKED if index == 0 else NodeStatus.LOCKED,
                is_expanded=False,
                linked_content_id=None,
                linked_content_collection=None,
                max_score=0,
                attempts=0,
                xp_gained=0,
                completed_at=None,
            )
        )

    now = datetime.now(timezone.utc)
    path_doc = {
        "user_id": user_oid,
        "analysis_id": analysis_oid,
        "recommendation_index": request.rec_index,
        "title": output.title or rec.get("title", "Career Path"),
        "description": output.description or rec.get("description", ""),
        "tags": output.tags or rec.get("tags") or [],
        "missing_skills": output.missing_skills or rec.get("missing_skills") or [],
        "status": PathStatus.ACTIVE.value,
        "deleted_at": None,
        "completed_at": None,
        "total_nodes": len(nodes),
        "created_at": now,
        "nodes": [node.model_dump() for node in nodes],
    }

    insert_res = await db.career_paths.insert_one(path_doc)
    path_id = str(insert_res.inserted_id)
    path_doc["_id"] = insert_res.inserted_id

    # Update recommendation linkage in analysis
    await db.analyses.update_one(
        {"_id": analysis_oid, "user_id": user_oid},
        {
            "$set": {
                f"recommendations.{request.rec_index}.is_expanded": True,
                f"recommendations.{request.rec_index}.linked_path_id": insert_res.inserted_id,
            }
        },
    )

    # Trigger background look-ahead expansion for Node 0
    background_tasks.add_task(expand_node_template, path_id, 0)

    return _to_detail(path_doc)


async def list_paths(
    user_id: str,
    status: Optional[PathStatus] = None,
) -> PathList:
    """Return all paths for the user with calculated progress."""
    user_oid = to_object_id(user_id)
    db = await get_database()

    query: dict = {"user_id": user_oid}
    if status is not None:
        query["status"] = status.value
    else:
        query["status"] = {"$ne": PathStatus.DELETED.value}

    cursor = db.career_paths.find(query).sort("created_at", -1)
    items: list[PathSummary] = []
    async for doc in cursor:
        items.append(_to_summary(doc))
    return PathList(paths=items)


async def get_path(user_id: str, path_id: str) -> PathDetail:
    """Return a single path or raise 404 PATH_NOT_FOUND."""
    try:
        path_oid = to_object_id(path_id)
    except ValueError:
        api_error(
            code="PATH_NOT_FOUND",
            message="Career path not found.",
            status_code=404,
        )

    user_oid = to_object_id(user_id)
    db = await get_database()
    doc = await db.career_paths.find_one({"_id": path_oid, "user_id": user_oid})
    if not doc:
        api_error(
            code="PATH_NOT_FOUND",
            message="Career path not found.",
            status_code=404,
        )
    return _to_detail(doc)


async def archive_path(user_id: str, path_id: str) -> ArchiveResponse:
    """Archive an active career path."""
    try:
        path_oid = to_object_id(path_id)
    except ValueError:
        api_error(
            code="PATH_NOT_FOUND",
            message="Career path not found.",
            status_code=404,
        )

    user_oid = to_object_id(user_id)
    db = await get_database()
    res = await db.career_paths.update_one(
        {
            "_id": path_oid,
            "user_id": user_oid,
            "status": {"$ne": PathStatus.DELETED.value},
        },
        {"$set": {"status": PathStatus.ARCHIVED.value}},
    )
    if res.matched_count == 0:
        api_error(
            code="PATH_NOT_FOUND",
            message="Career path not found.",
            status_code=404,
        )
    return ArchiveResponse(path_id=path_id, status=PathStatus.ARCHIVED)


async def delete_path(user_id: str, path_id: str) -> DeleteResponse:
    """Soft delete a career path."""
    try:
        path_oid = to_object_id(path_id)
    except ValueError:
        api_error(
            code="PATH_NOT_FOUND",
            message="Career path not found.",
            status_code=404,
        )

    user_oid = to_object_id(user_id)
    now = datetime.now(timezone.utc)
    db = await get_database()
    res = await db.career_paths.update_one(
        {
            "_id": path_oid,
            "user_id": user_oid,
            "status": {"$ne": PathStatus.DELETED.value},
        },
        {"$set": {"status": PathStatus.DELETED.value, "deleted_at": now}},
    )
    if res.matched_count == 0:
        api_error(
            code="PATH_NOT_FOUND",
            message="Career path not found.",
            status_code=404,
        )
    return DeleteResponse(path_id=path_id, status=PathStatus.DELETED, deleted_at=now)


async def restore_path(user_id: str, path_id: str) -> RestoreResponse:
    """Restore a soft-deleted career path."""
    try:
        path_oid = to_object_id(path_id)
    except ValueError:
        api_error(
            code="PATH_NOT_FOUND",
            message="Career path not found.",
            status_code=404,
        )

    user_oid = to_object_id(user_id)
    db = await get_database()
    doc = await db.career_paths.find_one({"_id": path_oid, "user_id": user_oid})
    if not doc:
        api_error(
            code="PATH_NOT_FOUND",
            message="Career path not found.",
            status_code=404,
        )

    if doc.get("status") != PathStatus.DELETED.value:
        api_error(
            code="PATH_NOT_DELETED",
            message="Career path is not deleted.",
            status_code=400,
        )

    await db.career_paths.update_one(
        {"_id": path_oid, "user_id": user_oid},
        {"$set": {"status": PathStatus.ACTIVE.value, "deleted_at": None}},
    )
    return RestoreResponse(path_id=path_id, status=PathStatus.ACTIVE, deleted_at=None)


async def expand_node_template(path_id: str, step: int) -> None:
    """Background task hook for generating node template (Feature 3 look-ahead)."""
    logger.info(
        "Look-ahead template expansion triggered for path %s step %s", path_id, step
    )


def _to_detail(doc: dict) -> PathDetail:
    nodes = [_to_node(n) for n in (doc.get("nodes") or [])]
    return PathDetail(
        path_id=str(doc["_id"]),
        title=doc.get("title", ""),
        description=doc.get("description", ""),
        status=PathStatus(doc["status"]),
        tags=doc.get("tags") or [],
        missing_skills=doc.get("missing_skills") or [],
        total_nodes=doc.get("total_nodes", len(nodes)),
        completed_at=doc.get("completed_at"),
        created_at=doc.get("created_at") or datetime.now(timezone.utc),
        deleted_at=doc.get("deleted_at"),
        analysis_id=str(doc.get("analysis_id", "")),
        recommendation_index=doc.get("recommendation_index", 0),
        nodes=nodes,
    )


def _to_summary(doc: dict) -> PathSummary:
    nodes = doc.get("nodes") or []
    total_nodes = doc.get("total_nodes", len(nodes))
    completed_nodes = sum(
        1 for n in nodes if n.get("status") == NodeStatus.COMPLETED.value
    )
    percentage = (
        int((completed_nodes / total_nodes) * 100) if total_nodes > 0 else 0
    )

    return PathSummary(
        path_id=str(doc["_id"]),
        title=doc.get("title", ""),
        status=PathStatus(doc["status"]),
        total_nodes=total_nodes,
        completed_at=doc.get("completed_at"),
        created_at=doc.get("created_at") or datetime.now(timezone.utc),
        deleted_at=doc.get("deleted_at"),
        progress=PathProgress(
            completed_nodes=completed_nodes,
            percentage=percentage,
        ),
    )


def _to_node(node_dict: dict) -> PathNode:
    return PathNode(
        step=node_dict.get("step", 0),
        title=node_dict.get("title", ""),
        description=node_dict.get("description", ""),
        type=NodeType(node_dict["type"]),
        difficulty=NodeDifficulty(node_dict["difficulty"]),
        tags=node_dict.get("tags") or [],
        status=NodeStatus(node_dict["status"]),
        is_expanded=node_dict.get("is_expanded", False),
        linked_content_id=object_id_str(node_dict.get("linked_content_id")),
        linked_content_collection=node_dict.get("linked_content_collection"),
        max_score=node_dict.get("max_score", 0),
        attempts=node_dict.get("attempts", 0),
        xp_gained=node_dict.get("xp_gained", 0),
        completed_at=node_dict.get("completed_at"),
    )
