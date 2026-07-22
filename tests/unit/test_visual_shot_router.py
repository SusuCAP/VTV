from __future__ import annotations

from uuid import uuid4

import pytest
from vtv_routing import (
    EpisodeWorkflowPlan,
    ShotVisualFeatures,
    VisualRoute,
    VisualShotRouter,
)


def _features(**kwargs) -> ShotVisualFeatures:
    defaults = dict(
        shot_id=uuid4(),
        shot_no=1,
        start_ms=0,
        end_ms=2000,
        duration_ms=2000,
        person_count=0,
        has_face_visible=False,
        max_face_scale=0.0,
        max_occlusion=0.0,
        has_text_overlay=False,
        has_dialogue=False,
        dialogue_duration_seconds=0.0,
    )
    defaults.update(kwargs)
    return ShotVisualFeatures(**defaults)


router = VisualShotRouter()


# ------------------------------------------------------------------
# Route A – PRESERVE
# ------------------------------------------------------------------


def test_route_a_no_active_elements() -> None:
    decision = router.route(_features())
    assert decision.route is VisualRoute.PRESERVE
    assert decision.candidate_count == 1
    assert decision.cost_tier == "FREE"
    assert "NO_ACTIVE_ELEMENTS" in decision.reason_codes


# ------------------------------------------------------------------
# Route B – SUBTITLE_CLEAN
# ------------------------------------------------------------------


def test_route_b_text_overlay_no_face() -> None:
    decision = router.route(_features(has_text_overlay=True))
    assert decision.route is VisualRoute.SUBTITLE_CLEAN
    assert decision.candidate_count == 1
    assert decision.cost_tier == "LOW"
    assert "TEXT_OVERLAY_DETECTED" in decision.reason_codes


# ------------------------------------------------------------------
# Route C – CHARACTER_REPLACE
# ------------------------------------------------------------------


def test_route_c_face_no_background() -> None:
    decision = router.route(_features(has_face_visible=True, person_count=1))
    assert decision.route is VisualRoute.CHARACTER_REPLACE
    assert decision.candidate_count == 2
    assert decision.cost_tier == "LOW"
    assert "FACE_REPLACEMENT" in decision.reason_codes


def test_route_c_close_up_face_gets_four_candidates() -> None:
    decision = router.route(
        _features(has_face_visible=True, person_count=1, max_face_scale=0.35)
    )
    assert decision.route is VisualRoute.CHARACTER_REPLACE
    assert decision.candidate_count == 4
    assert decision.cost_tier == "MEDIUM"


def test_route_c_face_scale_boundary_at_0_3() -> None:
    # exactly 0.3 → NOT close-up (threshold is strictly >0.3)
    decision = router.route(
        _features(has_face_visible=True, person_count=1, max_face_scale=0.3)
    )
    assert decision.candidate_count == 2
    assert decision.cost_tier == "LOW"


# ------------------------------------------------------------------
# Route D – BACKGROUND_REPLACE
# ------------------------------------------------------------------


def test_route_d_background_no_face() -> None:
    decision = router.route(_features(has_background_replacement_needed=True))
    assert decision.route is VisualRoute.BACKGROUND_REPLACE
    assert decision.candidate_count == 2
    assert decision.cost_tier == "MEDIUM"
    assert "BACKGROUND_REPLACEMENT" in decision.reason_codes


# ------------------------------------------------------------------
# Route E – JOINT_REPLACE
# ------------------------------------------------------------------


def test_route_e_face_and_background() -> None:
    decision = router.route(
        _features(
            has_face_visible=True,
            person_count=1,
            has_background_replacement_needed=True,
        )
    )
    assert decision.route is VisualRoute.JOINT_REPLACE
    assert decision.candidate_count == 3
    assert decision.cost_tier == "HIGH"
    assert "FACE_REPLACEMENT" in decision.reason_codes
    assert "BACKGROUND_REPLACEMENT" in decision.reason_codes


# ------------------------------------------------------------------
# Route F – FULL_REGEN
# ------------------------------------------------------------------


def test_route_f_group_shot_three_persons() -> None:
    decision = router.route(_features(person_count=3, has_face_visible=True))
    assert decision.route is VisualRoute.FULL_REGEN
    assert decision.candidate_count == 4
    assert decision.cost_tier == "VERY_HIGH"
    assert "GROUP_SHOT" in decision.reason_codes


