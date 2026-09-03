from datetime import datetime, timezone

from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.utils.auth import get_current_user
from app.career.api.path import router
from app.share.api.errors import register_error_handler

USER_ID = str(ObjectId())
CAREERS_PREFIX = "/api/v1/careers"

READY_ANALYSIS = {
    "_id": ObjectId(),
    "user_id": ObjectId(USER_ID),
    "created_at": datetime.now(timezone.utc),
    "status": "READY",
    "recommendations": [
        {
            "rec_index": 0,
            "title": "Backend Engineer",
            "description": "Design REST APIs",
            "match_score": 90,
            "reasoning": "Python knowledge",
            "missing_skills": ["Docker"],
            "tags": ["Backend"],
            "is_expanded": False,
            "linked_path_id": None,
        }
    ],
}

LLM_PATH_RESULT = {
    "title": "Backend Engineer Career Path",
    "description": "Roadmap to backend engineering.",
    "tags": ["Backend"],
    "missing_skills": ["Docker"],
    "nodes": [
        {
            "title": "Python & API Fundamentals",
            "description": "Learn Python & APIs.",
            "type": "LEARNING",
            "difficulty": "EASY",
            "tags": ["Python"],
        }
    ],
}


def _make_app() -> FastAPI:
    app = FastAPI()
    register_error_handler(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": USER_ID}
    return app


def _client(fake_db) -> TestClient:
    return TestClient(_make_app())


def test_create_path_api_success(fake_db, monkeypatch):
    async def _fake_generate_json(**kwargs):
        return LLM_PATH_RESULT

    monkeypatch.setattr("app.career.service.path.generate_json", _fake_generate_json)

    fake_db.analyses.docs.append(dict(READY_ANALYSIS))

    client = _client(fake_db)
    payload = {
        "analysis_id": str(READY_ANALYSIS["_id"]),
        "rec_index": 0,
    }
    resp = client.post(f"{CAREERS_PREFIX}/paths", json=payload)

    assert resp.status_code == 201
    body = resp.json()
    assert body["path_id"]
    assert body["title"] == "Backend Engineer Career Path"
    assert body["status"] == "ACTIVE"
    assert len(body["nodes"]) == 1


def test_list_paths_api(fake_db):
    fake_db.career_paths.docs.append(
        {
            "_id": ObjectId(),
            "user_id": ObjectId(USER_ID),
            "title": "Backend Path",
            "status": "ACTIVE",
            "created_at": datetime.now(timezone.utc),
            "total_nodes": 2,
            "nodes": [
                {"step": 0, "type": "LEARNING", "difficulty": "EASY", "status": "COMPLETED"},
                {"step": 1, "type": "PROJECT", "difficulty": "MEDIUM", "status": "UNLOCKED"},
            ],
        }
    )

    client = _client(fake_db)
    resp = client.get(f"{CAREERS_PREFIX}/paths")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["paths"]) == 1
    assert body["paths"][0]["progress"]["percentage"] == 50


def test_get_path_detail_api(fake_db):
    path_id = ObjectId()
    fake_db.career_paths.docs.append(
        {
            "_id": path_id,
            "user_id": ObjectId(USER_ID),
            "analysis_id": READY_ANALYSIS["_id"],
            "recommendation_index": 0,
            "title": "Backend Path",
            "description": "Roadmap",
            "status": "ACTIVE",
            "created_at": datetime.now(timezone.utc),
            "total_nodes": 1,
            "nodes": [
                {
                    "step": 0,
                    "title": "Python",
                    "description": "Learn Python",
                    "type": "LEARNING",
                    "difficulty": "EASY",
                    "tags": ["Python"],
                    "status": "UNLOCKED",
                }
            ],
        }
    )

    client = _client(fake_db)
    resp = client.get(f"{CAREERS_PREFIX}/paths/{path_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["path_id"] == str(path_id)
    assert body["nodes"][0]["title"] == "Python"


def test_archive_delete_restore_api(fake_db):
    path_id = ObjectId()
    fake_db.career_paths.docs.append(
        {
            "_id": path_id,
            "user_id": ObjectId(USER_ID),
            "title": "Path Lifecycle",
            "status": "ACTIVE",
            "created_at": datetime.now(timezone.utc),
            "total_nodes": 0,
            "nodes": [],
        }
    )

    client = _client(fake_db)

    # Archive
    arch_resp = client.patch(f"{CAREERS_PREFIX}/paths/{path_id}/archive")
    assert arch_resp.status_code == 200
    assert arch_resp.json()["status"] == "ARCHIVED"

    # Soft Delete
    del_resp = client.delete(f"{CAREERS_PREFIX}/paths/{path_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "DELETED"

    # Restore
    rest_resp = client.patch(f"{CAREERS_PREFIX}/paths/{path_id}/restore")
    assert rest_resp.status_code == 200
    assert rest_resp.json()["status"] == "ACTIVE"
