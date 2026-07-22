from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository
from vtv_schemas.candidates import CandidateGroupRead, CandidateVariantRead


def _setup(
    purpose: str = "TTS",
) -> tuple[MemoryRepository, TestClient, dict, dict, CandidateGroupRead]:
    repository = MemoryRepository()
    client = TestClient(create_app(repository=repository))
    project = client.post(
        "/v1/projects",
        json={"name": "Selection", "target_market": "US", "locale": "en-US"},
    ).json()
    now = datetime.now(UTC)
    rights = client.post(
        f"/v1/projects/{project['id']}/rights-releases",
        json={
            "subject_type": "VOICE",
            "subject_id": "character-1",
            "allowed_operations": (
                ["voice_clone", "lipsync"] if purpose == "LIPSYNC" else ["voice_clone"]
            ),
            "allowed_markets": ["US"],
            "allowed_languages": ["en-US"],
            "commercial_scope": "COMMERCIAL",
            "valid_from": (now - timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "evidence_uri": "s3://rights/voice.pdf",
            "evidence_sha256": "e" * 64,
            "created_by": str(uuid4()),
        },
    ).json()
    group_id = uuid4()
    variants = tuple(
        CandidateVariantRead(
            id=uuid4(),
            candidate_group_id=group_id,
            stage_run_id=uuid4(),
            variant_no=index,
            status="GENERATED",
            seed=40 + index,
            output_asset_id=uuid4(),
            raw_metrics={"duration_deviation": 0.01},
            allocated_cost={"usd": "0.01"},
            created_at=now,
            updated_at=now,
        )
        for index in (1, 2)
    )
    group = CandidateGroupRead(
        id=group_id,
        project_id=UUID(project["id"]),
        purpose=purpose,
        status="OPEN",
        state_version=1,
        variants=variants,
        created_at=now,
        updated_at=now,
    )
    repository._candidate_groups[group.id] = group
    params = {
        "rights_state_version": 1,
        "tts_request": {
            "commercial_use": True,
            "localized": {"target_market": "US", "target_language": "en-US"},
            "voice_release": {
                "rights": {
                    "rights_release_id": rights["id"],
                    "state_version": 1,
                }
            },
        },
    }
    repository._variant_stage_params.update({item.id: params for item in variants})
    return repository, client, project, rights, group


def _qc(client: TestClient, variant_id: UUID, verdict: str, hard_failure: bool = False):
    metric_names = (
        "tts_intelligibility",
        "speaker_similarity",
        "emotion_fidelity",
        "duration_fit",
        "audio_artifact_control",
    )
    return client.post(
        f"/v1/candidate-variants/{variant_id}/qc",
        json={
            "metrics": [
                {
                    "metric_name": name,
                    "metric_version": "metric@1",
                    "evaluator_release": "evaluator@1",
                    "score": 0.95 if verdict == "PASS" else 0.2,
                    "verdict": verdict,
                    "hard_failure": hard_failure and name == "audio_artifact_control",
                }
                for name in metric_names
            ]
        },
    )


def test_qc_and_adoption_enforce_pass_cas_and_unique_winner() -> None:
    repository, client, project, _, group = _setup()
    try:
        passed = _qc(client, group.variants[0].id, "PASS")
        failed = _qc(client, group.variants[1].id, "FAIL", hard_failure=True)
        assert passed.status_code == 200
        assert passed.json()["status"] == "QC_PASSED"
        assert failed.json()["status"] == "QC_FAILED"

        rejected = client.post(
            f"/v1/candidate-groups/{group.id}/adopt",
            json={
                "variant_id": str(group.variants[1].id),
                "expected_state_version": 1,
                "actor_id": str(uuid4()),
            },
        )
        assert rejected.status_code == 409

        adopted = client.post(
            f"/v1/candidate-groups/{group.id}/adopt",
            json={
                "variant_id": str(group.variants[0].id),
                "expected_state_version": 1,
                "actor_id": str(uuid4()),
            },
        )
        assert adopted.status_code == 200
        body = adopted.json()
        assert body["status"] == "ADOPTED"
        assert body["state_version"] == 2
        assert body["adopted_variant_id"] == str(group.variants[0].id)
        assert {item["status"] for item in body["variants"]} == {"ADOPTED", "REJECTED"}

        stale_cas = client.post(
            f"/v1/candidate-groups/{group.id}/adopt",
            json={
                "variant_id": str(group.variants[0].id),
                "expected_state_version": 1,
                "actor_id": str(uuid4()),
            },
        )
        assert stale_cas.status_code == 409
        listed = client.get(f"/v1/projects/{project['id']}/candidate-groups")
        assert listed.status_code == 200
        assert listed.json()[0]["adopted_variant_id"] == str(group.variants[0].id)
    finally:
        client.close()
        del repository


def test_tts_qc_rejects_incomplete_evidence() -> None:
    _, client, _, _, group = _setup()
    try:
        response = client.post(
            f"/v1/candidate-variants/{group.variants[0].id}/qc",
            json={
                "metrics": [
                    {
                        "metric_name": "tts_intelligibility",
                        "metric_version": "metric@1",
                        "evaluator_release": "evaluator@1",
                        "score": 0.95,
                        "verdict": "PASS",
                    }
                ]
            },
        )
        assert response.status_code == 409
        assert "incomplete" in response.json()["detail"]
    finally:
        client.close()


def test_lipsync_qc_requires_full_video_evidence() -> None:
    _, client, _, _, group = _setup("LIPSYNC")
    try:
        incomplete = client.post(
            f"/v1/candidate-variants/{group.variants[0].id}/qc",
            json={
                "metrics": [
                    {
                        "metric_name": "lipsync_alignment",
                        "metric_version": "metric@1",
                        "evaluator_release": "evaluator@1",
                        "score": 0.95,
                        "verdict": "PASS",
                    }
                ]
            },
        )
        assert incomplete.status_code == 409

        complete = client.post(
            f"/v1/candidate-variants/{group.variants[0].id}/qc",
            json={
                "metrics": [
                    {
                        "metric_name": name,
                        "metric_version": "metric@1",
                        "evaluator_release": "evaluator@1",
                        "score": 0.95,
                        "verdict": "PASS",
                    }
                    for name in (
                        "technical_integrity",
                        "identity_consistency",
                        "temporal_stability",
                        "structure_integrity",
                        "lipsync_alignment",
                        "continuity",
                    )
                ]
            },
        )
        assert complete.status_code == 200
        assert complete.json()["status"] == "QC_PASSED"
    finally:
        client.close()


def test_lipsync_adoption_rechecks_lipsync_rights() -> None:
    repository, client, _, rights, group = _setup("LIPSYNC")
    try:
        repository._variant_stage_params[group.variants[0].id] = {
            "lipsync_request": {
                "target_market": "US",
                "target_language": "en-US",
                "commercial_use": True,
                "rights": {
                    "rights_release_id": rights["id"],
                    "state_version": 1,
                },
            }
        }
        complete = client.post(
            f"/v1/candidate-variants/{group.variants[0].id}/qc",
            json={
                "metrics": [
                    {
                        "metric_name": name,
                        "metric_version": "metric@1",
                        "evaluator_release": "evaluator@1",
                        "score": 0.95,
                        "verdict": "PASS",
                    }
                    for name in (
                        "technical_integrity",
                        "identity_consistency",
                        "temporal_stability",
                        "structure_integrity",
                        "lipsync_alignment",
                        "continuity",
                    )
                ]
            },
        )
        assert complete.status_code == 200
        revoked = client.post(
            f"/v1/rights-releases/{rights['id']}/revoke",
            json={
                "expected_state_version": 1,
                "actor_id": str(uuid4()),
                "reason": "withdrawn before lipsync adoption",
            },
        )
        assert revoked.status_code == 200
        adopted = client.post(
            f"/v1/candidate-groups/{group.id}/adopt",
            json={
                "variant_id": str(group.variants[0].id),
                "expected_state_version": 1,
                "actor_id": str(uuid4()),
            },
        )
        assert adopted.status_code == 409
        assert "RIGHTS_BLOCKED" in adopted.json()["detail"]
    finally:
        client.close()


def test_adoption_rechecks_rights_after_qc() -> None:
    _, client, _, rights, group = _setup()
    try:
        assert _qc(client, group.variants[0].id, "PASS").status_code == 200
        revoked = client.post(
            f"/v1/rights-releases/{rights['id']}/revoke",
            json={
                "expected_state_version": 1,
                "actor_id": str(uuid4()),
                "reason": "withdrawn after QC",
            },
        )
        assert revoked.status_code == 200
        adopted = client.post(
            f"/v1/candidate-groups/{group.id}/adopt",
            json={
                "variant_id": str(group.variants[0].id),
                "expected_state_version": 1,
                "actor_id": str(uuid4()),
            },
        )
        assert adopted.status_code == 409
        assert "RIGHTS_BLOCKED" in adopted.json()["detail"]
    finally:
        client.close()
