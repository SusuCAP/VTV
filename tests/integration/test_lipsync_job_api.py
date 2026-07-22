from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository
from vtv_schemas.candidates import CandidateGroupRead, CandidateVariantRead
from vtv_schemas.episodes import EpisodeRead
from vtv_schemas.model_releases import ModelReleaseRead


def _active_lipsync(workspace_id: UUID, model_key: str = "LIPSYNC_L2") -> ModelReleaseRead:
    now = datetime.now(UTC)
    return ModelReleaseRead(
        id=uuid4(),
        workspace_id=workspace_id,
        model_key=model_key,
        release_name="latentsync@1.6-approved",
        provider="self-hosted",
        endpoint="https://lipsync.example.invalid/v1/render",
        license_id="lipsync-license",
        license_status="APPROVED",
        automation_status="ACTIVE",
        traffic_percent=100,
        state_version=4,
        model_card_uri="https://models.example.invalid/latentsync",
        config={"adapter_mode": "remote_lipsync"},
        approved_benchmark_release_id=uuid4(),
        created_at=now,
        updated_at=now,
    )


def _setup(*, allow_lipsync: bool = True):
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    project = client.post(
        "/v1/projects",
        json={"name": "LipSync", "target_market": "US", "locale": "en-US"},
    ).json()
    project_id = UUID(project["id"])
    workspace_id = UUID(project["workspace_id"])
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
    now = datetime.now(UTC)
    operations = ["voice_clone", "lipsync"] if allow_lipsync else ["voice_clone"]
    rights = client.post(
        f"/v1/projects/{project_id}/rights-releases",
        json={
            "subject_type": "VOICE",
            "subject_id": "character-1",
            "allowed_operations": operations,
            "allowed_markets": ["US"],
            "allowed_languages": ["en-US"],
            "commercial_scope": "COMMERCIAL",
            "valid_from": (now - timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "evidence_uri": "s3://rights/voice.pdf",
            "evidence_sha256": "d" * 64,
            "created_by": str(uuid4()),
        },
    ).json()
    model = _active_lipsync(workspace_id)
    repository._model_releases[model.id] = model
    shot_id = uuid4()
    source_asset_id = uuid4()
    audio_asset_id = uuid4()
    repository._lipsync_shots[shot_id] = {
        "episode_id": episode_id,
        "duration_seconds": 2.0,
    }
    repository._lipsync_assets[source_asset_id] = {
        "project_id": project_id,
        "shot_id": shot_id,
        "content_type": "video/mp4",
        "duration_seconds": 2.0,
        "sha256": "a" * 64,
    }
    repository._lipsync_assets[audio_asset_id] = {
        "project_id": project_id,
        "content_type": "audio/wav",
        "duration_seconds": 1.8,
        "sha256": "b" * 64,
    }
    group_id = uuid4()
    variant = CandidateVariantRead(
        id=uuid4(),
        candidate_group_id=group_id,
        stage_run_id=uuid4(),
        variant_no=1,
        status="ADOPTED",
        seed=42,
        output_asset_id=audio_asset_id,
        raw_metrics={},
        allocated_cost={},
        created_at=now,
        updated_at=now,
    )
    repository._candidate_groups[group_id] = CandidateGroupRead(
        id=group_id,
        project_id=project_id,
        purpose="TTS",
        status="ADOPTED",
        state_version=2,
        adopted_variant_id=variant.id,
        variants=(variant,),
        created_at=now,
        updated_at=now,
    )
    repository._variant_stage_params[variant.id] = {
        "tts_request": {
            "localized": {"target_language": "en-US", "target_market": "US"},
            "voice_release": {
                "rights": {"rights_release_id": rights["id"], "state_version": 1}
            },
        }
    }
    return repository, client, project, episode_id, shot_id, source_asset_id, variant


def _payload(episode_id, shot_id, source_asset_id, variant_id, **features):
    values = {
        "mouth_visible": True,
        "face_scale": 0.3,
        "occlusion": 0.1,
        "body_visible": False,
        "dialogue_duration_seconds": 1.8,
    }
    values.update(features)
    return {
        "episode_id": str(episode_id),
        "commercial_use": True,
        "shots": [
            {
                "shot_id": str(shot_id),
                "source_video_asset_id": str(source_asset_id),
                "adopted_tts_variant_id": str(variant_id),
                "seed": 100,
                "candidate_count": 3,
                **values,
            }
        ],
    }


def test_lipsync_job_routes_adopted_tts_to_registry_model_idempotently() -> None:
    repository, client, project, episode_id, shot_id, source_id, variant = _setup()
    try:
        payload = _payload(episode_id, shot_id, source_id, variant.id)
        accepted = client.post(
            f"/v1/projects/{project['id']}/lipsync-jobs", json=payload
        )
        repeated = client.post(
            f"/v1/projects/{project['id']}/lipsync-jobs", json=payload
        )

        assert accepted.status_code == 202
        assert repeated.json()["job_id"] == accepted.json()["job_id"]
        job_id = UUID(accepted.json()["job_id"])
        params = repository._production_stage_params[job_id][0]
        assert params["lipsync_request"]["decision"]["level"] == "L2_PRESERVE_SOURCE"
        assert params["lipsync_request"]["source_video_duration_seconds"] == 2
        assert params["model_runtime"]["model_key"] == "LIPSYNC_L2"
        assert params["input_asset_ids"] == [str(source_id), str(variant.output_asset_id)]
    finally:
        client.close()


def test_l0_forces_local_single_candidate_without_model_runtime() -> None:
    repository, client, project, episode_id, shot_id, source_id, variant = _setup()
    try:
        response = client.post(
            f"/v1/projects/{project['id']}/lipsync-jobs",
            json=_payload(
                episode_id,
                shot_id,
                source_id,
                variant.id,
                mouth_visible=False,
                face_scale=0.01,
            ),
        )
        assert response.status_code == 202
        params = repository._production_stage_params[UUID(response.json()["job_id"])][0]
        assert params["lipsync_request"]["decision"]["level"] == "L0_NONE"
        assert params["lipsync_request"]["candidate_count"] == 1
        assert "model_runtime" not in params
    finally:
        client.close()


def test_lipsync_job_requires_separate_lipsync_operation_right() -> None:
    repository, client, project, episode_id, shot_id, source_id, variant = _setup(
        allow_lipsync=False
    )
    try:
        response = client.post(
            f"/v1/projects/{project['id']}/lipsync-jobs",
            json=_payload(episode_id, shot_id, source_id, variant.id),
        )
        assert response.status_code == 409
        assert "OPERATION_NOT_ALLOWED" in response.json()["detail"]
        assert not repository._production_stage_params
    finally:
        client.close()
