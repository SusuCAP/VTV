from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from .contracts import (
    EpisodeWorkflowPlan,
    ShotVisualFeatures,
    ShotWorkflowDecision,
    VisualRoute,
)

_COST_TIER = Literal["FREE", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"]

_TIER_ORDER: dict[str, int] = {
    "FREE": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "VERY_HIGH": 4,
}
_TIER_NAMES = ["FREE", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"]


def _max_tier(a: str, b: str) -> str:
    return a if _TIER_ORDER[a] >= _TIER_ORDER[b] else b


@dataclass(frozen=True, slots=True)
class VisualShotRouter:
    router_release: str = "tiered-visual-router@1"

    def route(self, features: ShotVisualFeatures) -> ShotWorkflowDecision:
        route, reason_codes = self._classify(features)
        candidate_count = self._candidate_count(route, features)
        cost_tier = self._cost_tier(route, features)
        return ShotWorkflowDecision(
            shot_id=features.shot_id,
            shot_no=features.shot_no,
            route=route,
            reason_codes=reason_codes,
            candidate_count=candidate_count,
            cost_tier=cost_tier,
            router_release=self.router_release,
        )

    def plan(
        self, episode_id: UUID, shots: tuple[ShotVisualFeatures, ...]
    ) -> EpisodeWorkflowPlan:
        decisions = tuple(self.route(f) for f in shots)
        distribution: dict[str, int] = {}
        for d in decisions:
            distribution[d.route.value] = distribution.get(d.route.value, 0) + 1
        overall = "FREE"
        for d in decisions:
            overall = _max_tier(overall, d.cost_tier)
        return EpisodeWorkflowPlan(
            episode_id=episode_id,
            total_shots=len(shots),
            decisions=decisions,
            route_distribution=distribution,
            estimated_cost_tier=overall,
            router_release=self.router_release,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify(
        self, f: ShotVisualFeatures
    ) -> tuple[VisualRoute, tuple[str, ...]]:
        # Priority 1: FULL_REGEN
        if f.full_regen_required:
            return VisualRoute.FULL_REGEN, ("FULL_REGEN_REQUIRED",)
        if f.person_count >= 3:
            return VisualRoute.FULL_REGEN, ("GROUP_SHOT",)

        has_face = f.has_face_visible
        has_bg = f.has_background_replacement_needed

        # Priority 2: JOINT_REPLACE
        if has_face and has_bg:
            return VisualRoute.JOINT_REPLACE, ("FACE_REPLACEMENT", "BACKGROUND_REPLACEMENT")

        # Priority 3: CHARACTER_REPLACE
        if has_face and not has_bg:
            return VisualRoute.CHARACTER_REPLACE, ("FACE_REPLACEMENT",)

        # Priority 4: BACKGROUND_REPLACE
        if has_bg and not has_face:
            return VisualRoute.BACKGROUND_REPLACE, ("BACKGROUND_REPLACEMENT",)

        # Priority 5: SUBTITLE_CLEAN
        if f.has_text_overlay:
            return VisualRoute.SUBTITLE_CLEAN, ("TEXT_OVERLAY_DETECTED",)

        # Priority 6: PRESERVE
        return VisualRoute.PRESERVE, ("NO_ACTIVE_ELEMENTS",)

    def _candidate_count(self, route: VisualRoute, f: ShotVisualFeatures) -> int:
        if route is VisualRoute.PRESERVE:
            return 1
        if route is VisualRoute.SUBTITLE_CLEAN:
            return 1
        if route is VisualRoute.CHARACTER_REPLACE:
            return 4 if f.max_face_scale > 0.3 else 2
        if route is VisualRoute.BACKGROUND_REPLACE:
            return 2
        if route is VisualRoute.JOINT_REPLACE:
            return 3
        # FULL_REGEN
        return 4

    def _cost_tier(self, route: VisualRoute, f: ShotVisualFeatures) -> _COST_TIER:  # type: ignore[return]
        if route is VisualRoute.PRESERVE:
            return "FREE"
        if route is VisualRoute.SUBTITLE_CLEAN:
            return "LOW"
        if route is VisualRoute.CHARACTER_REPLACE:
            return "MEDIUM" if f.max_face_scale > 0.3 else "LOW"
        if route is VisualRoute.BACKGROUND_REPLACE:
            return "MEDIUM"
        if route is VisualRoute.JOINT_REPLACE:
            return "HIGH"
        # FULL_REGEN
        return "VERY_HIGH"
