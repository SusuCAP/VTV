from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_schemas.jobs import JobSummary
from vtv_schemas.project_stats import EpisodeJobSummary


def _make_summary(**kwargs) -> EpisodeJobSummary:
    defaults = dict(
        episode_id=uuid4(),
        jobs=[],
        pending_count=0,
        running_count=0,
        completed_count=0,
        failed_count=0,
    )
    defaults.update(kwargs)
    return EpisodeJobSummary(**defaults)


def _make_job_summary(**kwargs) -> JobSummary:
    now = datetime.now(UTC)
    defaults = dict(
        job_id=uuid4(),
        kind="PROJECT_ANALYSIS",
        status="QUEUED",
        total_stages=10,
        completed_stages=0,
        failed_stages=0,
        progress_percent=0.0,
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    return JobSummary(**defaults)


def test_episode_job_summary_fields() -> None:
    episode_id = uuid4()
    summary = _make_summary(episode_id=episode_id)
    assert summary.episode_id == episode_id
    assert summary.jobs == []
    assert summary.pending_count == 0


def test_counts_logic_with_jobs() -> None:
    jobs = [
        _make_job_summary(status="QUEUED"),
        _make_job_summary(status="RUNNING"),
        _make_job_summary(status="COMPLETED"),
        _make_job_summary(status="FAILED"),
    ]
    summary = _make_summary(
        jobs=jobs,
        pending_count=1,
        running_count=1,
        completed_count=1,
        failed_count=1,
    )
    total = (
        summary.pending_count
        + summary.running_count
        + summary.completed_count
        + summary.failed_count
    )
    assert total == len(summary.jobs)


def test_empty_jobs_list() -> None:
    summary = _make_summary()
    assert summary.jobs == []
    assert summary.pending_count == 0
    assert summary.running_count == 0
    assert summary.completed_count == 0
    assert summary.failed_count == 0


def test_negative_count_raises() -> None:
    with pytest.raises(ValidationError):
        _make_summary(pending_count=-1)


def test_multiple_jobs() -> None:
    jobs = [_make_job_summary(kind=f"JOB_{i}") for i in range(3)]
    summary = _make_summary(jobs=jobs, completed_count=3)
    assert len(summary.jobs) == 3
    assert summary.completed_count == 3
