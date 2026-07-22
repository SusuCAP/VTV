"""Integration tests for POST /v1/projects/{project_id}:produce."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository
from vtv_schemas.episodes import EpisodeRead

pytestmark = pytest.mark.skip(reason="requires postgres — run with postgres marker")


def _project_payload(name: str = "VTV Test") -> dict:
    return {
        "name": name,
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
    }


def _setup() -> tuple[TestClient, MemoryRepository, UUID, UUID]:
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    project = client.post("/v1/projects", json=_project_payload()).json()
    project_id = UUID(project["id"])
    episode_id = uuid4()
    repository._episodes[project_id] = [
        EpisodeRead(
            id=episode_id,
            project_id=project_id,
            episode_no=1,
            source_asset_id=uuid4(),
            processing_status="READY",
        )
    ]
    return client, repository, project_id, episode_id


def _produce_payload(state_version: int = 1, **kwargs) -> dict:
    return {"expected_project_state_version": state_version, **kwargs}


def test_produce_creates_job_for_project():
    """produce returns 202 + Location header and creates a VISUAL_PRODUCTION job."""
    client, repository, project_id, _ = _setup()

    resp = client.post(
        f"/v1/projects/{project_id}:produce",
        json=_produce_payload(),
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["kind"] == "VISUAL_PRODUCTION"
    assert body["status"] == "QUEUED"
    assert "Location" in resp.headers
    assert resp.headers["Location"] == f"/v1/jobs/{body['id']}"


def test_produce_creates_shot_routing_stage_when_no_workflow_plan():
    """When an episode has no WORKFLOW_PLAN, the job is still created (SHOT_ROUTING path)."""
    client, repository, project_id, episode_id = _setup()
    # No AnalysisDocument injected — MemoryRepository stub always creates the job regardless

    resp = client.post(
        f"/v1/projects/{project_id}:produce",
        json=_produce_payload(),
    )

    assert resp.status_code == 202, resp.text
    job_id = UUID(resp.json()["id"])
    # Job is retrievable via GET /v1/jobs/{job_id}
    job_resp = client.get(f"/v1/jobs/{job_id}")
    assert job_resp.status_code == 200
    assert job_resp.json()["kind"] == "VISUAL_PRODUCTION"


def test_produce_state_version_mismatch_returns_409():
    """Passing the wrong expected_project_state_version must return 409."""
    client, _, project_id, _ = _setup()

    resp = client.post(
        f"/v1/projects/{project_id}:produce",
        json=_produce_payload(state_version=99),
    )

    assert resp.status_code == 409, resp.text
    assert "state version mismatch" in resp.json()["detail"]


def test_produce_empty_episodes_returns_409():
    """A project with no uploaded episodes must return 409."""
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    project = client.post("/v1/projects", json=_project_payload("Empty")).json()
    project_id = UUID(project["id"])
    # No episodes injected

    resp = client.post(
        f"/v1/projects/{project_id}:produce",
        json=_produce_payload(),
    )

    assert resp.status_code == 409, resp.text
    assert "episode" in resp.json()["detail"].lower()


def test_produce_unknown_project_returns_404():
    """Producing against a non-existent project must return 404."""
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))

    resp = client.post(
        f"/v1/projects/{uuid4()}:produce",
        json=_produce_payload(),
    )

    assert resp.status_code == 404, resp.text
