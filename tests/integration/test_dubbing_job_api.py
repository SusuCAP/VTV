from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository
from vtv_schemas.episodes import EpisodeRead
from vtv_schemas.model_releases import ModelReleaseRead
from vtv_schemas.releases import ArtifactReleaseRead


def _released_artifact(project_id: UUID, artifact_type: str, asset_id: UUID) -> ArtifactReleaseRead:
    now = datetime.now(UTC)
    return ArtifactReleaseRead(
        id=uuid4(),
        project_id=project_id,
        artifact_type=artifact_type,
        version=1,
        status="RELEASED",
        state_version=3,
        content_asset_id=asset_id,
        created_at=now,
        updated_at=now,
        released_at=now,
    )


def _active_tts(workspace_id: UUID) -> ModelReleaseRead:
    now = datetime.now(UTC)
    return ModelReleaseRead(
        id=uuid4(),
        workspace_id=workspace_id,
        model_key="TTS",
        release_name="voxcpm2@approved-1",
        provider="self-hosted",
        endpoint="https://tts.example.invalid/v1/synthesize",
        license_id="voxcpm2-license",
        license_status="APPROVED",
        automation_status="ACTIVE",
        traffic_percent=100,
        state_version=4,
        model_card_uri="https://models.example.invalid/voxcpm2",
        config={"adapter_mode": "remote_tts"},
        approved_benchmark_release_id=uuid4(),
        created_at=now,
        updated_at=now,
    )


def _job_payload(
    episode_id: UUID,
    localization_id: UUID,
    voice_id: UUID,
    rights_id: str,
    *,
    seed_offset: int = 0,
) -> dict:
    return {
        "episode_id": str(episode_id),
        "localization_release_id": str(localization_id),
        "commercial_use": True,
        "utterances": [
            {
                "utterance_id": f"utterance-{index}",
                "character_id": "character-1",
                "source_text": "你好",
                "source_language": "zh-CN",
                "target_text": "Hello",
                "target_language": "en-US",
                "start_seconds": index * 2,
                "end_seconds": index * 2 + 1.5,
                "emotion": "warm",
                "voice_release_id": str(voice_id),
                "rights_release_id": rights_id,
                "seed": seed_offset + index,
                "candidate_count": 2,
                "maximum_duration_deviation": 0.04,
            }
            for index in (1, 2)
        ],
    }


def _setup(
    repository: MemoryRepository, client: TestClient
) -> tuple[dict, UUID, UUID, UUID, dict]:
    project = client.post(
        "/v1/projects",
        json={"name": "Dubbing", "target_market": "US", "locale": "en-US"},
    ).json()
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
    localization = _released_artifact(project_id, "LOCALIZATION_UTTERANCES", uuid4())
    voice_asset_id = uuid4()
    voice = _released_artifact(project_id, "VOICE_RELEASE", voice_asset_id)
    repository._releases[localization.id] = localization
    repository._releases[voice.id] = voice
    repository._asset_sha256s[voice_asset_id] = "c" * 64
    workspace_id = UUID(project["workspace_id"])
    model = _active_tts(workspace_id)
    repository._model_releases[model.id] = model
    now = datetime.now(UTC)
    rights = client.post(
        f"/v1/projects/{project_id}/rights-releases",
        json={
            "subject_type": "VOICE",
            "subject_id": "character-1",
            "allowed_operations": ["voice_clone"],
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
    return project, episode_id, localization.id, voice.id, rights


def test_dubbing_job_creates_one_registry_bound_stage_per_utterance() -> None:
    repository = MemoryRepository()
    with TestClient(create_app(repository=repository)) as client:
        project, episode_id, localization_id, voice_id, rights = _setup(
            repository, client
        )
        payload = _job_payload(
            episode_id, localization_id, voice_id, rights["id"]
        )

        accepted = client.post(
            f"/v1/projects/{project['id']}/dubbing-jobs", json=payload
        )
        repeated = client.post(
            f"/v1/projects/{project['id']}/dubbing-jobs", json=payload
        )

        assert accepted.status_code == 202
        assert repeated.json()["job_id"] == accepted.json()["job_id"]
        job = client.get(accepted.json()["status_url"]).json()
        assert job["kind"] == "EPISODE_DUBBING_CANDIDATES"
        assert job["total_stages"] == 2
        stage_params = repository._production_stage_params[UUID(job["id"])]
        assert len(stage_params) == 2
        assert all(item["model_runtime"]["model_key"] == "TTS" for item in stage_params)
        assert all(item["rights_state_version"] == 1 for item in stage_params)
        refreshed = client.get(f"/v1/projects/{project['id']}").json()
        assert refreshed["status"] == "PRODUCING"


def test_dubbing_job_rechecks_revoked_rights_for_new_request() -> None:
    repository = MemoryRepository()
    with TestClient(create_app(repository=repository)) as client:
        project, episode_id, localization_id, voice_id, rights = _setup(
            repository, client
        )
        revoked = client.post(
            f"/v1/rights-releases/{rights['id']}/revoke",
            json={
                "expected_state_version": 1,
                "actor_id": str(uuid4()),
                "reason": "withdrawn",
            },
        )
        assert revoked.status_code == 200

        blocked = client.post(
            f"/v1/projects/{project['id']}/dubbing-jobs",
            json=_job_payload(
                episode_id,
                localization_id,
                voice_id,
                rights["id"],
                seed_offset=100,
            ),
        )

        assert blocked.status_code == 409
        assert "RIGHTS_BLOCKED" in blocked.json()["detail"]
