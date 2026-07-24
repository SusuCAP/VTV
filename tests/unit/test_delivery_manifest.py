from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_delivery import (
    ApprovalEvidence,
    CostSummary,
    DeliveredAsset,
    DeliveryEvidenceRequest,
    DeliveryManifestBuilder,
    EditStageEvidence,
    QcEvidence,
    ShotDeliveryEntry,
)


def _hash(character: str) -> str:
    return character * 64


def _asset(role: str, digest: str) -> DeliveredAsset:
    return DeliveredAsset(
        asset_id=uuid4(),
        role=role,
        object_uri=f"s3://deliveries/{role.lower()}",
        sha256=digest,
        size_bytes=10,
        content_type=(
            "application/json"
            if role.endswith("REPORT") or role == "SHOT_LIST"
            else "video/mp4"
        ),
    )


def _manifest_values() -> dict:
    master = _hash("b")
    return {
        "delivery_id": uuid4(),
        "workspace_id": uuid4(),
        "project_id": uuid4(),
        "episode_id": uuid4(),
        "project_state_version": 3,
        "generated_at": datetime.now(UTC),
        "assets": (
            _asset("SOURCE_VIDEO", _hash("a")),
            _asset("MASTER_VIDEO", master),
            _asset("SUBTITLE_SRT", _hash("c")),
            _asset("QUALITY_REPORT", _hash("d")),
            _asset("SHOT_LIST", _hash("e")),
        ),
        "edit_chain": (
            EditStageEvidence(
                stage_run_id=uuid4(),
                stage_type="ASSEMBLE_EPISODE",
                input_sha256s=(_hash("a"),),
                output_sha256s=(master,),
                parameters_sha256=_hash("f"),
            ),
        ),
        "approvals": (
            ApprovalEvidence(
                subject_type="DELIVERY",
                subject_id=uuid4(),
                decision="APPROVED",
                actor_id="reviewer@example.com",
                state_version=1,
                decided_at=datetime.now(UTC),
            ),
        ),
        "qc": (
            QcEvidence(
                metric_name="master_duration",
                metric_version="v1",
                evaluator_release="ffmpeg-7",
                score=1,
                verdict="PASS",
            ),
        ),
        "shots": (
            ShotDeliveryEntry(
                shot_id=uuid4(),
                shot_no=1,
                start_ms=0,
                end_ms=1000,
                route="L0",
                qc_verdict="SOURCE_UNCHANGED",
            ),
            ShotDeliveryEntry(
                shot_id=uuid4(),
                shot_no=2,
                start_ms=1000,
                end_ms=2000,
                route="L2",
                adopted_variant_id=uuid4(),
                output_asset_id=uuid4(),
                qc_verdict="PASS",
            ),
        ),
        "cost": CostSummary(total=Decimal("1.2"), by_stage={"ASSEMBLE_EPISODE": Decimal("1")}),
        "final_encoding": {"video_codec": "h264", "audio_codec": "aac"},
        "c2pa_status": "NOT_REQUESTED",
    }


def test_manifest_is_deterministic_and_closes_provenance_chain() -> None:
    values = _manifest_values()
    first = DeliveryManifestBuilder.build(**values)
    second = DeliveryManifestBuilder.build(**{**values, "generated_at": datetime.now(UTC)})

    assert first.fingerprint == second.fingerprint
    assert first.assets[1].sha256 in first.edit_chain[0].output_sha256s


def test_manifest_fingerprint_excludes_mutable_c2pa_state() -> None:
    values = _manifest_values()
    pending = DeliveryManifestBuilder.build(**{**values, "c2pa_status": "PENDING"})
    embedded = DeliveryManifestBuilder.build(**{**values, "c2pa_status": "EMBEDDED"})

    assert pending.fingerprint == embedded.fingerprint


def test_manifest_rejects_untraceable_master_and_shot_gap() -> None:
    values = _manifest_values()
    values["edit_chain"] = (
        values["edit_chain"][0].model_copy(update={"output_sha256s": (_hash("9"),)}),
    )
    with pytest.raises(ValidationError, match="master must be traceable"):
        DeliveryManifestBuilder.build(**values)

    values = _manifest_values()
    values["shots"] = (
        values["shots"][0],
        values["shots"][1].model_copy(update={"start_ms": 1001}),
    )
    with pytest.raises(ValidationError, match="shot list must be contiguous"):
        DeliveryManifestBuilder.build(**values)


def test_manifest_rejects_hard_failure_and_incomplete_asset_set() -> None:
    with pytest.raises(ValidationError, match="hard failures"):
        QcEvidence(
            metric_name="identity",
            metric_version="v1",
            evaluator_release="qc-v1",
            score=0,
            verdict="REVIEW",
            hard_failure=True,
        )

    values = _manifest_values()
    values["assets"] = tuple(asset for asset in values["assets"] if asset.role != "SHOT_LIST")
    with pytest.raises(ValidationError, match="requires source, master"):
        DeliveryManifestBuilder.build(**values)


def test_delivery_evidence_requires_full_timeline_and_traceable_master() -> None:
    master_hash = _hash("b")
    values = {
        "source_video_sha256": _hash("a"),
        "master_video_sha256": master_hash,
        "project_state_version": 2,
        "duration_ms": 2000,
        "edit_chain": (
            EditStageEvidence(
                stage_run_id=uuid4(),
                stage_type="ASSEMBLE_EPISODE",
                output_sha256s=(master_hash,),
                parameters_sha256=_hash("f"),
            ),
        ),
        "shots": (
            ShotDeliveryEntry(
                shot_id=uuid4(),
                shot_no=1,
                start_ms=0,
                end_ms=2000,
                route="L0",
                qc_verdict="SOURCE_UNCHANGED",
            ),
        ),
        "cost": CostSummary(total=Decimal()),
        "final_encoding": {"video_codec": "h264"},
    }
    request = DeliveryEvidenceRequest.model_validate(values)
    assert request.shots[-1].end_ms == request.duration_ms

    with pytest.raises(ValidationError, match="span the full episode"):
        DeliveryEvidenceRequest.model_validate(
            {**values, "shots": (values["shots"][0].model_copy(update={"end_ms": 1999}),)}
        )
    with pytest.raises(ValidationError, match="traceable"):
        DeliveryEvidenceRequest.model_validate(
            {**values, "master_video_sha256": _hash("9")}
        )
