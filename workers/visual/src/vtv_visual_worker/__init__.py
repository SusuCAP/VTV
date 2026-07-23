from __future__ import annotations

from vtv_schemas.jobs import StageJob, StageResult

from .factory import create_worker_for_job
from .worker import VisualProductionWorker

__all__ = ["VisualProductionWorker", "execute"]


def execute(job: StageJob) -> StageResult:
    """Dispatch visual production stage to the correct adapter based on model_runtime."""
    return create_worker_for_job(job).execute(job)