def test_route_f_explicit_full_regen_flag() -> None:
    decision = router.route(_features(full_regen_required=True))
    assert decision.route is VisualRoute.FULL_REGEN
    assert "FULL_REGEN_REQUIRED" in decision.reason_codes


def test_route_f_full_regen_overrides_face_and_background() -> None:
    # Even with face + bg, explicit flag wins
    decision = router.route(
        _features(
            has_face_visible=True,
            has_background_replacement_needed=True,
            full_regen_required=True,
        )
    )
    assert decision.route is VisualRoute.FULL_REGEN


def test_route_f_group_shot_many_persons() -> None:
    decision = router.route(_features(person_count=5))
    assert decision.route is VisualRoute.FULL_REGEN


# ------------------------------------------------------------------
# Decision fields
# ------------------------------------------------------------------


def test_decision_carries_router_release() -> None:
    decision = router.route(_features())
    assert decision.router_release == "tiered-visual-router@1"


def test_decision_shot_metadata_preserved() -> None:
    sid = uuid4()
    decision = router.route(_features(shot_id=sid, shot_no=7))
    assert decision.shot_id == sid
    assert decision.shot_no == 7


# ------------------------------------------------------------------
# EpisodeWorkflowPlan
# ------------------------------------------------------------------


def _shot(shot_no: int, **kwargs) -> ShotVisualFeatures:
    return _features(
        shot_id=uuid4(),
        shot_no=shot_no,
        start_ms=(shot_no - 1) * 2000,
        end_ms=shot_no * 2000,
        duration_ms=2000,
        **kwargs,
    )


def test_plan_produces_episode_workflow_plan() -> None:
    shots = (
        _shot(1),
        _shot(2, has_face_visible=True, person_count=1),
        _shot(3, has_text_overlay=True),
    )
    plan = router.plan(uuid4(), shots)
    assert isinstance(plan, EpisodeWorkflowPlan)
    assert plan.total_shots == 3
    assert plan.schema_version == "vtv.workflow-plan.v1"
    assert len(plan.decisions) == 3


def test_plan_route_distribution_counts() -> None:
    shots = (
        _shot(1),
        _shot(2),
        _shot(3, has_face_visible=True, person_count=1),
    )
    plan = router.plan(uuid4(), shots)
    assert plan.route_distribution.get("A", 0) == 2
    assert plan.route_distribution.get("C", 0) == 1


def test_plan_estimated_cost_uses_highest_tier() -> None:
    shots = (
        _shot(1),
        _shot(2, person_count=3),
    )
    plan = router.plan(uuid4(), shots)
    assert plan.estimated_cost_tier == "VERY_HIGH"


def test_plan_contiguous_shot_numbers_validated() -> None:
    episode_id = uuid4()
    shots = (
        _shot(1),
        _shot(3),  # gap — should fail
    )
    with pytest.raises(ValueError, match="contiguous"):
        router.plan(episode_id, shots)


def test_plan_decision_count_must_match_total_shots() -> None:
    """EpisodeWorkflowPlan validator rejects mismatched decision count."""
    shots = (_shot(1), _shot(2))
    plan = router.plan(uuid4(), shots)
    with pytest.raises(ValueError, match="decisions must cover all shots"):
        EpisodeWorkflowPlan(
            episode_id=uuid4(),
            total_shots=5,
            decisions=plan.decisions,
            route_distribution=plan.route_distribution,
            estimated_cost_tier=plan.estimated_cost_tier,
            router_release=plan.router_release,
        )


def test_plan_carries_router_release() -> None:
    plan = router.plan(uuid4(), (_shot(1),))
    assert plan.router_release == "tiered-visual-router@1"


# ------------------------------------------------------------------
# ShotVisualFeatures validation
# ------------------------------------------------------------------


def test_features_end_must_be_after_start() -> None:
    with pytest.raises(ValueError):
        ShotVisualFeatures(
            shot_id=uuid4(),
            shot_no=1,
            start_ms=1000,
            end_ms=500,
            duration_ms=500,
            person_count=0,
            has_face_visible=False,
            max_face_scale=0.0,
            max_occlusion=0.0,
            has_text_overlay=False,
            has_dialogue=False,
            dialogue_duration_seconds=0.0,
        )
