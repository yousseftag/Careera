from datetime import datetime, timezone

from app.career.model.path import (
    ArchiveResponse,
    CareerPathLLMOutput,
    CreatePathRequest,
    DeleteResponse,
    NodeDifficulty,
    NodeDraft,
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


def test_career_path_llm_output_validation():
    output = CareerPathLLMOutput(
        title="Backend Engineer Path",
        description="Roadmap for backend engineers",
        tags=["Backend", "Python"],
        missing_skills=["Docker", "Kubernetes"],
        nodes=[
            NodeDraft(
                title="Python Basics",
                description="Learn Python syntax",
                type=NodeType.LEARNING,
                difficulty=NodeDifficulty.EASY,
                tags=["Python"],
            )
        ],
    )
    assert output.title == "Backend Engineer Path"
    assert len(output.nodes) == 1
    assert output.nodes[0].type == NodeType.LEARNING


def test_create_path_request_validation():
    req = CreatePathRequest(analysis_id="60f1b2c3d4e5f6a7b8c9d0e1", rec_index=0)
    assert req.analysis_id == "60f1b2c3d4e5f6a7b8c9d0e1"
    assert req.rec_index == 0


def test_path_node_defaults():
    node = PathNode(
        step=0,
        title="Intro",
        description="Description",
        type=NodeType.LEARNING,
        difficulty=NodeDifficulty.EASY,
        status=NodeStatus.UNLOCKED,
    )
    assert node.step == 0
    assert node.is_expanded is False
    assert node.linked_content_id is None
    assert node.max_score == 0
    assert node.attempts == 0
    assert node.xp_gained == 0


def test_path_summary_and_list_serialization():
    summary = PathSummary(
        path_id="60f1b2c3d4e5f6a7b8c9d0e1",
        title="Backend Engineer Path",
        status=PathStatus.ACTIVE,
        total_nodes=4,
        created_at=datetime.now(timezone.utc),
        progress=PathProgress(completed_nodes=1, percentage=25),
    )
    path_list = PathList(paths=[summary])
    assert len(path_list.paths) == 1
    assert path_list.paths[0].progress.percentage == 25


def test_action_responses():
    now = datetime.now(timezone.utc)
    arch = ArchiveResponse(path_id="123")
    assert arch.status == PathStatus.ARCHIVED

    dele = DeleteResponse(path_id="123", deleted_at=now)
    assert dele.status == PathStatus.DELETED
    assert dele.deleted_at == now

    rest = RestoreResponse(path_id="123")
    assert rest.status == PathStatus.ACTIVE
    assert rest.deleted_at is None
