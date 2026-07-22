import os
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vtv_db.models import Job, OutboxEvent, StageDependency, StageRun
from vtv_db.repository import SqlAlchemyProjectRepository
from vtv_schemas.projects import ProjectCreate

DATABASE_URL = os.getenv("VTV_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="VTV_TEST_DATABASE_URL is not set")


@pytest.fixture
async def database() -> async_sessionmaker:
    assert DATABASE_URL
    asyncpg_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(asyncpg_url)
    try:
        await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        for migration in sorted(Path("migrations").glob("*.sql")):
            await connection.execute(migration.read_text())
    finally:
        await connection.close()
    engine = create_async_engine(DATABASE_URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_project_and_analysis_dag_are_committed_atomically(
    database: async_sessionmaker,
) -> None:
    ids = iter(UUID(int=value) for value in range(10, 100))
    repository = SqlAlchemyProjectRepository(database, id_factory=lambda: next(ids))
    workspace_id = UUID(int=1)
    project = await repository.create_project(
        workspace_id,
        ProjectCreate(name="Drama-US-001", target_market="US", locale="en-US"),
    )
    job = await repository.create_analysis_job(workspace_id, project.id)

    assert job.total_stages == 6
    assert (await repository.get_project(workspace_id, project.id)).status == "ANALYZING"
    async with database() as session:
        runs = list(
            await session.scalars(
                select(StageRun).where(StageRun.job_id == job.id).order_by(StageRun.created_at)
            )
        )
        dependency_count = await session.scalar(select(func.count()).select_from(StageDependency))
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxEvent))
        stored_job = await session.get(Job, job.id)

    assert len(runs) == 6
    assert [run.status for run in runs].count("READY") == 1
    assert dependency_count == 6
    assert outbox_count == 2
    assert stored_job and stored_job.idempotency_key == "project-analysis:1"
