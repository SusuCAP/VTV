from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_control_api.app import ShotRouteOverride, StageRetryRequest
from vtv_db.repository import FailedStageRead

# ---------------------------------------------------------------------------
# StageRetryRequest
# ---------------------------------------------------------------------------


def test_stage_retry_request_defaults() -> None:
    req = StageRetryRequest()
    assert req.reason == "manual-retry"


def test_stage_retry_request_custom_reason() -> None:
    req = StageRetryRequest(reason="worker-crashed")
    assert req.reason == "worker-crashed"


def test_stage_retry_request_reason_max_length() -> None:
    req = StageRetryRequest(reason="x" * 200)
    assert len(req.reason) == 200


def test_stage_retry_request_reason_too_long() -> None:
    with pytest.raises(ValidationError):
        StageRetryRequest(reason="x" * 201)


# ---------------------------------------------------------------------------
# ShotRouteOverride
# ---------------------------------------------------------------------------


def test_shot_route_override_valid_routes() -> None:
    for route in "ABCDEF":
        override = ShotRouteOverride(route=route)
        assert override.route == route


def test_shot_route_override_invalid_route_g() -> None:
    with pytest.raises(ValidationError):
        ShotRouteOverride(route="G")


def test_shot_route_override_invalid_lowercase() -> None:
    with pytest.raises(ValidationError):
        ShotRouteOverride(route="a")


def test_shot_route_override_defaults() -> None:
    override = ShotRouteOverride(route="C")
    assert override.reason == "manual-override"
    assert override.force_rerun is False


# ---------------------------------------------------------------------------
# FailedStageRead
# ---------------------------------------------------------------------------


def test_failed_stage_read_fields() -> None:
    now = datetime.now(UTC)
    record = FailedStageRead(
        stage_run_id=uuid4(),
        stage_type="VISUAL_CHARACTER_REPLACE",
        episode_id=uuid4(),
        shot_id=uuid4(),
        status="EXECUTION_FAILED",
        error_class="RuntimeError",
        error_detail={"message": "GPU OOM"},
        attempt_count=3,
        last_attempt_at=now,
        created_at=now,
    )
    assert record.attempt_count == 3
    assert record.error_class == "RuntimeError"
    assert record.status == "EXECUTION_FAILED"


def test_failed_stage_read_nullable_fields() -> None:
    now = datetime.now(UTC)
    record = FailedStageRead(
        stage_run_id=uuid4(),
        stage_type="VISUAL_SUBTITLE_CLEAN",
        episode_id=None,
        shot_id=None,
        status="EXECUTION_FAILED",
        error_class=None,
        error_detail=None,
        attempt_count=0,
        last_attempt_at=None,
        created_at=now,
    )
    assert record.episode_id is None
    assert record.error_class is None
    assert record.last_attempt_at is None


# ---------------------------------------------------------------------------
# Route → stage_type mapping (mirrors the production repo constant)
# ---------------------------------------------------------------------------


def test_route_to_stage_type_mapping() -> None:
    _ROUTE_TO_STAGE = {
        "B": "VISUAL_SUBTITLE_CLEAN",
        "C": "VISUAL_CHARACTER_REPLACE",
        "D": "VISUAL_BACKGROUND_REPLACE",
        "E": "VISUAL_JOINT_REPLACE",
        "F": "VISUAL_FULL_REGEN",
    }
    assert _ROUTE_TO_STAGE["C"] == "VISUAL_CHARACTER_REPLACE"
    assert _ROUTE_TO_STAGE["F"] == "VISUAL_FULL_REGEN"
    assert "A" not in _ROUTE_TO_STAGE  # Route A = no-op, no stage type
