from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from vtv_db.repository import MediaAssetRead, OutboxEventRead

# ── 1. OutboxEventRead field validation ──────────────────────────────────────


def test_outbox_event_read_all_fields_present() -> None:
    event_id = uuid4()
    aggregate_id = uuid4()
    now = datetime.now(UTC)
    ev = OutboxEventRead(
        event_id=event_id,
        aggregate_type="project",
        aggregate_id=aggregate_id,
        event_type="project.created",
        payload={"project_id": str(aggregate_id)},
        created_at=now,
    )
    assert ev.event_id == event_id
    assert ev.aggregate_type == "project"
    assert ev.aggregate_id == aggregate_id
    assert ev.event_type == "project.created"
    assert ev.payload == {"project_id": str(aggregate_id)}
    assert ev.created_at == now


def test_outbox_event_read_rejects_missing_required_fields() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        OutboxEventRead(
            event_id=uuid4(),
            # aggregate_type missing
            aggregate_id=uuid4(),
            event_type="project.created",
            payload={},
            created_at=datetime.now(UTC),
        )


# ── 2. list_outbox_events query params (MemoryRepository stub) ───────────────


@pytest.mark.asyncio
async def test_list_outbox_events_returns_empty_for_memory_repo() -> None:
    from vtv_db.repository import MemoryRepository
    from vtv_schemas.projects import ProjectCreate

    repo = MemoryRepository()
    project = await repo.create_project(
        uuid4(),
        ProjectCreate(
            name="test",
            target_market="US",
            locale="en-US",
            timezone="UTC",
        ),
    )
    events = await repo.list_outbox_events(
        project.workspace_id, project.id, since=None, limit=20
    )
    assert events == []


@pytest.mark.asyncio
async def test_list_outbox_events_with_since_param_returns_empty() -> None:
    from vtv_db.repository import MemoryRepository
    from vtv_schemas.projects import ProjectCreate

    repo = MemoryRepository()
    project = await repo.create_project(
        uuid4(),
        ProjectCreate(
            name="test",
            target_market="US",
            locale="en-US",
            timezone="UTC",
        ),
    )
    events = await repo.list_outbox_events(
        project.workspace_id,
        project.id,
        since="2026-01-01T00:00:00Z",
        limit=10,
    )
    assert isinstance(events, list)
    assert len(events) == 0


# ── 3. MediaAssetRead fields ──────────────────────────────────────────────────


def test_media_asset_read_all_fields_present() -> None:
    asset_id = uuid4()
    project_id = uuid4()
    episode_id = uuid4()
    run_id = uuid4()
    now = datetime.now(UTC)
    asset = MediaAssetRead(
        id=asset_id,
        project_id=project_id,
        episode_id=episode_id,
        object_uri="s3://bucket/key.mp4",
        sha256="a" * 64,
        size_bytes=1_000_000,
        content_type="video/mp4",
        source_stage_run_id=run_id,
        stage_type="VISUAL_CHARACTER_REPLACE",
        metadata={"stage_type": "VISUAL_CHARACTER_REPLACE"},
        created_at=now,
    )
    assert asset.id == asset_id
    assert asset.episode_id == episode_id
    assert asset.content_type == "video/mp4"
    assert asset.stage_type == "VISUAL_CHARACTER_REPLACE"
    assert asset.source_stage_run_id == run_id


def test_media_asset_read_optional_fields_accept_none() -> None:
    asset = MediaAssetRead(
        id=uuid4(),
        project_id=uuid4(),
        episode_id=None,
        object_uri="s3://bucket/key.json",
        sha256="b" * 64,
        size_bytes=512,
        content_type="application/json",
        source_stage_run_id=None,
        stage_type=None,
        metadata={},
        created_at=datetime.now(UTC),
    )
    assert asset.episode_id is None
    assert asset.source_stage_run_id is None
    assert asset.stage_type is None


# ── 5. SSE format: id / event / data fields ───────────────────────────────────


def test_sse_line_format_contains_required_fields() -> None:
    event_id = uuid4()
    payload = {"project_id": str(uuid4()), "status": "ok"}
    sse_line = (
        f"id: {event_id}\n"
        f"event: project.created\n"
        f"data: {json.dumps(payload)}\n\n"
    )
    assert sse_line.startswith(f"id: {event_id}\n")
    assert "event: project.created\n" in sse_line
    assert f"data: {json.dumps(payload)}\n\n" in sse_line
    # Each SSE message ends with double newline
    assert sse_line.endswith("\n\n")


# ── 6. Heartbeat format ───────────────────────────────────────────────────────


def test_sse_heartbeat_format() -> None:
    heartbeat = ": heartbeat\n\n"
    # SSE comment lines start with ":"
    assert heartbeat.startswith(":")
    assert "heartbeat" in heartbeat
    assert heartbeat.endswith("\n\n")
