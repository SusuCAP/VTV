from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_schemas.enums import ProjectStatus
from vtv_schemas.health import HealthCheckResult, HealthReport, SystemMetrics
from vtv_schemas.projects import ProjectRead

# ---------------------------------------------------------------------------
# ProjectRead archived fields
# ---------------------------------------------------------------------------


def _make_project(**kwargs) -> ProjectRead:
    now = datetime.now(UTC)
    defaults = dict(
        id=uuid4(),
        workspace_id=uuid4(),
        name="Test Project",
        target_market="US",
        locale="en-US",
        timezone="UTC",
        quality_profile="research_best",
        output={"aspect_ratio": "9:16", "width": 1080, "height": 1920, "fps": 24,
                "video_codec": "h264", "audio_codec": "aac", "subtitle_formats": ["srt"]},
        budget={"currency": "USD", "warning_at": "280.00", "hard_limit": "350.00"},
        status=ProjectStatus.DRAFT,
        state_version=1,
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    return ProjectRead(**defaults)


def test_project_read_has_archived_at_field() -> None:
    project = _make_project()
    assert project.archived_at is None


def test_project_read_archived_at_can_be_set() -> None:
    now = datetime.now(UTC)
    project = _make_project(archived_at=now, archive_reason="no longer needed")
    assert project.archived_at == now
    assert project.archive_reason == "no longer needed"


def test_archive_reason_length_validation() -> None:
    # exactly 500 chars — OK
    project = _make_project(archive_reason="x" * 500)
    assert len(project.archive_reason) == 500


def test_archive_reason_length_validation_too_long() -> None:
    with pytest.raises(ValidationError):
        _make_project(archive_reason="x" * 501)


# ---------------------------------------------------------------------------
# HealthCheckResult
# ---------------------------------------------------------------------------


def test_health_check_result_ok() -> None:
    result = HealthCheckResult(status="ok")
    assert result.status == "ok"
    assert result.message == ""
    assert result.latency_ms is None


def test_health_check_result_error_with_message() -> None:
    result = HealthCheckResult(status="error", message="connection refused", latency_ms=42.5)
    assert result.status == "error"
    assert result.latency_ms == 42.5


# ---------------------------------------------------------------------------
# HealthReport status propagation
# ---------------------------------------------------------------------------


def test_health_report_ok_status() -> None:
    report = HealthReport(
        status="ok",
        checks={
            "database": HealthCheckResult(status="ok"),
            "storage": HealthCheckResult(status="ok"),
        },
        timestamp=datetime.now(UTC),
    )
    assert report.status == "ok"


def test_health_report_degraded_status() -> None:
    report = HealthReport(
        status="degraded",
        checks={
            "database": HealthCheckResult(status="ok"),
            "modal": HealthCheckResult(status="warn", message="not importable"),
        },
        timestamp=datetime.now(UTC),
    )
    assert report.status == "degraded"


def test_health_report_error_status() -> None:
    report = HealthReport(
        status="error",
        checks={"database": HealthCheckResult(status="error", message="timeout")},
        timestamp=datetime.now(UTC),
    )
    assert report.status == "error"


# ---------------------------------------------------------------------------
# SystemMetrics fields all non-negative
# ---------------------------------------------------------------------------


def test_system_metrics_all_non_negative() -> None:
    metrics = SystemMetrics(
        active_projects=5,
        archived_projects=2,
        total_episodes=10,
        total_stage_runs=100,
        pending_stage_runs=3,
        running_stage_runs=2,
        failed_stage_runs=1,
        total_deliveries=8,
        approved_deliveries=6,
        orphan_asset_count=0,
        generated_at=datetime.now(UTC),
    )
    assert metrics.active_projects >= 0
    assert metrics.archived_projects >= 0
    assert metrics.total_stage_runs >= 0


def test_system_metrics_rejects_negative_counts() -> None:
    with pytest.raises(ValidationError):
        SystemMetrics(
            active_projects=-1,
            archived_projects=0,
            total_episodes=0,
            total_stage_runs=0,
            pending_stage_runs=0,
            running_stage_runs=0,
            failed_stage_runs=0,
            total_deliveries=0,
            approved_deliveries=0,
            orphan_asset_count=0,
            generated_at=datetime.now(UTC),
        )
