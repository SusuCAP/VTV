from __future__ import annotations

import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository

DATABASE_URL = os.getenv("VTV_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="VTV_TEST_DATABASE_URL is not set")


@pytest.fixture
def app():
    repo = MemoryRepository()
    return create_app(repository=repo)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


async def test_create_evaluator_release(client: AsyncClient) -> None:
    payload = {
        "evaluator_key": "lipsync_qc",
        "release_name": "vtv.lipsync-qc.v1",
        "metric_definitions": [
            {
                "metric_name": "mouth_sync_score",
                "metric_version": "v1",
                "hard_failure_below": 0.2,
            },
            {
                "metric_name": "temporal_alignment",
                "metric_version": "v1",
                "hard_failure_below": 0.3,
            },
        ],
        "thresholds": {"mouth_sync_score": 0.6, "temporal_alignment": 0.65},
    }
    resp = await client.post("/v1/evaluator-releases", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["evaluator_key"] == "lipsync_qc"
    assert data["version"] == 1
    assert data["status"] == "ACTIVE"


async def test_list_evaluator_releases(client: AsyncClient) -> None:
    payload = {
        "evaluator_key": "visual_technical",
        "release_name": "vtv.visual-technical.v1",
        "metric_definitions": [
            {"metric_name": "frame_integrity", "metric_version": "v1"},
        ],
        "thresholds": {},
    }
    await client.post("/v1/evaluator-releases", json=payload)
    resp = await client.get("/v1/evaluator-releases?evaluator_key=visual_technical")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["evaluator_key"] == "visual_technical"


async def test_get_evaluator_release(client: AsyncClient) -> None:
    payload = {
        "evaluator_key": "audio_continuity",
        "release_name": "vtv.audio-continuity.v1",
        "metric_definitions": [
            {"metric_name": "loudness_consistency", "metric_version": "v1"},
        ],
        "thresholds": {},
    }
    create_resp = await client.post("/v1/evaluator-releases", json=payload)
    release_id = create_resp.json()["id"]
    resp = await client.get(f"/v1/evaluator-releases/{release_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == release_id


async def test_deprecate_evaluator_release(client: AsyncClient) -> None:
    payload = {
        "evaluator_key": "visual_identity",
        "release_name": "vtv.visual-identity.v1",
        "metric_definitions": [
            {"metric_name": "character_identity_score", "metric_version": "v1"},
        ],
        "thresholds": {},
    }
    create_resp = await client.post("/v1/evaluator-releases", json=payload)
    release_id = create_resp.json()["id"]
    resp = await client.post(f"/v1/evaluator-releases/{release_id}:deprecate")
    assert resp.status_code == 200
    assert resp.json()["status"] == "DEPRECATED"


async def test_submit_qc_evidence_stub(client: AsyncClient) -> None:
    """MemoryRepository stub: submit_qc_evidence requires a real project."""

    project_payload = {
        "name": "QC Test Project",
        "target_market": "US",
        "locale": "en-US",
        "timezone": "UTC",
        "quality_profile": "standard",
        "budget": {"currency": "USD", "warning_at": "800.00", "hard_limit": "1000.00"},
        "output": {
            "width": 1920, "height": 1080, "fps": 25,
            "video_codec": "h264", "audio_codec": "aac",
        },
    }
    project_resp = await client.post("/v1/projects", json=project_payload)
    assert project_resp.status_code == 201
    project_id = project_resp.json()["id"]
    variant_id = str(uuid4())
    qc_payload = {
        "render_variant_id": variant_id,
        "evaluator_release_id": str(uuid4()),
        "results": [],
    }
    resp = await client.post(
        f"/v1/projects/{project_id}/candidates/{variant_id}:submit-qc",
        json=qc_payload,
    )
    # MemoryRepository stub returns 204 (no error since project exists)
    assert resp.status_code == 204


async def test_submit_qc_evidence_project_not_found(client: AsyncClient) -> None:
    project_id = str(uuid4())
    variant_id = str(uuid4())
    qc_payload = {
        "render_variant_id": variant_id,
        "evaluator_release_id": str(uuid4()),
        "results": [],
    }
    resp = await client.post(
        f"/v1/projects/{project_id}/candidates/{variant_id}:submit-qc",
        json=qc_payload,
    )
    assert resp.status_code == 404
