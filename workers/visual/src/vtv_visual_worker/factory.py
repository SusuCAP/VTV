"""Factory helpers for VisualProductionWorker with benchmark admission gate."""

from __future__ import annotations

from vtv_production.visual_adapters import (
    PassthroughSegmentationAdapter,
    PassthroughSubtitleCleanAdapter,
    PassthroughVisualGenerationAdapter,
)

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

    This is a forward-compatibility hook.  All current adapter instances are
    passthrough; the enforcement path is exercised once real adapters ship.

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
    is_passthrough: bool = bool(adapter_kwargs.get("passthrough", True))

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
