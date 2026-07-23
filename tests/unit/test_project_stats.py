from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_schemas.project_stats import ProjectStats


def _make_stats(**kwargs) -> ProjectStats:
    defaults = dict(
        project_id=uuid4(),
        episodes=0,
        total_shots=0,
        total_stage_runs=0,
        completed_stage_runs=0,
        failed_stage_runs=0,
        total_deliveries=0,
        approved_deliveries=0,
        total_cost_usd=Decimal("0.000000"),
        analysis_complete_episodes=0,
        production_complete_episodes=0,
        generated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return ProjectStats(**defaults)


def test_project_stats_field_validation() -> None:
    stats = _make_stats(episodes=3, total_shots=30, total_stage_runs=90)
    assert stats.episodes == 3
    assert stats.total_shots == 30
    assert stats.total_stage_runs == 90


def test_all_counts_non_negative() -> None:
    stats = _make_stats(
        episodes=0,
        total_shots=0,
        total_stage_runs=0,
        completed_stage_runs=0,
        failed_stage_runs=0,
        total_deliveries=0,
        approved_deliveries=0,
        analysis_complete_episodes=0,
        production_complete_episodes=0,
    )
    assert stats.episodes >= 0
    assert stats.total_shots >= 0
    assert stats.total_stage_runs >= 0
    assert stats.completed_stage_runs >= 0
    assert stats.failed_stage_runs >= 0
    assert stats.total_deliveries >= 0
    assert stats.approved_deliveries >= 0


def test_negative_count_raises() -> None:
    with pytest.raises(ValidationError):
        _make_stats(episodes=-1)


def test_cost_usd_precision() -> None:
    stats = _make_stats(total_cost_usd=Decimal("1.234567"))
    assert stats.total_cost_usd == Decimal("1.234567")
    # decimal_places=6 is enforced
    with pytest.raises(ValidationError):
        _make_stats(total_cost_usd=Decimal("1.2345678"))


def test_generated_at_is_recent() -> None:
    now = datetime.now(UTC)
    stats = _make_stats(generated_at=now)
    assert abs((stats.generated_at - now).total_seconds()) < 1


def test_analysis_complete_logic() -> None:
    stats = _make_stats(episodes=5, analysis_complete_episodes=3)
    assert stats.analysis_complete_episodes <= stats.episodes


def test_production_complete_logic() -> None:
    stats = _make_stats(episodes=5, production_complete_episodes=2)
    assert stats.production_complete_episodes <= stats.episodes
