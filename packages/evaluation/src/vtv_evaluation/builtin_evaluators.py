from __future__ import annotations

from .contracts import EvaluatorReleaseCreate, MetricDefinition

VISUAL_TECHNICAL_EVALUATOR = EvaluatorReleaseCreate(
    evaluator_key="visual_technical",
    release_name="vtv.visual-technical.v1",
    metric_definitions=(
        MetricDefinition(
            metric_name="frame_integrity",
            metric_version="v1",
            hard_failure_below=0.5,
        ),
        MetricDefinition(
            metric_name="duration_deviation",
            metric_version="v1",
            hard_failure_below=0.0,
        ),
        MetricDefinition(
            metric_name="resolution_match",
            metric_version="v1",
        ),
        MetricDefinition(
            metric_name="audio_stream_present",
            metric_version="v1",
            hard_failure_below=0.5,
        ),
    ),
    thresholds={
        "frame_integrity": 0.8,
        "duration_deviation": 0.9,
        "resolution_match": 0.8,
    },
)

VISUAL_IDENTITY_EVALUATOR = EvaluatorReleaseCreate(
    evaluator_key="visual_identity",
    release_name="vtv.visual-identity.v1",
    metric_definitions=(
        MetricDefinition(
            metric_name="character_identity_score",
            metric_version="v1",
            hard_failure_below=0.3,
        ),
        MetricDefinition(
            metric_name="expression_preservation",
            metric_version="v1",
        ),
        MetricDefinition(
            metric_name="clothing_consistency",
            metric_version="v1",
        ),
    ),
    thresholds={
        "character_identity_score": 0.6,
        "expression_preservation": 0.5,
    },
)

VISUAL_CONTINUITY_EVALUATOR = EvaluatorReleaseCreate(
    evaluator_key="visual_continuity",
    release_name="vtv.visual-continuity.v1",
    metric_definitions=(
        MetricDefinition(
            metric_name="scene_boundary_match",
            metric_version="v1",
        ),
        MetricDefinition(
            metric_name="color_consistency",
            metric_version="v1",
        ),
        MetricDefinition(
            metric_name="motion_smoothness",
            metric_version="v1",
        ),
    ),
    thresholds={
        "scene_boundary_match": 0.7,
        "color_consistency": 0.6,
    },
)

LIPSYNC_QC_EVALUATOR = EvaluatorReleaseCreate(
    evaluator_key="lipsync_qc",
    release_name="vtv.lipsync-qc.v1",
    metric_definitions=(
        MetricDefinition(
            metric_name="mouth_sync_score",
            metric_version="v1",
            hard_failure_below=0.2,
        ),
        MetricDefinition(
            metric_name="temporal_alignment",
            metric_version="v1",
            hard_failure_below=0.3,
        ),
        MetricDefinition(
            metric_name="naturalness_score",
            metric_version="v1",
        ),
    ),
    thresholds={
        "mouth_sync_score": 0.6,
        "temporal_alignment": 0.65,
    },
)

AUDIO_CONTINUITY_EVALUATOR = EvaluatorReleaseCreate(
    evaluator_key="audio_continuity",
    release_name="vtv.audio-continuity.v1",
    metric_definitions=(
        MetricDefinition(
            metric_name="loudness_consistency",
            metric_version="v1",
        ),
        MetricDefinition(
            metric_name="background_preservation",
            metric_version="v1",
        ),
        MetricDefinition(
            metric_name="dialogue_intelligibility",
            metric_version="v1",
            hard_failure_below=0.4,
        ),
    ),
    thresholds={
        "loudness_consistency": 0.7,
        "dialogue_intelligibility": 0.7,
    },
)

BUILTIN_EVALUATORS = (
    VISUAL_TECHNICAL_EVALUATOR,
    VISUAL_IDENTITY_EVALUATOR,
    VISUAL_CONTINUITY_EVALUATOR,
    LIPSYNC_QC_EVALUATOR,
    AUDIO_CONTINUITY_EVALUATOR,
)
