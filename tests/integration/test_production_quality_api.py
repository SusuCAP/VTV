from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository
from vtv_schemas.candidates import CandidateGroupRead, CandidateVariantRead
from vtv_schemas.episodes import EpisodeRead

DATABASE_URL = os.getenv("VTV_TEST_DATABASE_URL")


def _make_project(client: TestClient) -> dict:
    return client.post(
        "/v1/projects",
        json={
            "name": "QualityTest",
            "target_market": "US",
            "locale": "en-US",
            "output": {
                "aspect_ratio": "16:9",
                "width": 1920,
                "height": 1080,
                "fps": 24,
                "video_codec": "h264",
                "audio_codec": "aac",
                "subtitle_formats": ["srt"],
            },
        },
    ).json()


def _setup() -> tuple[TestClient, MemoryRepository]:
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    return client, repository


# ── 1. Stats endpoint returns 200 with episode count ──────────────────────────


def test_stats_endpoint_returns_200_with_episode_count() -> None:
    client, repository = _setup()
    project = _make_project(client)
    project_id = UUID(project["id"])
    repository._episodes[project_id] = [
        EpisodeRead(
            id=uuid4(),
            project_id=project_id,
            episode_no=1,
            processing_status="READY",
        )
    ]
    resp = client.get(f"/v1/projects/{project_id}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert "project_id" in body
    assert body["project_id"] == str(project_id)


# ── 2. Quality-snapshot endpoint returns 200 with zeros ──────────────────────


def test_quality_snapshot_returns_200_with_zeros() -> None:
    client, _ = _setup()
    project = _make_project(client)
    project_id = UUID(project["id"])
    resp = client.get(f"/v1/projects/{project_id}/quality-snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == str(project_id)
    assert body["total_candidates_generated"] == 0
    assert body["qc_passed"] == 0
    assert body["qc_failed"] == 0
    assert body["adopted_count"] == 0
    assert body["pass_rate"] == 0.0
    assert body["circuit_breaker_active"] is False
    assert body["top_failure_reasons"] == []


# ── 3. adopt_candidate with unknown variant returns 404 ──────────────────────


def test_adopt_candidate_unknown_variant_returns_404() -> None:
    client, _ = _setup()
    project = _make_project(client)
    project_id = UUID(project["id"])
    unknown_variant_id = uuid4()
    resp = client.post(
        f"/v1/projects/{project_id}/candidates/{unknown_variant_id}:adopt",
        json={"actor_id": "user-abc"},
    )
    assert resp.status_code == 404


# ── 4. Project stats include correct zero values ─────────────────────────────


def test_project_stats_zero_values() -> None:
    client, _ = _setup()
    project = _make_project(client)
    project_id = UUID(project["id"])
    resp = client.get(f"/v1/projects/{project_id}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["episodes"] == 0
    assert body["total_deliveries"] == 0
    assert body["total_shots"] == 0


# ── 5. list_episode_jobs returns 200 with empty list ─────────────────────────


def test_list_episode_jobs_returns_200_empty() -> None:
    client, repository = _setup()
    project = _make_project(client)
    project_id = UUID(project["id"])
    episode_id = uuid4()
    repository._episodes[project_id] = [
        EpisodeRead(
            id=episode_id,
            project_id=project_id,
            episode_no=1,
            processing_status="READY",
        )
    ]
    resp = client.get(f"/v1/projects/{project_id}/episodes/{episode_id}/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["episode_id"] == str(episode_id)
    assert body["jobs"] == []


# ── 6. quality-snapshot with unknown project returns 404 ─────────────────────


def test_quality_snapshot_unknown_project_returns_404() -> None:
    client, _ = _setup()
    unknown_id = uuid4()
    resp = client.get(f"/v1/projects/{unknown_id}/quality-snapshot")
    assert resp.status_code == 404


# ── 7. adopt_candidate success path ──────────────────────────────────────────


def test_adopt_candidate_manual_success() -> None:
    client, repository = _setup()
    project = _make_project(client)
    project_id = UUID(project["id"])
    now = datetime.now(UTC)
    group_id = uuid4()
    variant_id = uuid4()
    variant = CandidateVariantRead(
        id=variant_id,
        candidate_group_id=group_id,
        stage_run_id=uuid4(),
        variant_no=1,
        status="QC_PASSED",
        output_asset_id=uuid4(),
        raw_metrics={},
        allocated_cost={},
        created_at=now,
        updated_at=now,
    )
    repository._candidate_groups[group_id] = CandidateGroupRead(
        id=group_id,
        project_id=project_id,
        purpose="TTS",
        status="OPEN",
        state_version=1,
        variants=(variant,),
        created_at=now,
        updated_at=now,
    )
    resp = client.post(
        f"/v1/projects/{project_id}/candidates/{variant_id}:adopt",
        json={"actor_id": "editor-1", "reason": "preferred take"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["variant_id"] == str(variant_id)
    assert body["new_status"] == "ADOPTED"
    assert body["actor_id"] == "editor-1"


# ── 8. adopt_candidate QC_FAILED without override returns 409 ────────────────


def test_adopt_candidate_qc_failed_without_override_returns_409() -> None:
    client, repository = _setup()
    project = _make_project(client)
    project_id = UUID(project["id"])
    now = datetime.now(UTC)
    group_id = uuid4()
    variant_id = uuid4()
    variant = CandidateVariantRead(
        id=variant_id,
        candidate_group_id=group_id,
        stage_run_id=uuid4(),
        variant_no=1,
        status="QC_FAILED",
        output_asset_id=uuid4(),
        raw_metrics={},
        allocated_cost={},
        created_at=now,
        updated_at=now,
    )
    repository._candidate_groups[group_id] = CandidateGroupRead(
        id=group_id,
        project_id=project_id,
        purpose="TTS",
        status="OPEN",
        state_version=1,
        variants=(variant,),
        created_at=now,
        updated_at=now,
    )
    resp = client.post(
        f"/v1/projects/{project_id}/candidates/{variant_id}:adopt",
        json={"actor_id": "editor-1", "override_qc_failure": False},
    )
    assert resp.status_code == 409
