from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from vtv_db.repository import MediaAssetRead

# ── 1. MediaAssetRead all fields ──────────────────────────────────────────────


def test_media_asset_read_validates_all_required_fields() -> None:
    asset_id = uuid4()
    project_id = uuid4()
    episode_id = uuid4()
    stage_run_id = uuid4()
    now = datetime.now(UTC)
    asset = MediaAssetRead(
        id=asset_id,
        project_id=project_id,
        episode_id=episode_id,
        object_uri="s3://vtv/assets/master.mp4",
        sha256="c" * 64,
        size_bytes=50_000_000,
        content_type="video/mp4",
        source_stage_run_id=stage_run_id,
        stage_type="ASSEMBLE_EPISODE",
        metadata={"stage_type": "ASSEMBLE_EPISODE", "episode_id": str(episode_id)},
        created_at=now,
    )
    assert asset.id == asset_id
    assert asset.project_id == project_id
    assert asset.episode_id == episode_id
    assert asset.object_uri == "s3://vtv/assets/master.mp4"
    assert asset.sha256 == "c" * 64
    assert asset.size_bytes == 50_000_000
    assert asset.content_type == "video/mp4"
    assert asset.source_stage_run_id == stage_run_id
    assert asset.stage_type == "ASSEMBLE_EPISODE"
    assert asset.metadata["episode_id"] == str(episode_id)
    assert asset.created_at == now


# ── 2. search_assets pagination params (MemoryRepository stub) ───────────────


@pytest.mark.asyncio
async def test_search_assets_returns_empty_list_from_memory_repo() -> None:
    from vtv_db.repository import MemoryRepository
    from vtv_schemas.projects import ProjectCreate

    repo = MemoryRepository()
    project = await repo.create_project(
        uuid4(),
        ProjectCreate(
            name="asset-search-test",
            target_market="GB",
            locale="en-GB",
            timezone="UTC",
        ),
    )
    results = await repo.search_assets(
        project.workspace_id,
        project.id,
        limit=50,
        offset=0,
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_assets_pagination_params_are_forwarded() -> None:
    """Verify that limit and offset are accepted without error (stub returns [])."""
    from vtv_db.repository import MemoryRepository
    from vtv_schemas.projects import ProjectCreate

    repo = MemoryRepository()
    project = await repo.create_project(
        uuid4(),
        ProjectCreate(
            name="pagination-test",
            target_market="US",
            locale="en-US",
            timezone="UTC",
        ),
    )
    # Test that non-default pagination values are accepted
    results = await repo.search_assets(
        project.workspace_id,
        project.id,
        limit=10,
        offset=100,
    )
    assert isinstance(results, list)


# ── 3. content_type filter format ────────────────────────────────────────────


def test_content_type_field_accepts_mime_format() -> None:
    """MediaAssetRead content_type accepts standard MIME type strings."""
    for mime in ("video/mp4", "audio/wav", "application/json", "image/png"):
        asset = MediaAssetRead(
            id=uuid4(),
            project_id=uuid4(),
            episode_id=None,
            object_uri=f"s3://bucket/{mime.replace('/', '_')}",
            sha256="d" * 64,
            size_bytes=100,
            content_type=mime,
            source_stage_run_id=None,
            stage_type=None,
            metadata={},
            created_at=datetime.now(UTC),
        )
        assert asset.content_type == mime


# ── 4. stage_type presence in metadata ───────────────────────────────────────


def test_stage_type_reflected_in_metadata_and_top_level_field() -> None:
    """stage_type on MediaAssetRead should match metadata['stage_type']."""
    stage = "VISUAL_CHARACTER_REPLACE"
    asset = MediaAssetRead(
        id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        object_uri="s3://bucket/frame.mp4",
        sha256="e" * 64,
        size_bytes=200,
        content_type="video/mp4",
        source_stage_run_id=uuid4(),
        stage_type=stage,
        metadata={"stage_type": stage, "route": "C"},
        created_at=datetime.now(UTC),
    )
    assert asset.stage_type == stage
    assert asset.metadata.get("stage_type") == stage
