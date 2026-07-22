from __future__ import annotations

from dataclasses import dataclass

import modal
from vtv_schemas.jobs import StageJob, StageResult


@dataclass(frozen=True, slots=True)
class ModalStageExecutor:
    app_name: str = "vtv-analysis"
    function_name: str = "execute_analysis_stage"
    environment_name: str | None = None

    def execute(self, job: StageJob) -> StageResult:
        try:
            function = modal.Function.from_name(
                self.app_name,
                self.function_name,
                environment_name=self.environment_name,
            )
            payload = function.remote(job.model_dump(mode="json"))
            result = StageResult.model_validate(payload)
            if (
                result.stage_run_id != job.stage_run_id
                or result.stage_attempt_id != job.stage_attempt_id
            ):
                raise ValueError("Modal result identity does not match submitted stage")
            return result
        except Exception as exc:
            return StageResult(
                stage_run_id=job.stage_run_id,
                stage_attempt_id=job.stage_attempt_id,
                status="EXECUTION_FAILED",
                error_class=type(exc).__name__,
                error_detail={"message": str(exc), "retryable": True},
                attempt_usage={"worker": "modal", "remote": True},
            )
