from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from vtv_c2pa import C2paSignerOutput, C2paWorker
from vtv_delivery import C2paSignRequest
from vtv_schemas.jobs import AssetRef, StageJob


class StubSigner:
    signer_id = "kms:delivery-signing"

    def sign(
        self,
        request: C2paSignRequest,
        master_path: Path,
        output_directory: Path,
    ) -> C2paSignerOutput:
        credential = output_directory / "content-credentials.json"
        credential.write_text(request.manifest_fingerprint, encoding="utf-8")
        signed_master = output_directory / "master.content-credentials.mp4"
        signed_master.write_bytes(master_path.read_bytes() + b"-signed")
        return C2paSignerOutput(
            credential_path=credential,
            signed_master_path=signed_master,
            assertions=("c2pa.actions.v2", "org.vtv.delivery.v1"),
            signed_at=datetime.now(UTC),
        )


def _job(tmp_path: Path) -> StageJob:
    master = tmp_path / "master.mp4"
    master.write_bytes(b"immutable-master")
    digest = sha256(master.read_bytes()).hexdigest()
    delivery_id = uuid4()
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        idempotency_key=f"c2pa:{delivery_id}",
        stage_type="C2PA_SIGN",
        input_assets=[
            AssetRef(
                uri=master.resolve().as_uri(),
                sha256=digest,
                media_type="video/mp4",
                size_bytes=master.stat().st_size,
            )
        ],
        output_prefix=(tmp_path / "output").resolve().as_uri(),
        runtime_profile_id="local",
        observed_control_version=1,
        params={
            "master_sha256": digest,
            "c2pa_sign_request": {
                "delivery_id": str(delivery_id),
                "manifest_fingerprint": "a" * 64,
                "master_object_uri": "s3://bucket/master.mp4",
                "output_prefix": "s3://bucket/c2pa",
                "signer_id": StubSigner.signer_id,
            },
        },
        trace_id="c2pa-component",
    )


def test_c2pa_worker_emits_verified_report_and_signed_master(tmp_path: Path) -> None:
    result = C2paWorker(StubSigner()).execute(_job(tmp_path))

    assert result.status == "OUTPUT_READY"
    assets = result.variants[0].output_assets
    assert [asset.media_type for asset in assets] == [
        "application/json",
        "video/mp4",
    ]
    assert assets[1].metadata["role"] == "C2PA_SIGNED_MASTER"
    artifact = result.domain_artifacts[0]
    assert artifact.document_type == "C2PA_CREDENTIALS"
    assert artifact.payload["signer_id"] == StubSigner.signer_id
    assert artifact.payload["signed_master_sha256"] == assets[1].sha256


def test_c2pa_worker_rejects_missing_real_signer(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="real C2PA SDK-backed signer"):
        C2paWorker().execute(_job(tmp_path))


def test_c2pa_worker_rejects_signer_identity_mismatch(tmp_path: Path) -> None:
    job = _job(tmp_path)
    request = {
        **job.params["c2pa_sign_request"],
        "signer_id": "kms:unexpected",
    }
    job = job.model_copy(
        update={"params": {**job.params, "c2pa_sign_request": request}}
    )

    with pytest.raises(ValueError, match="identity"):
        C2paWorker(StubSigner()).execute(job)


def test_c2pa_worker_rejects_master_hash_mismatch(tmp_path: Path) -> None:
    job = _job(tmp_path)
    Path(job.input_assets[0].uri.removeprefix("file://")).write_bytes(b"tampered")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        C2paWorker(StubSigner()).execute(job)
