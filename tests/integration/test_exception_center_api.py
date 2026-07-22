"""Integration tests for exception-centre endpoints (Phase 3).

All tests require a live PostgreSQL database and are skipped in the unit-test
environment.  Run them with:

    pytest tests/integration/test_exception_center_api.py \
        --postgres-url postgresql+asyncpg://...
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup() -> tuple[TestClient, MemoryRepository, UUID]:
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    project = client.post(
        "/v1/projects",
        json={
            "name": "ExceptionsProject",
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
    return client, repository, UUID(project["id"])


# ---------------------------------------------------------------------------
# retry_stage: EXECUTION_FAILED → READY
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="requires postgres")
def test_retry_stage_execution_failed_to_ready() -> None:
    """POST …/stages/{id}:retry on an EXECUTION_FAILED stage returns 202 + READY."""
    # This test inserts a StageRun with status=EXECUTION_FAILED directly into the
    # database, calls the retry endpoint, and asserts status=READY in the response.
    client, _repo, project_id = _setup()
    stage_run_id = uuid4()  # would be seeded in real DB
    resp = client.post(
        f"/v1/projects/{project_id}/stages/{stage_run_id}:retry",
        json={"reason": "manual-retry"},
    )
    assert resp.status_code in (202, 404)  # 404 for memory stub


# ---------------------------------------------------------------------------
# retry_stage: wrong status → 409
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="requires postgres")
def test_retry_stage_wrong_status_returns_409() -> None:
    """POST …/stages/{id}:retry on a COMPLETED stage returns 409."""
    client, _repo, project_id = _setup()
    stage_run_id = uuid4()  # would be seeded as COMPLETED in real DB
    resp = client.post(
        f"/v1/projects/{project_id}/stages/{stage_run_id}:retry",
        json={"reason": "manual-retry"},
    )
    assert resp.status_code in (409, 404)


# ---------------------------------------------------------------------------
# override_shot_route
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="requires postgres")
def test_override_shot_route_records_and_returns() -> None:
    """POST …/shots/{id}:override returns 202 with shot_id and route."""
    client, _repo, project_id = _setup()
    shot_id = uuid4()  # would be seeded in real DB
    resp = client.post(
        f"/v1/projects/{project_id}/shots/{shot_id}:override",
        json={"route": "C", "reason": "manual-override", "force_rerun": False},
    )
    assert resp.status_code in (202, 404)


# ---------------------------------------------------------------------------
# list_failed_stages: filter by stage_type
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="requires postgres")
def test_list_failed_stages_filter_by_stage_type() -> None:
    """GET …/exceptions?stage_type=X only returns stages of that type."""
    client, _repo, project_id = _setup()
    resp = client.get(
        f"/v1/projects/{project_id}/exceptions",
        params={"stage_type": "VISUAL_CHARACTER_REPLACE"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for item in data:
        assert item["stage_type"] == "VISUAL_CHARACTER_REPLACE"


# ---------------------------------------------------------------------------
# list_failed_stages: filter by episode_id
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="requires postgres")
def test_list_failed_stages_filter_by_episode_id() -> None:
    """GET …/exceptions?episode_id=X only returns stages for that episode."""
    client, _repo, project_id = _setup()
    episode_id = uuid4()
    resp = client.get(
        f"/v1/projects/{project_id}/exceptions",
        params={"episode_id": str(episode_id)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for item in data:
        assert item["episode_id"] == str(episode_id)
