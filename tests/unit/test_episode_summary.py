from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from vtv_db.repository import EpisodeSummary


def _make_summary(**kwargs) -> EpisodeSummary:
    defaults = dict(
        episode_id=uuid4(),
        project_id=uuid4(),
        episode_no=1,
        title="Episode 1",
        source_asset_id=uuid4(),
        processing_status="COMPLETED",
        duration_seconds=1200.5,
        shot_count=42,
        dialogue_line_count=120,
        character_count=5,
        analysis_complete=True,
        production_complete=True,
        delivery_count=1,
        latest_delivery_status="APPROVED",
        total_cost_usd=Decimal("3.14"),
        generated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return EpisodeSummary(**defaults)


def test_episode_summary_all_fields() -> None:
    ep_id = uuid4()
    proj_id = uuid4()
    asset_id = uuid4()
    now = datetime.now(UTC)
    summary = EpisodeSummary(
        episode_id=ep_id,
        project_id=proj_id,
        episode_no=3,
        title="Pilot",
        source_asset_id=asset_id,
        processing_status="COMPLETED",
        duration_seconds=1800.0,
        shot_count=60,
        dialogue_line_count=200,
        character_count=8,
        analysis_complete=True,
        production_complete=True,
        delivery_count=2,
        latest_delivery_status="APPROVED",
        total_cost_usd=Decimal("12.50"),
        generated_at=now,
    )
    assert summary.episode_id == ep_id
    assert summary.project_id == proj_id
    assert summary.episode_no == 3
    assert summary.title == "Pilot"
    assert summary.source_asset_id == asset_id
    assert summary.processing_status == "COMPLETED"
    assert summary.duration_seconds == 1800.0
    assert summary.shot_count == 60
    assert summary.dialogue_line_count == 200
    assert summary.character_count == 8
    assert summary.analysis_complete is True
    assert summary.production_complete is True
    assert summary.delivery_count == 2
    assert summary.latest_delivery_status == "APPROVED"
    assert summary.total_cost_usd == Decimal("12.50")
    assert summary.generated_at == now


def test_episode_summary_duration_seconds_none_when_no_probe() -> None:
    summary = _make_summary(duration_seconds=None)
    assert summary.duration_seconds is None


def test_episode_summary_analysis_complete_logic() -> None:
    complete = _make_summary(analysis_complete=True)
    assert complete.analysis_complete is True

    incomplete = _make_summary(analysis_complete=False)
    assert incomplete.analysis_complete is False


def test_episode_summary_production_complete_logic() -> None:
    done = _make_summary(production_complete=True)
    assert done.production_complete is True

    not_done = _make_summary(production_complete=False)
    assert not_done.production_complete is False


def test_episode_summary_decimal_cost_non_negative() -> None:
    summary = _make_summary(total_cost_usd=Decimal("0"))
    assert summary.total_cost_usd >= Decimal("0")

    summary2 = _make_summary(total_cost_usd=Decimal("999.999999"))
    assert summary2.total_cost_usd >= Decimal("0")
