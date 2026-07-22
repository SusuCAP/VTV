"""Unit tests for ProduceRequest schema validation."""

from decimal import Decimal

import pytest
from pydantic import ValidationError
from vtv_schemas.jobs import ProduceRequest


def test_produce_request_default_values():
    """ProduceRequest defaults: include_routes empty, ratio 0.12, no budget limits."""
    req = ProduceRequest(expected_project_state_version=1)

    assert req.expected_project_state_version == 1
    assert req.include_routes == ()
    assert req.max_full_regen_ratio == 0.12
    assert req.budget_usd_limit is None
    assert req.budget_warning_at_usd is None
    assert req.shot_route_overrides == {}


def test_produce_request_include_routes_filtering():
    """include_routes stores only the provided route values."""
    req = ProduceRequest(
        expected_project_state_version=2,
        include_routes=("B", "C"),
    )

    assert set(req.include_routes) == {"B", "C"}
    assert "D" not in req.include_routes
    assert "F" not in req.include_routes


def test_produce_request_budget_constraints():
    """Budget fields accept valid Decimal values and reject negative amounts."""
    req = ProduceRequest(
        expected_project_state_version=1,
        budget_usd_limit=Decimal("50.00"),
        budget_warning_at_usd=Decimal("40.00"),
    )

    assert req.budget_usd_limit == Decimal("50.00")
    assert req.budget_warning_at_usd == Decimal("40.00")

    with pytest.raises(ValidationError):
        ProduceRequest(
            expected_project_state_version=1,
            budget_usd_limit=Decimal("-1.00"),
        )


def test_produce_request_shot_route_overrides():
    """shot_route_overrides maps shot ID strings to route values."""
    shot_id = "550e8400-e29b-41d4-a716-446655440000"
    req = ProduceRequest(
        expected_project_state_version=1,
        shot_route_overrides={shot_id: "F"},
    )

    assert req.shot_route_overrides[shot_id] == "F"


def test_produce_request_max_full_regen_ratio_boundary():
    """max_full_regen_ratio must be in [0, 1]; values outside are rejected."""
    req_zero = ProduceRequest(expected_project_state_version=1, max_full_regen_ratio=0.0)
    assert req_zero.max_full_regen_ratio == 0.0

    req_one = ProduceRequest(expected_project_state_version=1, max_full_regen_ratio=1.0)
    assert req_one.max_full_regen_ratio == 1.0

    with pytest.raises(ValidationError):
        ProduceRequest(expected_project_state_version=1, max_full_regen_ratio=-0.01)

    with pytest.raises(ValidationError):
        ProduceRequest(expected_project_state_version=1, max_full_regen_ratio=1.01)
