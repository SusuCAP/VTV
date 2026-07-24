from __future__ import annotations

import json
from dataclasses import dataclass

import modal
from modal.exception import TimeoutError as ModalTimeoutError
from vtv_schemas.jobs import StageJob, StageResult


@dataclass(frozen=True, slots=True)
class ModalTarget:
    app_name: str
    callable_name: str
    class_name: str | None = None


_MODAL_STAGE_TARGETS: dict[str, ModalTarget] = {
    "INGEST_VALIDATE": ModalTarget("vtv-analysis", "run", "AnalysisStageWorker"),
    "PROXY_GENERATE": ModalTarget("vtv-analysis", "run", "AnalysisStageWorker"),
    "SHOT_DETECT": ModalTarget("vtv-analysis", "run", "AnalysisStageWorker"),
    "AUDIO_STEM_SEPARATION": ModalTarget("vtv-audio", "run", "AudioStageWorker"),
    "ASR_ALIGN": ModalTarget("vtv-audio", "run", "AudioStageWorker"),
    "VISION_ANALYSIS": ModalTarget("vtv-analysis", "run", "AnalysisStageWorker"),
    "PROJECT_SYNTHESIS": ModalTarget("vtv-analysis", "run", "AnalysisStageWorker"),
    "TTS_GENERATE": ModalTarget("vtv-production", "run", "ProductionStageWorker"),
    "LIPSYNC_GENERATE": ModalTarget("vtv-production", "run", "ProductionStageWorker"),
    "VISUAL_CHARACTER_REPLACE": ModalTarget("vtv-visual", "run", "VisualStageWorker"),
    "VISUAL_BACKGROUND_REPLACE": ModalTarget("vtv-visual", "run", "VisualStageWorker"),
    "VISUAL_JOINT_REPLACE": ModalTarget("vtv-visual", "run", "VisualStageWorker"),
    "VISUAL_FULL_REGEN": ModalTarget("vtv-visual", "run", "VisualStageWorker"),
    "VISUAL_SUBTITLE_CLEAN": ModalTarget("vtv-visual", "run", "VisualStageWorker"),
    "VISUAL_KEYFRAME_PREVIEW": ModalTarget("vtv-visual", "run", "VisualStageWorker"),
    "VISUAL_QC": ModalTarget("vtv-visual", "run", "VisualStageWorker"),
    "PICTURE_CONFORM": ModalTarget("vtv-assemble", "execute_assemble_stage"),
    "SUBTITLE_RENDER": ModalTarget("vtv-assemble", "execute_assemble_stage"),
    "AUDIO_MIX": ModalTarget("vtv-assemble", "execute_assemble_stage"),
    "ASSEMBLE_EPISODE": ModalTarget("vtv-assemble", "execute_assemble_stage"),
    "DELIVERY_EVIDENCE": ModalTarget("vtv-assemble", "execute_assemble_stage"),
    "SHOT_ROUTING": ModalTarget("vtv-assemble", "execute_assemble_stage"),
}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def modal_workload_json(job: StageJob) -> str:
    """Return the stable Modal pool key for workload-size dimensions."""
    params = job.params
    runtime = params.get("model_runtime")
    runtime = runtime if isinstance(runtime, dict) else {}
    runtime_config = runtime.get("config")
    runtime_config = runtime_config if isinstance(runtime_config, dict) else {}

    request: dict[str, object] = {}
    for key in (
        "visual_generation_request",
        "lipsync_request",
        "tts_request",
        "vision_analysis_request",
    ):
        value = params.get(key)
        if isinstance(value, dict):
            request = value
            break
    request_parameters = request.get("parameters")
    request_parameters = (
        request_parameters if isinstance(request_parameters, dict) else {}
    )

    sources = (params, request_parameters, request, runtime_config, runtime)

    def first_value(*keys: str) -> object | None:
        for source in sources:
            for key in keys:
                value = source.get(key)
                if value is not None:
                    return value
        return None

    workload: dict[str, object] = {}
    resolution = first_value("resolution", "target_resolution")
    width = first_value("width", "target_width")
    height = first_value("height", "target_height")
    if resolution is not None:
        workload["resolution"] = resolution
    elif width is not None or height is not None:
        workload["resolution"] = {"height": height, "width": width}

    frame_count = first_value("frame_count", "num_frames", "target_frame_count")
    if frame_count is not None:
        workload["frame_count"] = frame_count

    decision = request.get("decision")
    if isinstance(decision, dict) and decision.get("level") is not None:
        workload["lipsync_level"] = decision["level"]

    reference_count = first_value("reference_count")
    if reference_count is None:
        references = request.get("reference_asset_sha256s")
        if not isinstance(references, (list, tuple)):
            voice_release = request.get("voice_release")
            references = (
                voice_release.get("reference_asset_sha256s")
                if isinstance(voice_release, dict)
                else None
            )
        if isinstance(references, (list, tuple)):
            reference_count = len(references)
        else:
            reference_count = sum(
                asset.media_type.startswith("image/") for asset in job.input_assets
            )
    workload["reference_count"] = reference_count
    return _canonical_json(workload)


def modal_target_for_stage(stage_type: str) -> ModalTarget:
    try:
        return _MODAL_STAGE_TARGETS[stage_type]
    except KeyError as exc:
        raise ValueError(f"stage has no deployed Modal target: {stage_type}") from exc


def _modal_callable(
    target: ModalTarget,
    job: StageJob,
    environment_name: str | None,
):
    if target.class_name is None:
        return modal.Function.from_name(
            target.app_name,
            target.callable_name,
            environment_name=environment_name,
        )
    runtime = job.params.get("model_runtime")
    runtime_json = _canonical_json(runtime if isinstance(runtime, dict) else {})
    worker_class = modal.Cls.from_name(
        target.app_name,
        target.class_name,
        environment_name=environment_name,
    )
    worker = worker_class(
        stage_type=job.stage_type,
        runtime_json=runtime_json,
        workload_json=modal_workload_json(job),
    )
    return getattr(worker, target.callable_name)


@dataclass(frozen=True, slots=True)
class ModalStageExecutor:
    environment_name: str | None = None

    def execute(self, job: StageJob) -> StageResult:
        try:
            function = _modal_callable(
                modal_target_for_stage(job.stage_type),
                job,
                self.environment_name,
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
        function = _modal_callable(
            modal_target_for_stage(job.stage_type),
            job,
            self.environment_name,
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
