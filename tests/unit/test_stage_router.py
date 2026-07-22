from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from vtv_orchestrator.stage_router import StageRouter
from vtv_schemas.jobs import AssetRef, StageJob, StageResult, VariantResult


def _job(stage_type: str) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        idempotency_key=f"test:{stage_type}",
        stage_type=stage_type,
        output_prefix="memory://old",
        runtime_profile_id="test",
        observed_control_version=1,
        trace_id="router-test",
    )


def _successful(job: StageJob) -> StageResult:
    return StageResult(
        stage_run_id=job.stage_run_id,
        stage_attempt_id=job.stage_attempt_id,
        status="OUTPUT_READY",
        attempt_usage={"output_prefix": job.output_prefix},
    )


def test_router_sends_concrete_stages_to_local_workers(tmp_path: Path) -> None:
    router = StageRouter(
        tmp_path,
        media_executor=_successful,
        analysis_executor=_successful,
        fallback_executor=_successful,
    )

    media = router.execute(_job("PROXY_GENERATE"))
    analysis = router.execute(_job("ASR_ALIGN"))
    fallback = router.execute(_job("MOCK_RENDER"))

    assert media.attempt_usage["output_prefix"].startswith("file://")
    assert analysis.attempt_usage["output_prefix"].startswith("file://")
    assert fallback.attempt_usage["output_prefix"] == "memory://old"


def test_router_converts_worker_exception_to_stage_failure(tmp_path: Path) -> None:
    def fail(job: StageJob) -> StageResult:
        raise RuntimeError(f"cannot execute {job.stage_type}")

    result = StageRouter(tmp_path, media_executor=fail).execute(_job("SHOT_DETECT"))

    assert result.status == "EXECUTION_FAILED"
    assert result.error_class == "RuntimeError"
    assert result.error_detail == {
        "message": "cannot execute SHOT_DETECT",
        "retryable": False,
    }


class FakeWorkerStore:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.uploaded_keys: list[str] = []

    def download_file(
        self,
        *,
        object_uri: str,
        destination: Path,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> Path:
        assert object_uri.startswith("s3://")
        assert expected_sha256 == sha256(self.payload).hexdigest()
        assert expected_size_bytes == len(self.payload)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.payload)
        return destination

    def upload_file(
        self, *, source: Path, object_key: str, content_type: str
    ) -> AssetRef:
        payload = source.read_bytes()
        self.uploaded_keys.append(object_key)
        return AssetRef(
            uri=f"s3://bucket/{object_key}",
            sha256=sha256(payload).hexdigest(),
            media_type=content_type,
            size_bytes=len(payload),
        )


def test_router_materializes_s3_input_and_uploads_worker_output(tmp_path: Path) -> None:
    payload = b"source"
    store = FakeWorkerStore(payload)

    def execute(job: StageJob) -> StageResult:
        local_input = Path(job.input_assets[0].uri.removeprefix("file://"))
        output = Path(job.output_prefix.removeprefix("file://")) / "result.json"
        output.write_bytes(local_input.read_bytes() + b"-result")
        digest = sha256(output.read_bytes()).hexdigest()
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[
                VariantResult(
                    variant_no=1,
                    output_assets=[
                        AssetRef(
                            uri=output.resolve().as_uri(),
                            sha256=digest,
                            media_type="application/json",
                            size_bytes=output.stat().st_size,
                        )
                    ],
                )
            ],
        )

    job = _job("INGEST_VALIDATE").model_copy(
        update={
            "input_assets": [
                AssetRef(
                    uri="s3://bucket/source.mp4",
                    sha256=sha256(payload).hexdigest(),
                    media_type="video/mp4",
                    size_bytes=len(payload),
                )
            ]
        }
    )
    result = StageRouter(tmp_path, media_executor=execute, object_store=store).execute(job)

    assert result.status == "OUTPUT_READY"
    assert result.variants[0].output_assets[0].uri.startswith("s3://bucket/projects/")
    assert store.uploaded_keys[0].endswith("/result.json")


def test_router_rejects_worker_output_with_false_digest(tmp_path: Path) -> None:
    store = FakeWorkerStore(b"source")

    def execute(job: StageJob) -> StageResult:
        output = Path(job.output_prefix.removeprefix("file://")) / "bad.json"
        output.write_bytes(b"actual")
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[
                VariantResult(
                    variant_no=1,
                    output_assets=[
                        AssetRef(
                            uri=output.resolve().as_uri(),
                            sha256="0" * 64,
                            media_type="application/json",
                            size_bytes=output.stat().st_size,
                        )
                    ],
                )
            ],
        )

    result = StageRouter(tmp_path, media_executor=execute, object_store=store).execute(
        _job("INGEST_VALIDATE")
    )

    assert result.status == "EXECUTION_FAILED"
    assert result.error_detail and "SHA-256" in result.error_detail["message"]
    assert store.uploaded_keys == []
