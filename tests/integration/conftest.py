"""Shared helpers for integration tests that need real DB rows."""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4


def _db_url() -> str:
    url = os.environ.get("VTV_DATABASE_URL", "postgresql+asyncpg://vtv:vtv@localhost:5432/vtv")
    # asyncpg.connect needs plain postgresql:// (no +asyncpg driver tag)
    return url.replace("+asyncpg", "")


async def _insert_media_asset(workspace_id: str, project_id: str) -> str:
    import asyncpg  # type: ignore[import-untyped]

    conn = await asyncpg.connect(_db_url())
    try:
        asset_id = str(uuid4())
        sha256 = uuid4().hex + uuid4().hex  # 64 hex chars, unique per call
        await conn.execute(
            """
            INSERT INTO media_assets
                (id, workspace_id, project_id, object_uri,
                 sha256, size_bytes, content_type, metadata)
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, 100, 'application/json', '{}')
            """,
            asset_id,
            workspace_id,
            project_id,
            f"file://test-asset-{asset_id}.json",
            sha256,
        )
        return asset_id
    finally:
        await conn.close()


def insert_test_media_asset(workspace_id: str, project_id: str) -> str:
    """Insert a minimal media_asset row and return its UUID string.

    Uses asyncpg directly so it works from synchronous test code without
    going through the FastAPI test client.
    """
    return asyncio.run(_insert_media_asset(workspace_id, project_id))
