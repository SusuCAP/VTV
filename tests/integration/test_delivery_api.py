from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository
from vtv_schemas.episodes import EpisodeRead


def _asset(
    asset_id: UUID,
    project_id: UUID,
    episode_id: UUID,
    *,
    uri: str,
    digest: str,
    content_type: str,
    metadata: dict | None = None,
) -> dict:
    return {
        "id": asset_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "object_uri": uri,
        "sha256": digest,
        "size_bytes": 100,
        "content_type": content_type,
        "metadata": {"episode_id": str(episode_id), **(metadata or {})},
    }


def _setup() -> tuple[TestClient, MemoryRepository, UUID, UUID, dict[str, UUID]]:
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    project = client.post(
        "/v1/projects",
        json={
            "name": "Delivery",
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
    repository._lipsync_assets[ids["source"]] = _asset(
        ids["source"],
        project_id,
        episode_id,
        uri="s3://input/source.mp4",
        digest="a" * 64,
        content_type="video/mp4",
    )
    stage_id = uuid4()
    repository._lipsync_assets[ids["master"]] = _asset(
        ids["master"],
        project_id,
        episode_id,
        uri="s3://deliveries/master.mp4",
        digest="b" * 64,
        content_type="video/mp4",
        metadata={
            "edit_chain": [
                {
                    "stage_run_id": str(stage_id),
                    "stage_type": "ASSEMBLE_EPISODE",
                    "input_sha256s": ["a" * 64],
                    "output_sha256s": ["b" * 64],
                    "parameters_sha256": "f" * 64,
                }
            ],
            "models": [],
            "cost": {
                "currency": "USD",
                "total": "1.250000",
                "by_stage": {"ASSEMBLE_EPISODE": "1.250000"},
            },
            "final_encoding": {
                "video_codec": "h264",
                "audio_codec": "aac",
                "width": 1080,
                "height": 1920,
                "fps": 24,
            },
        },
    )
    delivery_evidence = repository._lipsync_assets[ids["master"]]["metadata"]
    repository._lipsync_assets[ids["subtitle"]] = _asset(
        ids["subtitle"],
        project_id,
        episode_id,
        uri="s3://deliveries/en-US.srt",
        digest="c" * 64,
        content_type="application/x-subrip",
    )
    repository._lipsync_assets[ids["quality"]] = _asset(
        ids["quality"],
        project_id,
        episode_id,
        uri="s3://deliveries/quality.json",
        digest="d" * 64,
        content_type="application/json",
        metadata={
            **delivery_evidence,
            "qc": [
                {
                    "metric_name": "master_duration",
                    "metric_version": "v1",
                    "evaluator_release": "ffmpeg-7",
                    "score": 1,
                    "verdict": "PASS",
                }
            ]
        },
    )
    repository._lipsync_assets[ids["shots"]] = _asset(
        ids["shots"],
        project_id,
        episode_id,
        uri="s3://deliveries/shots.json",
        digest="e" * 64,
        content_type="application/json",
        metadata={
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
    return client, repository, project_id, episode_id, ids


def _create_payload(episode_id: UUID, ids: dict[str, UUID]) -> dict:
    return {
        "episode_id": str(episode_id),
        "master_asset_id": str(ids["master"]),
        "subtitle_asset_ids": [str(ids["subtitle"])],
        "quality_report_asset_id": str(ids["quality"]),
        "shot_list_asset_id": str(ids["shots"]),
        "expected_project_state_version": 1,
        "c2pa_requested": True,
    }


def test_delivery_draft_approval_and_manifest_query() -> None:
    client, _repository, project_id, episode_id, ids = _setup()
    response = client.post(
        f"/v1/projects/{project_id}/deliveries",
        json=_create_payload(episode_id, ids),
    )
    assert response.status_code == 201
    draft = response.json()
    assert draft["status"] == "DRAFT"
    assert draft["manifest"] is None
    assert response.headers["location"] == f"/v1/deliveries/{draft['id']}"

    approved_response = client.post(
        f"/v1/deliveries/{draft['id']}/approve",
        json={"expected_state_version": 1, "actor_id": "producer@example.com"},
    )
    assert approved_response.status_code == 200
    approved = approved_response.json()
    assert approved["status"] == "APPROVED"
    assert approved["state_version"] == 2
    assert len(approved["manifest_fingerprint"]) == 64
    assert approved["manifest"]["c2pa_status"] == "PENDING"
    assert {asset["role"] for asset in approved["manifest"]["assets"]} >= {
        "SOURCE_VIDEO",
        "MASTER_VIDEO",
        "SUBTITLE_SRT",
        "QUALITY_REPORT",
        "SHOT_LIST",
    }
    fetched = client.get(f"/v1/deliveries/{draft['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == approved

    listed = client.get(
        f"/v1/projects/{project_id}/deliveries",
        params={"episode_id": str(episode_id)},
    )
    assert listed.status_code == 200
    assert listed.json() == [approved]


def test_delivery_rejects_stale_project_and_duplicate_approval() -> None:
    client, repository, project_id, episode_id, ids = _setup()
    draft = client.post(
        f"/v1/projects/{project_id}/deliveries",
        json=_create_payload(episode_id, ids),
    ).json()
    project = repository._projects[project_id]
    repository._projects[project_id] = project.model_copy(
        update={"state_version": 2, "updated_at": datetime.now(UTC)}
    )
    stale = client.post(
        f"/v1/deliveries/{draft['id']}/approve",
        json={"expected_state_version": 1, "actor_id": "producer@example.com"},
    )
    assert stale.status_code == 409
    assert "project changed" in stale.json()["detail"]

    repository._projects[project_id] = project
    approved = client.post(
        f"/v1/deliveries/{draft['id']}/approve",
        json={"expected_state_version": 1, "actor_id": "producer@example.com"},
    )
    assert approved.status_code == 200
    duplicate = client.post(
        f"/v1/deliveries/{draft['id']}/approve",
        json={"expected_state_version": 2, "actor_id": "producer@example.com"},
    )
    assert duplicate.status_code == 409
    assert "only draft" in duplicate.json()["detail"]
