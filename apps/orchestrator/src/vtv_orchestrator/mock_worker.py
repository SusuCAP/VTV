from hashlib import sha256

from vtv_schemas.jobs import AssetRef, StageJob, StageResult, VariantResult


def execute(job: StageJob) -> StageResult:
    """Deterministic worker used by local and CI end-to-end orchestration tests."""
    if job.params.get("force_failure"):
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="EXECUTION_FAILED",
            error_class="MOCK_FAILURE",
            error_detail={"retryable": True},
        )
    payload = f"{job.stage_run_id}:{job.stage_type}".encode()
    digest = sha256(payload).hexdigest()
    media_type = (
        "video/mp4"
        if job.stage_type in {"PROXY_GENERATE", "MOCK_RENDER", "ASSEMBLE_EPISODE"}
        else "application/json"
    )
    extension = "mp4" if media_type == "video/mp4" else "json"
    return StageResult(
        stage_run_id=job.stage_run_id,
        stage_attempt_id=job.stage_attempt_id,
        status="OUTPUT_READY",
        variants=[
            VariantResult(
                variant_no=1,
                output_assets=[
                    AssetRef(
                        uri=f"{job.output_prefix}/result.{extension}",
                        sha256=digest,
                        media_type=media_type,
                        size_bytes=len(payload),
                    )
                ],
                raw_metrics={"mock": True, "stage_type": job.stage_type},
                allocated_cost={"usd": 0},
            )
        ],
        attempt_usage={"cpu_core_seconds": 0.01, "worker": "mock"},
    )
