"""Integration tests for batch job status tracking and delivery package/revoke endpoints."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository
from vtv_schemas.enums import JobStatus
from vtv_schemas.episodes import EpisodeRead
from vtv_schemas.jobs import JobRead


def _setup_with_job() -> tuple[TestClient, MemoryRepository, UUID, UUID]:
    """Create a project with one job and return client, repo, project_id, job_id."""
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    project = client.post(
        "/v1/projects",
        json={
            "name": "BatchTest",
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
    project_id = UUID(project["id"])
    job_id = uuid4()
    repository._jobs[job_id] = JobRead(
        id=job_id,
        project_id=project_id,
        kind="PROJECT_ANALYSIS",
        status=JobStatus.RUNNING,
        progress=0.5,
        total_stages=10,
        completed_stages=5,
    )
    return client, repository, project_id, job_id


# ---------------------------------------------------------------------------
# list_job_summaries
# ---------------------------------------------------------------------------


def test_list_jobs_returns_summaries() -> None:
    client, repository, project_id, job_id = _setup_with_job()
    resp = client.get(f"/v1/projects/{project_id}/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    summary = data[0]
    assert summary["job_id"] == str(job_id)
    assert summary["kind"] == "PROJECT_ANALYSIS"
    assert summary["total_stages"] == 10
    assert summary["completed_stages"] == 5
    assert summary["progress_percent"] == 50.0


def test_list_jobs_unknown_project_404() -> None:
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    resp = client.get(f"/v1/projects/{uuid4()}/jobs")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# get_job_progress
# ---------------------------------------------------------------------------


def test_get_job_progress_counts_correctly() -> None:
    client, repository, project_id, job_id = _setup_with_job()
    resp = client.get(f"/v1/projects/{project_id}/jobs/{job_id}/progress")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == str(job_id)
    assert data["total_stages"] == 10
    assert data["completed_stages"] == 5
    assert data["progress_percent"] == 50.0
    assert data["estimated_seconds_remaining"] is None


def test_get_job_progress_unknown_job_404() -> None:
    client, repository, project_id, job_id = _setup_with_job()
    resp = client.get(f"/v1/projects/{project_id}/jobs/{uuid4()}/progress")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# delivery package / revoke helpers
# ---------------------------------------------------------------------------


def _setup_delivery() -> tuple[TestClient, MemoryRepository, UUID, UUID]:
    """Create a project with a delivery and return client, repo, project_id, delivery_id."""
    from vtv_schemas.episodes import EpisodeRead

    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    project = client.post(
        "/v1/projects",
        json={
            "name": "DeliveryPkg",
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
    project_id = UUID(project["id"])
    episode_id = uuid4()
    ids = {role: uuid4() for role in ("source", "master", "subtitle", "quality", "shots")}
    repository._episodes[project_id] = [
        EpisodeRead(
            id=episode_id,
            project_id=project_id,
            episode_no=1,
            duration_ms=2000,
            source_asset_id=ids["source"],
            processing_status="READY",
        )
    ]

    def _asset(asset_id: UUID, *, uri: str, digest: str, ct: str, meta: dict | None = None) -> dict:
        return {
            "id": asset_id,
            "project_id": project_id,
            "episode_id": episode_id,
            "object_uri": uri,
            "sha256": digest,
            "size_bytes": 100,
            "content_type": ct,
            "metadata": {"episode_id": str(episode_id), **(meta or {})},
        }

    stage_id = uuid4()
    repository._lipsync_assets[ids["source"]] = _asset(
        ids["source"], uri="s3://input/source.mp4", digest="a" * 64, ct="video/mp4"
    )
    edit_chain = [
        {
            "stage_run_id": str(stage_id),
            "stage_type": "ASSEMBLE_EPISODE",
            "input_sha256s": ["a" * 64],
            "output_sha256s": ["b" * 64],
            "parameters_sha256": "f" * 64,
        }
    ]
    cost = {"currency": "USD", "total": "1.000000", "by_stage": {"ASSEMBLE_EPISODE": "1.000000"}}
    final_enc = {
        "video_codec": "h264", "audio_codec": "aac", "width": 1080, "height": 1920, "fps": 24
    }
    repository._lipsync_assets[ids["master"]] = _asset(
        ids["master"],
        uri="s3://deliveries/master.mp4",
        digest="b" * 64,
        ct="video/mp4",
        meta={"edit_chain": edit_chain, "models": [], "cost": cost, "final_encoding": final_enc},
    )
    repository._lipsync_assets[ids["subtitle"]] = _asset(
        ids["subtitle"], uri="s3://deliveries/sub.srt", digest="c" * 64, ct="application/x-subrip"
    )
    evidence = repository._lipsync_assets[ids["master"]]["metadata"]
    repository._lipsync_assets[ids["quality"]] = _asset(
        ids["quality"],
        uri="s3://deliveries/quality.json",
        digest="d" * 64,
        ct="application/json",
        meta={
            **evidence,
            "qc": [
                {
                    "metric_name": "master_duration",
                    "metric_version": "v1",
                    "evaluator_release": "ffmpeg-7",
                    "score": 1,
                    "verdict": "PASS",
                }
            ],
        },
    )
    repository._lipsync_assets[ids["shots"]] = _asset(
        ids["shots"],
        uri="s3://deliveries/shots.json",
        digest="e" * 64,
        ct="application/json",
        meta={
            "shots": [
                {
                    "shot_id": str(uuid4()),
                    "shot_no": 1,
                    "start_ms": 0,
                    "end_ms": 2000,
                    "route": "L0",
                    "qc_verdict": "SOURCE_UNCHANGED",
                }
            ]
        },
    )
    # Create draft delivery
    create_payload = {
        "episode_id": str(episode_id),
        "master_asset_id": str(ids["master"]),
        "subtitle_asset_ids": [str(ids["subtitle"])],
        "quality_report_asset_id": str(ids["quality"]),
        "shot_list_asset_id": str(ids["shots"]),
        "expected_project_state_version": 1,
    }
    draft = client.post(f"/v1/projects/{project_id}/deliveries", json=create_payload).json()
    delivery_id = UUID(draft["id"])
    # Approve the delivery
    client.post(
        f"/v1/deliveries/{delivery_id}/approve",
        json={"expected_state_version": 1, "actor_id": "producer@example.com"},
    )
    return client, repository, project_id, delivery_id


# ---------------------------------------------------------------------------
# get_delivery_package
# ---------------------------------------------------------------------------


def test_get_delivery_package_rejects_draft() -> None:
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    project = client.post(
        "/v1/projects",
        json={
            "name": "DraftTest",
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
    project_id = UUID(project["id"])
    episode_id = uuid4()
    ids = {role: uuid4() for role in ("source", "master", "subtitle", "quality", "shots")}
    repository._episodes[project_id] = [
        EpisodeRead(
            id=episode_id,
            project_id=project_id,
            episode_no=1,
            duration_ms=2000,
            source_asset_id=ids["source"],
            processing_status="READY",
        )
    ]
    stage_id = uuid4()
    edit_chain = [
        {
            "stage_run_id": str(stage_id),
            "stage_type": "ASSEMBLE_EPISODE",
            "input_sha256s": ["a" * 64],
            "output_sha256s": ["b" * 64],
            "parameters_sha256": "f" * 64,
        }
    ]
    cost = {"currency": "USD", "total": "1.000000", "by_stage": {}}
    final_enc = {
        "video_codec": "h264", "audio_codec": "aac", "width": 1080, "height": 1920, "fps": 24
    }
    for aid, uri, digest, ct, meta in [
        (ids["source"], "s3://input/src.mp4", "a" * 64, "video/mp4", None),
        (
            ids["master"],
            "s3://del/m.mp4",
            "b" * 64,
            "video/mp4",
            {"edit_chain": edit_chain, "models": [], "cost": cost, "final_encoding": final_enc},
        ),
        (ids["subtitle"], "s3://del/s.srt", "c" * 64, "application/x-subrip", None),
        (
            ids["quality"],
            "s3://del/q.json",
            "d" * 64,
            "application/json",
            {
                "edit_chain": edit_chain,
                "models": [],
                "cost": cost,
                "final_encoding": final_enc,
                "qc": [
                    {
                        "metric_name": "m",
                        "metric_version": "v1",
                        "evaluator_release": "e-1",
                        "score": 1,
                        "verdict": "PASS",
                    }
                ],
            },
        ),
        (
            ids["shots"],
            "s3://del/sh.json",
            "e" * 64,
            "application/json",
            {
                "shots": [
                    {
                        "shot_id": str(uuid4()),
                        "shot_no": 1,
                        "start_ms": 0,
                        "end_ms": 2000,
                        "route": "L0",
                        "qc_verdict": "SOURCE_UNCHANGED",
                    }
                ]
            },
        ),
    ]:
        repository._lipsync_assets[aid] = {
            "id": aid,
            "project_id": project_id,
            "episode_id": episode_id,
            "object_uri": uri,
            "sha256": digest,
            "size_bytes": 100,
            "content_type": ct,
            "metadata": {"episode_id": str(episode_id), **(meta or {})},
        }
    draft = client.post(
        f"/v1/projects/{project_id}/deliveries",
        json={
            "episode_id": str(episode_id),
            "master_asset_id": str(ids["master"]),
            "subtitle_asset_ids": [str(ids["subtitle"])],
            "quality_report_asset_id": str(ids["quality"]),
            "shot_list_asset_id": str(ids["shots"]),
            "expected_project_state_version": 1,
        },
    ).json()
    delivery_id = draft["id"]
    # DRAFT — package must be rejected
    resp = client.get(f"/v1/deliveries/{delivery_id}/package")
    assert resp.status_code == 409
    assert "APPROVED" in resp.json()["detail"]


def test_get_delivery_package_returns_assets_for_approved() -> None:
    client, repository, project_id, delivery_id = _setup_delivery()
    resp = client.get(f"/v1/deliveries/{delivery_id}/package")
    assert resp.status_code == 200
    pkg = resp.json()
    assert pkg["delivery_id"] == str(delivery_id)
    assert len(pkg["assets"]) > 0
    # Each asset has a download_url (passthrough = object_uri)
    for asset in pkg["assets"]:
        assert asset["download_url"] == asset["object_uri"]


# ---------------------------------------------------------------------------
# revoke_delivery
# ---------------------------------------------------------------------------


def test_revoke_delivery_changes_status() -> None:
    client, repository, project_id, delivery_id = _setup_delivery()
    resp = client.post(
        f"/v1/deliveries/{delivery_id}:revoke",
        json={"reason": "License expired", "actor_id": "admin@example.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "REVOKED"
    assert data["state_version"] == 3  # draft=1, approved=2, revoked=3
