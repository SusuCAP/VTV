from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vtv_analysis_worker import execute as execute_analysis
from vtv_media_worker import execute as execute_media
from vtv_schemas.jobs import StageJob, StageResult

from .mock_worker import execute as execute_mock

MEDIA_STAGES = frozenset({"INGEST_VALIDATE", "PROXY_GENERATE", "SHOT_DETECT"})
ANALYSIS_STAGES = frozenset({"ASR_ALIGN", "VISION_ANALYSIS", "PROJECT_SYNTHESIS"})


@dataclass(frozen=True, slots=True)
class StageRouter:
    work_root: Path
    media_executor: Callable[[StageJob], StageResult] = execute_media
    analysis_executor: Callable[[StageJob], StageResult] = execute_analysis
    fallback_executor: Callable[[StageJob], StageResult] = execute_mock

    def execute(self, job: StageJob) -> StageResult:
        try:
            if job.stage_type in MEDIA_STAGES:
                return self.media_executor(self._with_local_output(job))
            if job.stage_type in ANALYSIS_STAGES:
                return self.analysis_executor(self._with_local_output(job))
            return self.fallback_executor(job)
        except Exception as exc:
            return StageResult(
                stage_run_id=job.stage_run_id,
                stage_attempt_id=job.stage_attempt_id,
                status="EXECUTION_FAILED",
                error_class=type(exc).__name__,
                error_detail={"message": str(exc), "retryable": False},
                attempt_usage={"worker": "stage-router", "local": True},
            )

    def _with_local_output(self, job: StageJob) -> StageJob:
        output = (
            self.work_root
            / str(job.project_id)
            / str(job.episode_id or "project")
            / str(job.stage_run_id)
        )
        output.mkdir(parents=True, exist_ok=True)
        return job.model_copy(update={"output_prefix": output.resolve().as_uri()})
