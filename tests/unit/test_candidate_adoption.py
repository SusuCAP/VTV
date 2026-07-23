from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from vtv_schemas.candidates import (
    CandidateAdoptRequest,
    CandidateAdoptResult,
)
from vtv_schemas.project_stats import QualitySnapshot

# --- CandidateAdoptRequest ---


def test_candidate_adopt_request_defaults() -> None:
    req = CandidateAdoptRequest(actor_id="user-123")
    assert req.reason == "manual-adoption"
    assert req.override_qc_failure is False


def test_candidate_adopt_request_override_qc_failure_validation() -> None:
    req = CandidateAdoptRequest(actor_id="supervisor", override_qc_failure=True)
    assert req.override_qc_failure is True
    req2 = CandidateAdoptRequest(actor_id="supervisor", override_qc_failure=False)
    assert req2.override_qc_failure is False


# --- CandidateAdoptResult ---


def test_candidate_adopt_result_fields() -> None:
    now = datetime.now(UTC)
    variant_id = uuid4()
    group_id = uuid4()
    result = CandidateAdoptResult(
        variant_id=variant_id,
        candidate_group_id=group_id,
        previous_status="QC_PASSED",
        new_status="ADOPTED",
        actor_id="reviewer-42",
        adopted_at=now,
    )
    assert result.variant_id == variant_id
    assert result.candidate_group_id == group_id
    assert result.previous_status == "QC_PASSED"
    assert result.new_status == "ADOPTED"
    assert result.actor_id == "reviewer-42"
    assert result.adopted_at == now


# --- QualitySnapshot ---


def test_quality_snapshot_pass_rate_zero_when_no_candidates() -> None:
    snap = QualitySnapshot(
        project_id=uuid4(),
        total_candidates_generated=0,
        qc_passed=0,
        qc_failed=0,
        qc_review=0,
        adopted_count=0,
        pass_rate=0.0,
        generated_at=datetime.now(UTC),
    )
    assert snap.pass_rate == 0.0
    assert snap.total_candidates_generated == 0


def test_quality_snapshot_circuit_breaker_default_false() -> None:
    snap = QualitySnapshot(
        project_id=uuid4(),
        total_candidates_generated=5,
        qc_passed=3,
        qc_failed=2,
        qc_review=0,
        adopted_count=1,
        pass_rate=0.6,
        generated_at=datetime.now(UTC),
    )
    assert snap.circuit_breaker_active is False


def test_quality_snapshot_top_failure_reasons_list() -> None:
    snap = QualitySnapshot(
        project_id=uuid4(),
        total_candidates_generated=10,
        qc_passed=5,
        qc_failed=5,
        qc_review=0,
        adopted_count=3,
        pass_rate=0.5,
        top_failure_reasons=["audio_artifact_control", "speaker_similarity"],
        generated_at=datetime.now(UTC),
    )
    assert snap.top_failure_reasons == ["audio_artifact_control", "speaker_similarity"]
    assert isinstance(snap.top_failure_reasons, list)
