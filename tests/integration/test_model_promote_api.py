from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository


def _setup() -> tuple[TestClient, MemoryRepository, dict]:
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    project = client.post(
        "/v1/projects",
        json={
            "name": "Rollback Test",
            "target_market": "US",
            "locale": "en-US",
            "output": {
                "aspect_ratio": "9:16",
                "width": 1080,
                "height": 1920,
                "fps": 24,
                "video_codec": "h264",
                "audio_codec": "aac",
                "subtitle_formats": ["srt"],
            },
        },
    ).json()
    return client, repository, project


def test_rollback_production_stub() -> None:
    client, _repo, project = _setup()
    project_id = project["id"]
    episode_id = str(uuid4())
    resp = client.post(
        f"/v1/projects/{project_id}/episodes/{episode_id}:rollback-production",
        json={"reason": "rerun needed", "actor_id": "op-001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["stages_reset"] == 0
    assert data["candidates_rejected"] == 0
    assert data["reason"] == "rerun needed"
    assert data["actor_id"] == "op-001"


def test_rollback_production_missing_project() -> None:
    client, _repo, _project = _setup()
    resp = client.post(
        f"/v1/projects/{uuid4()}/episodes/{uuid4()}:rollback-production",
        json={"reason": "rerun needed", "actor_id": "op-001"},
    )
    assert resp.status_code == 404


def test_promote_to_active_not_found() -> None:
    client, _repo, _project = _setup()
    resp = client.post(
        f"/v1/model-releases/{uuid4()}:promote-to-active",
        json={"expected_state_version": 1, "actor_id": "reviewer"},
    )
    assert resp.status_code == 404


def test_promote_to_active_body_validation() -> None:
    client, _repo, _project = _setup()
    resp = client.post(
        f"/v1/model-releases/{uuid4()}:promote-to-active",
        json={"expected_state_version": 0, "actor_id": "reviewer"},
    )
    assert resp.status_code == 422


def test_rollback_production_validation() -> None:
    client, _repo, project = _setup()
    project_id = project["id"]
    episode_id = str(uuid4())
    resp = client.post(
        f"/v1/projects/{project_id}/episodes/{episode_id}:rollback-production",
        json={"reason": "", "actor_id": "op-001"},
    )
    assert resp.status_code == 422
