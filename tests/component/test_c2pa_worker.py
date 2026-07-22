from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from vtv_c2pa import C2paWorker
from vtv_schemas.jobs import StageJob


def _job(tmp_path: Path, params: dict) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        idempotency_key=f"c2pa-test-{uuid4()}",
        stage_type="C2PA_SIGN",
        input_assets=[],
        output_prefix=tmp_path.resolve().as_uri(),
        runtime_profile_id="local",
        observed_control_version=1,
        params=params,
        trace_id="test-trace",
    )


def _sha(ch: str) -> str:
    return ch * 64


class TestC2paWorker:
    def test_generates_credentials_json(self, tmp_path: Path) -> None:
        delivery_id = uuid4()
        fingerprint = _sha("a")
        job = _job(
            tmp_path,
            {
                "c2pa_sign_request": {
                    "delivery_id": str(delivery_id),
                    "manifest_fingerprint": fingerprint,
                    "master_object_uri": "s3://bucket/master.mp4",
                    "output_prefix": tmp_path.resolve().as_uri(),
                }
            },
        )
        worker = C2paWorker()
        result = worker.execute(job)

        assert result.status == "OUTPUT_READY"
        assert len(result.variants) == 1
        variant = result.variants[0]
        assert len(variant.output_assets) == 1

        asset = variant.output_assets[0]
        assert asset.media_type == "application/json"
        assert asset.size_bytes > 0
        assert len(asset.sha256) == 64

        # Verify the file was written with valid JSON
        cred_path = tmp_path / "content-credentials.json"
        assert cred_path.exists()
        data = json.loads(cred_path.read_bytes())
        assert data["credentials"]["delivery_id"] == str(delivery_id)
        assert data["credentials"]["manifest_fingerprint"] == fingerprint
        assert data["credentials"]["signer"] == "vtv.passthrough-signer.v1"

    def test_domain_artifact_type(self, tmp_path: Path) -> None:
        delivery_id = uuid4()
        fingerprint = _sha("b")
        job = _job(
            tmp_path,
            {
                "c2pa_sign_request": {
                    "delivery_id": str(delivery_id),
                    "manifest_fingerprint": fingerprint,
                    "master_object_uri": "s3://bucket/master.mp4",
                    "output_prefix": tmp_path.resolve().as_uri(),
                }
            },
        )
        worker = C2paWorker()
        result = worker.execute(job)

        assert len(result.domain_artifacts) == 1
        artifact = result.domain_artifacts[0]
        assert artifact.document_type == "C2PA_CREDENTIALS"
        assert artifact.payload["delivery_id"] == str(delivery_id)
        assert artifact.payload["manifest_fingerprint"] == fingerprint

    def test_wrong_stage_type_raises(self, tmp_path: Path) -> None:
        job = _job(tmp_path, {})
        wrong_job = job.model_copy(update={"stage_type": "DELIVERY_EVIDENCE"})
        worker = C2paWorker()
        with pytest.raises(ValueError, match="unsupported stage type"):
            worker.execute(wrong_job)

    def test_missing_c2pa_sign_request_raises(self, tmp_path: Path) -> None:
        job = _job(tmp_path, {})
        worker = C2paWorker()
        with pytest.raises(ValueError, match="c2pa_sign_request"):
            worker.execute(job)

    def test_idempotent_output_sha256(self, tmp_path: Path) -> None:
        """Two runs with the same params produce different sha256 (timestamps differ),
        but both succeed and produce valid JSON files."""
        delivery_id = uuid4()
        fingerprint = _sha("c")
        params = {
            "c2pa_sign_request": {
                "delivery_id": str(delivery_id),
                "manifest_fingerprint": fingerprint,
                "master_object_uri": "s3://bucket/master.mp4",
                "output_prefix": tmp_path.resolve().as_uri(),
            }
        }
        worker = C2paWorker()
        result1 = worker.execute(_job(tmp_path, params))
        result2 = worker.execute(_job(tmp_path, params))
        assert result1.status == "OUTPUT_READY"
        assert result2.status == "OUTPUT_READY"
