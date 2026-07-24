from __future__ import annotations

from dataclasses import dataclass

import modal
from modal.exception import TimeoutError as ModalTimeoutError
from vtv_schemas.jobs import StageJob, StageResult

_MODAL_STAGE_TARGETS: dict[str, tuple[str, str]] = {
    "INGEST_VALIDATE": ("vtv-analysis", "execute_analysis_stage"),
    "PROXY_GENERATE": ("vtv-analysis", "execute_analysis_stage"),
    "SHOT_DETECT": ("vtv-analysis", "execute_analysis_stage"),
    "AUDIO_STEM_SEPARATION": ("vtv-audio", "execute_audio_stage"),
    "ASR_ALIGN": ("vtv-audio", "execute_audio_stage"),
    "VISION_ANALYSIS": ("vtv-analysis", "execute_analysis_stage"),
    "PROJECT_SYNTHESIS": ("vtv-analysis", "execute_analysis_stage"),
    "TTS_GENERATE": ("vtv-production", "execute_production_stage"),
    "LIPSYNC_GENERATE": ("vtv-production", "execute_production_stage"),
    "VISUAL_CHARACTER_REPLACE": ("vtv-visual", "execute_visual_stage"),
    "VISUAL_BACKGROUND_REPLACE": ("vtv-visual", "execute_visual_stage"),
    "VISUAL_JOINT_REPLACE": ("vtv-visual", "execute_visual_stage"),
    "VISUAL_FULL_REGEN": ("vtv-visual", "execute_visual_stage"),
    "VISUAL_SUBTITLE_CLEAN": ("vtv-visual", "execute_visual_stage"),
    "VISUAL_KEYFRAME_PREVIEW": ("vtv-visual", "execute_visual_stage"),
    "VISUAL_QC": ("vtv-visual", "execute_visual_stage"),
    "PICTURE_CONFORM": ("vtv-assemble", "execute_assemble_stage"),
    "SUBTITLE_RENDER": ("vtv-assemble", "execute_assemble_stage"),
    "AUDIO_MIX": ("vtv-assemble", "execute_assemble_stage"),
    "ASSEMBLE_EPISODE": ("vtv-assemble", "execute_assemble_stage"),
    "DELIVERY_EVIDENCE": ("vtv-assemble", "execute_assemble_stage"),
    "SHOT_ROUTING": ("vtv-assemble", "execute_assemble_stage"),
}


def modal_target_for_stage(stage_type: str) -> tuple[str, str]:
    try:
        return _MODAL_STAGE_TARGETS[stage_type]
    except KeyError as exc:
        raise ValueError(f"stage has no deployed Modal target: {stage_type}") from exc


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


@dataclass(frozen=True, slots=True)
class ModalStageGateway:
    """Non-blocking Modal submission and restart-safe result collection."""

    environment_name: str | None = None

    def spawn(self, job: StageJob) -> str:
        app_name, function_name = modal_target_for_stage(job.stage_type)
        function = modal.Function.from_name(
            app_name,
            function_name,
            environment_name=self.environment_name,
        )
        call = function.spawn(job.model_dump(mode="json"))
        if not call.object_id:
            raise RuntimeError("Modal spawn returned no function call ID")
        return call.object_id

    def get_result(self, modal_call_id: str) -> StageResult | None:
        call = modal.FunctionCall.from_id(modal_call_id)
        try:
            payload = call.get(timeout=0)
        except (TimeoutError, ModalTimeoutError):
            return None
        return StageResult.model_validate(payload)

    def cancel(self, modal_call_id: str) -> None:
        modal.FunctionCall.from_id(modal_call_id).cancel()
