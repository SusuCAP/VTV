from dataclasses import dataclass

from .contracts import (
    LipSyncDecision,
    LipSyncLevel,
    ShotDialogueFeatures,
)


@dataclass(frozen=True, slots=True)
class TieredLipSyncRouter:
    router_release: str = "tiered-lipsync-router@1"

    def route(self, features: ShotDialogueFeatures) -> LipSyncDecision:
        if not features.mouth_visible or features.face_scale < 0.05:
            return self._decision(features, LipSyncLevel.L0_NONE, "MOUTH_NOT_VISIBLE")
        if features.full_regeneration_required or not features.original_performance_reusable:
            return self._decision(features, LipSyncLevel.L5_FULL_REGEN, "FULL_REGEN_REQUIRED")
        if features.body_visible and features.dialogue_duration_seconds >= 4:
            return self._decision(features, LipSyncLevel.L4_FULL_BODY, "FULL_BODY_DIALOGUE")
        if features.occlusion >= 0.4:
            return self._decision(features, LipSyncLevel.L3_GENERATIVE_FACE, "HIGH_OCCLUSION")
        if features.face_scale >= 0.2:
            return self._decision(
                features, LipSyncLevel.L2_PRESERVE_SOURCE, "VISIBLE_CLOSE_DIALOGUE"
            )
        return self._decision(features, LipSyncLevel.L1_FAST, "STANDARD_DIALOGUE")

    def _decision(
        self,
        features: ShotDialogueFeatures,
        level: LipSyncLevel,
        reason: str,
    ) -> LipSyncDecision:
        deviation = 0.04 if features.face_scale >= 0.2 and features.mouth_visible else 0.08
        return LipSyncDecision(
            shot_id=features.shot_id,
            level=level,
            reason_codes=(reason,),
            maximum_duration_deviation=deviation,
        )
