"""Unit tests for delivery package contracts and job tracking schemas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from vtv_delivery.contracts import DeliveryPackage, DeliveryPackageAsset, DeliveryRevoke
from vtv_schemas.jobs import JobProgress, JobSummary

# ---------------------------------------------------------------------------
# DeliveryPackageAsset
# ---------------------------------------------------------------------------


def test_delivery_package_asset_valid() -> None:
    asset = DeliveryPackageAsset(
        role="MASTER_VIDEO",
        object_uri="s3://bucket/master.mp4",
        sha256="a" * 64,
        size_bytes=1024,
        content_type="video/mp4",
        download_url="s3://bucket/master.mp4",
    )
    assert asset.role == "MASTER_VIDEO"
    assert asset.download_url == "s3://bucket/master.mp4"


def test_delivery_package_asset_fields_present() -> None:
    asset = DeliveryPackageAsset(
        role="SUBTITLE_SRT",
        object_uri="s3://bucket/sub.srt",
        sha256="b" * 64,
        size_bytes=512,
        content_type="application/x-subrip",
        download_url="s3://bucket/sub.srt",
    )
    assert asset.role == "SUBTITLE_SRT"
    assert asset.size_bytes == 512


# ---------------------------------------------------------------------------
# DeliveryPackage
# ---------------------------------------------------------------------------


def _make_asset(role: str = "MASTER_VIDEO") -> DeliveryPackageAsset:
    return DeliveryPackageAsset(
        role=role,
        object_uri=f"s3://bucket/{role.lower()}.bin",
        sha256="c" * 64,
        size_bytes=100,
        content_type="application/octet-stream",
        download_url=f"s3://bucket/{role.lower()}.bin",
    )


def test_delivery_package_basic() -> None:
    delivery_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    pkg = DeliveryPackage(
        delivery_id=delivery_id,
        manifest_fingerprint="d" * 64,
        assets=[_make_asset("MASTER_VIDEO"), _make_asset("SUBTITLE_SRT")],
        expires_at=expires_at,
    )
    assert pkg.delivery_id == delivery_id
    assert len(pkg.assets) == 2
    assert pkg.expires_at == expires_at


def test_delivery_package_empty_assets_allowed() -> None:
    pkg = DeliveryPackage(
        delivery_id=uuid4(),
        manifest_fingerprint="e" * 64,
        assets=[],
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    assert pkg.assets == []


# ---------------------------------------------------------------------------
# DeliveryRevoke
# ---------------------------------------------------------------------------


def test_delivery_revoke_valid() -> None:
    revoke = DeliveryRevoke(reason="Content policy violation", actor_id="admin@example.com")
    assert revoke.reason == "Content policy violation"
    assert revoke.actor_id == "admin@example.com"


def test_delivery_revoke_reason_min_length() -> None:
    with pytest.raises(ValueError):
        DeliveryRevoke(reason="", actor_id="admin@example.com")


def test_delivery_revoke_actor_id_min_length() -> None:
    with pytest.raises(ValueError):
        DeliveryRevoke(reason="Valid reason", actor_id="")


# ---------------------------------------------------------------------------
# JobSummary
# ---------------------------------------------------------------------------


def test_job_summary_progress_percent_full() -> None:
    now = datetime.now(UTC)
    summary = JobSummary(
        job_id=uuid4(),
        kind="PROJECT_ANALYSIS",
        status="COMPLETED",
        total_stages=10,
        completed_stages=10,
        failed_stages=0,
        progress_percent=100.0,
        created_at=now,
        updated_at=now,
    )
    assert summary.progress_percent == 100.0
    assert summary.status == "COMPLETED"


def test_job_summary_progress_percent_partial() -> None:
    now = datetime.now(UTC)
    summary = JobSummary(
        job_id=uuid4(),
        kind="VISUAL_PRODUCTION",
        status="RUNNING",
        total_stages=20,
        completed_stages=5,
        failed_stages=1,
        progress_percent=25.0,
        created_at=now,
        updated_at=now,
    )
    assert summary.progress_percent == 25.0
    assert summary.failed_stages == 1


def test_job_summary_zero_total_stages() -> None:
    now = datetime.now(UTC)
    summary = JobSummary(
        job_id=uuid4(),
        kind="EPISODE_INGEST",
        status="QUEUED",
        total_stages=0,
        completed_stages=0,
        failed_stages=0,
        progress_percent=0.0,
        created_at=now,
        updated_at=now,
    )
    assert summary.progress_percent == 0.0


# ---------------------------------------------------------------------------
# JobProgress
# ---------------------------------------------------------------------------


def test_job_progress_fields() -> None:
    job_id = uuid4()
    progress = JobProgress(
        job_id=job_id,
        status="RUNNING",
        total_stages=8,
        completed_stages=4,
        failed_stages=0,
        running_stages=1,
        pending_stages=3,
        progress_percent=50.0,
        estimated_seconds_remaining=None,
        recent_stage_completions=[
            {"stage_type": "AUDIO_ANALYSIS", "completed_at": "2026-07-22T10:00:00+00:00"}
        ],
    )
    assert progress.job_id == job_id
    assert progress.running_stages == 1
    assert progress.pending_stages == 3
    assert len(progress.recent_stage_completions) == 1
    assert progress.estimated_seconds_remaining is None


def test_job_progress_estimated_seconds_remaining_present() -> None:
    progress = JobProgress(
        job_id=uuid4(),
        status="RUNNING",
        total_stages=10,
        completed_stages=5,
        failed_stages=0,
        running_stages=2,
        pending_stages=3,
        progress_percent=50.0,
        estimated_seconds_remaining=120.5,
        recent_stage_completions=[],
    )
    assert progress.estimated_seconds_remaining == 120.5
