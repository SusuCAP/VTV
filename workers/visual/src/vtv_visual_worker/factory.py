"""Factory helpers for VisualProductionWorker with benchmark admission gate."""

from __future__ import annotations

from vtv_production.visual_adapters import (
    PassthroughSegmentationAdapter,
    PassthroughSubtitleCleanAdapter,
    PassthroughVisualGenerationAdapter,
)
from vtv_schemas.jobs import StageJob

from .worker import VisualProductionWorker


def create_worker_with_benchmark_check(
    benchmark_approved: bool = False,
    **adapter_kwargs: object,
) -> VisualProductionWorker:
    """Create VisualProductionWorker; require benchmark approval for real adapters.

    For passthrough adapters (the default), ``benchmark_approved`` is not
    enforced — passthrough paths are always permitted for contract testing.

    For production adapters bound to real model weights, set
    ``benchmark_approved=True`` only after a successful benchmark release has
    been submitted and approved via the ``POST /benchmark-releases`` API.
    Passing ``passthrough=False`` without ``benchmark_approved=True`` raises
    ``ValueError`` to prevent unapproved weights from reaching production.

    Args:
        benchmark_approved: Whether a visual golden benchmark release has been
            approved for the model weights that will be used.
        **adapter_kwargs: Optional overrides forwarded to adapter construction.
            Recognised keys:
            - ``passthrough`` (bool, default True): when False, enforce the
              benchmark gate (for use with real model-weight adapters).

    Returns:
        A fully-constructed :class:`VisualProductionWorker` ready to execute
        visual production stage jobs.

    Raises:
        ValueError: If ``passthrough=False`` and ``benchmark_approved`` is not
            True, indicating that unapproved model weights must not be used.
    """
    is_passthrough: bool = bool(adapter_kwargs.get("passthrough", False))
    contract_test = bool(adapter_kwargs.get("contract_test", False))

    if is_passthrough and not contract_test:
        raise ValueError(
            "passthrough visual adapters are test-only; select a benchmark-approved "
            "production adapter"
        )
    if not is_passthrough and not benchmark_approved:
        raise ValueError(
            "Real visual generation adapters require benchmark_approved=True. "
            "Submit a visual benchmark report via the benchmark release API and "
            "set benchmark_approved=True before creating a production worker."
        )

    return VisualProductionWorker(
        segmentation=PassthroughSegmentationAdapter(),
        character_replace=PassthroughVisualGenerationAdapter(route_handled="C"),
        background_replace=PassthroughVisualGenerationAdapter(route_handled="D"),
        full_regen=PassthroughVisualGenerationAdapter(route_handled="F"),
        subtitle_clean=PassthroughSubtitleCleanAdapter(),
    )


def create_worker_for_job(job: StageJob) -> VisualProductionWorker:
    """Create a VisualProductionWorker whose adapters match the job's model_runtime.

    Reads ``job.params.get("model_runtime", {})`` and dispatches to real or
    passthrough adapters accordingly.  Real adapters (sam3, wan_animate) are
    loaded lazily so CI environments without GPU packages can still import this
    module without error.

    Adapter modes recognised:
        segmentation_adapter_mode: "passthrough" | "sam3"
        adapter_mode (visual generation): "passthrough" | "wan_animate"
    """
    runtime: dict = job.params.get("model_runtime") or {}
    if not runtime:
        raise ValueError("visual production requires a registry-selected model runtime")
    seg_mode = runtime.get("segmentation_adapter_mode")
    gen_mode = runtime.get("adapter_mode")

    # -- segmentation adapter --------------------------------------------------
    if seg_mode == "sam3":
        from vtv_production.sam3_adapter import Sam31SegmentationAdapter
        segmentation = Sam31SegmentationAdapter()
    elif seg_mode == "matanyone2":
        from vtv_production.matanyone2_adapter import MatAnyone2Adapter
        segmentation = MatAnyone2Adapter()
    else:
        raise ValueError(f"unsupported segmentation adapter mode: {seg_mode}")

    # -- visual generation adapters -------------------------------------------
    if gen_mode == "wan_animate":
        from vtv_production.wan_animate_adapter import WanAnimateAdapter
        # Wan-Animate handles character replace (C), joint replace (E), and full regen (F)
        character_replace = WanAnimateAdapter()
        background_replace = WanAnimateAdapter()  # also handles D until a VACE adapter ships
        full_regen = WanAnimateAdapter()
    elif gen_mode == "mocha":
        from vtv_production.mocha_adapter import MoChaAdapter
        character_replace = MoChaAdapter()
        background_replace = MoChaAdapter()
        full_regen = MoChaAdapter()
    elif gen_mode == "hunyuan_custom":
        from vtv_production.hunyuan_custom_adapter import HunyuanCustomAdapter
        character_replace = HunyuanCustomAdapter()
        background_replace = HunyuanCustomAdapter()
        full_regen = HunyuanCustomAdapter()
    elif gen_mode == "vace":
        from vtv_production.vace_adapter import VACEAdapter
        character_replace = VACEAdapter()
        background_replace = VACEAdapter()
        full_regen = VACEAdapter()
    elif gen_mode == "ltx23":
        from vtv_production.ltx23_adapter import LTX23Adapter
        character_replace = LTX23Adapter()
        background_replace = LTX23Adapter()
        full_regen = LTX23Adapter()
    else:
        raise ValueError(f"unsupported visual generation adapter mode: {gen_mode}")

    return VisualProductionWorker(
        segmentation=segmentation,
        character_replace=character_replace,
        background_replace=background_replace,
        full_regen=full_regen,
        subtitle_clean=None,
    )
