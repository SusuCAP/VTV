from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_schemas.cost_report import ModelCostEntry, ProjectCostReport, StageCostEntry

# ---------------------------------------------------------------------------
# StageCostEntry
# ---------------------------------------------------------------------------


def test_stage_cost_entry_valid() -> None:
    entry = StageCostEntry(
        stage_type="TTS_GENERATE",
        stage_run_count=10,
        total_cost_usd=Decimal("1.234567"),
        avg_cost_usd=Decimal("0.123457"),
        p95_latency_seconds=3.5,
    )
    assert entry.stage_type == "TTS_GENERATE"
    assert entry.stage_run_count == 10
    assert entry.p95_latency_seconds == 3.5


def test_stage_cost_entry_rejects_negative_cost() -> None:
    with pytest.raises(ValidationError):
        StageCostEntry(
            stage_type="TTS_GENERATE",
            stage_run_count=1,
            total_cost_usd=Decimal("-0.01"),
            avg_cost_usd=Decimal("0.01"),
            p95_latency_seconds=1.0,
        )


# ---------------------------------------------------------------------------
# ModelCostEntry
# ---------------------------------------------------------------------------


def test_model_cost_entry_valid() -> None:
    entry = ModelCostEntry(
        model_key="TTS",
        model_release_name="tts-v2.1",
        invocation_count=50,
        total_cost_usd=Decimal("5.000000"),
        total_gpu_seconds=120.0,
    )
    assert entry.invocation_count == 50
    assert entry.total_gpu_seconds == 120.0


# ---------------------------------------------------------------------------
# ProjectCostReport
# ---------------------------------------------------------------------------


def _make_report(**kwargs: object) -> ProjectCostReport:
    now = datetime.now(UTC)
    defaults: dict = dict(
        project_id=uuid4(),
        workspace_id=uuid4(),
        report_generated_at=now,
        total_cost_usd=Decimal("10.000000"),
        episode_count=5,
        shot_count=40,
        cost_per_episode_usd=Decimal("2.000000"),
        cost_per_shot_usd=Decimal("0.250000"),
    )
    defaults.update(kwargs)
    return ProjectCostReport(**defaults)


def test_project_cost_report_valid() -> None:
    report = _make_report()
    assert report.currency == "USD"
    assert report.by_stage == []
    assert report.by_model == []
    assert report.budget_utilization_pct is None


def test_project_cost_report_decimal_precision() -> None:
    report = _make_report(total_cost_usd=Decimal("0.123456"))
    assert report.total_cost_usd == Decimal("0.123456")


def test_project_cost_report_budget_utilization_none_when_no_budget() -> None:
    report = _make_report(budget_usd=None, budget_utilization_pct=None)
    assert report.budget_usd is None
    assert report.budget_utilization_pct is None


def test_project_cost_report_budget_utilization_present() -> None:
    report = _make_report(
        budget_usd=Decimal("100.000000"),
        budget_utilization_pct=10.0,
    )
    assert report.budget_utilization_pct == 10.0


def test_project_cost_report_episode_count_zero_allowed() -> None:
    # episode_count=0 must not crash; cost_per_episode_usd can be 0
    report = _make_report(
        episode_count=0,
        shot_count=0,
        cost_per_episode_usd=Decimal("0.000000"),
        cost_per_shot_usd=Decimal("0.000000"),
    )
    assert report.episode_count == 0
    assert report.cost_per_episode_usd == Decimal("0.000000")


def test_project_cost_report_rejects_negative_total() -> None:
    with pytest.raises(ValidationError):
        _make_report(total_cost_usd=Decimal("-1.000000"))


def test_project_cost_report_invalid_currency() -> None:
    with pytest.raises(ValidationError):
        _make_report(currency="usd")
