from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository
from vtv_schemas.candidates import CandidateGroupRead, CandidateVariantRead
from vtv_schemas.episodes import EpisodeRead


def _adopted_group(
    project_id: UUID,
    purpose: str,
    output_asset_id: UUID,
    *,
    shot_id: UUID | None = None,
) -> CandidateGroupRead:
    now = datetime.now(UTC)
    group_id = uuid4()
    variant = CandidateVariantRead(
        id=uuid4(),
        candidate_group_id=group_id,
        stage_run_id=uuid4(),
        variant_no=1,
        status="ADOPTED",
        seed=42,
        output_asset_id=output_asset_id,
        raw_metrics={},
        allocated_cost={},
        created_at=now,
        updated_at=now,
    )
    return CandidateGroupRead(
        id=group_id,
        project_id=project_id,
        shot_id=shot_id,
        purpose=purpose,
        status="ADOPTED",
        state_version=2,
        adopted_variant_id=variant.id,
        variants=(variant,),
        created_at=now,
        updated_at=now,
    )


def _setup():
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    project = client.post(
        "/v1/projects",
        json={
            "name": "Assembly",
            "target_market": "US",
            "locale": "en-US",
            "output": {
                "aspect_ratio": "9:16",
                "width": 320,
                "height": 568,
                "fps": 24,
                "video_codec": "h264",
                "audio_codec": "aac",
                "subtitle_formats": ["srt", "vtt", "burned"],
            },
        },
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
    source_id = uuid4()
    picture_id = uuid4()
    dialogue_id = uuid4()
    stem_id = uuid4()
    shot_id = uuid4()
    repository._lipsync_assets[source_id] = {
        "id": source_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "content_type": "video/mp4",
        "duration_seconds": 3.0,
        "sha256": "a" * 64,
    }
    repository._lipsync_assets[picture_id] = {
        "id": picture_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "content_type": "video/mp4",
        "duration_seconds": 1.0,
        "sha256": "b" * 64,
    }
    repository._lipsync_assets[dialogue_id] = {
        "id": dialogue_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "content_type": "audio/wav",
        "duration_seconds": 1.0,
        "sha256": "c" * 64,
    }
    repository._lipsync_assets[stem_id] = {
        "id": stem_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "content_type": "audio/wav",
        "duration_seconds": 3.0,
        "stem_kind": "BACKGROUND",
        "sha256": "d" * 64,
    }
    repository._lipsync_shots[shot_id] = {
        "id": shot_id,
        "episode_id": episode_id,
        "start_seconds": 1.0,
        "end_seconds": 2.0,
        "duration_seconds": 1.0,
    }
    leading_shot_id = uuid4()
    trailing_shot_id = uuid4()
    repository._lipsync_shots[leading_shot_id] = {
        "id": leading_shot_id,
        "episode_id": episode_id,
        "shot_no": 1,
        "start_seconds": 0.0,
        "end_seconds": 1.0,
        "duration_seconds": 1.0,
        "route": "L0",
    }
    repository._lipsync_shots[shot_id]["shot_no"] = 2
    repository._lipsync_shots[trailing_shot_id] = {
        "id": trailing_shot_id,
        "episode_id": episode_id,
        "shot_no": 3,
        "start_seconds": 2.0,
        "end_seconds": 3.0,
        "duration_seconds": 1.0,
        "route": "L0",
    }
    picture_group = _adopted_group(
        project_id, "LIPSYNC", picture_id, shot_id=shot_id
    )
    dialogue_group = _adopted_group(project_id, "TTS", dialogue_id)
    repository._candidate_groups[picture_group.id] = picture_group
    repository._candidate_groups[dialogue_group.id] = dialogue_group
    repository._variant_stage_params[dialogue_group.variants[0].id] = {
        "tts_request": {
            "localized": {
                "utterance": {"start_seconds": 1.0, "end_seconds": 2.0}
            }
        }
    }
    payload = {
        "episode_id": str(episode_id),
        "source_video_asset_id": str(source_id),
        "picture_selections": [
            {
                "shot_id": str(shot_id),
                "adopted_variant_id": str(picture_group.variants[0].id),
            }
        ],
        "dialogue_selections": [
            {
                "adopted_variant_id": str(dialogue_group.variants[0].id),
                "gain_db": -1,
                "room_reverb": 0.2,
            }
        ],
        "stem_selections": [
            {"asset_id": str(stem_id), "role": "BACKGROUND", "gain_db": -12}
        ],
        "subtitle_cues": [
            {
                "index": 1,
                "start_seconds": 1.0,
                "end_seconds": 2.0,
                "text": "Hello.",
                "speaker_id": "character-1",
            }
        ],
        "loudness_preset": "web-dialogue",
        "burn_subtitles": True,
    }
    return repository, client, project, payload, picture_group, dialogue_group


def test_assembly_job_builds_delivery_ready_dag_idempotently() -> None:
    repository, client, project, payload, _, _ = _setup()
    try:
        accepted = client.post(
            f"/v1/projects/{project['id']}/assembly-jobs", json=payload
        )
        repeated = client.post(
            f"/v1/projects/{project['id']}/assembly-jobs", json=payload
        )

        assert accepted.status_code == 202
        assert repeated.json()["job_id"] == accepted.json()["job_id"]
        job_id = UUID(accepted.json()["job_id"])
        params = repository._production_stage_params[job_id]
        assert [item["stage_type"] for item in params] == [
            "PICTURE_CONFORM",
            "SUBTITLE_RENDER",
            "AUDIO_MIX",
            "ASSEMBLE_EPISODE",
            "DELIVERY_EVIDENCE",
        ]
        assert params[0]["picture_conform_request"]["edits"][0]["start_seconds"] == 1
        assert {item["role"] for item in params[2]["audio_mix_request"]["tracks"]} == {
            "DIALOGUE",
            "BACKGROUND",
        }
        assert params[2]["audio_mix_request"]["preset"]["integrated_lufs"] == -16
        assert params[3]["episode_assembly_template"]["width"] == 320
        assert params[3]["episode_assembly_template"]["burn_subtitles"] is True
        assert len(params[4]["delivery_evidence_template"]["shots"]) == 3
    finally:
        client.close()


def test_assembly_job_rejects_non_adopted_picture_and_cross_episode_stem() -> None:
    repository, client, project, payload, picture_group, _ = _setup()
    try:
        repository._candidate_groups[picture_group.id] = picture_group.model_copy(
            update={"status": "OPEN", "adopted_variant_id": None}
        )
        rejected_picture = client.post(
            f"/v1/projects/{project['id']}/assembly-jobs", json=payload
        )
        assert rejected_picture.status_code == 409
        assert "adopted" in rejected_picture.json()["detail"]

        repository._candidate_groups[picture_group.id] = picture_group
        stem_id = UUID(payload["stem_selections"][0]["asset_id"])
        repository._lipsync_assets[stem_id]["episode_id"] = uuid4()
        rejected_stem = client.post(
            f"/v1/projects/{project['id']}/assembly-jobs", json=payload
        )
        assert rejected_stem.status_code == 409
        assert "stem" in rejected_stem.json()["detail"]
    finally:
        client.close()
