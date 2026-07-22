from __future__ import annotations

from vtv_production.visual_adapters import (
    PassthroughSegmentationAdapter,
    PassthroughSubtitleCleanAdapter,
    PassthroughVisualGenerationAdapter,
)
from vtv_schemas.jobs import StageJob, StageResult

from .worker import VisualProductionWorker

__all__ = ["VisualProductionWorker", "execute"]


def execute(job: StageJob) -> StageResult:
    worker = VisualProductionWorker(
        segmentation=PassthroughSegmentationAdapter(),
        character_replace=PassthroughVisualGenerationAdapter(route_handled="C"),
        background_replace=PassthroughVisualGenerationAdapter(route_handled="D"),
        full_regen=PassthroughVisualGenerationAdapter(route_handled="F"),
        subtitle_clean=PassthroughSubtitleCleanAdapter(),
    )
    return worker.execute(job)
