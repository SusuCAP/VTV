import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vtv_db.models import (
    ArtifactRelease,
    Episode,
    Job,
    MediaAsset,
    ModelRelease,
    OrphanAsset,
    OutboxEvent,
    RightsRelease,
    StageDependency,
    StageRun,
)
from vtv_db.repository import SqlAlchemyProjectRepository
from vtv_orchestrator.mock_worker import execute
from vtv_orchestrator.runner import OrchestratorLoop
from vtv_orchestrator.scheduler import Scheduler
from vtv_schemas.jobs import AssetRef, StageResult, VariantResult
from vtv_schemas.production import DubbingJobCreate, DubbingUtteranceCreate
from vtv_schemas.projects import ProjectCreate
from vtv_schemas.rights import RightsExecutionCheck, RightsReleaseCreate
from vtv_schemas.uploads import MultipartInit, UploadPart

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
    upload_id = UUID(int=200)
    sha256 = "a" * 64
    await repository.create_upload_session(
        workspace_id,
        upload_id,
        MultipartInit(
            project_id=project.id,
            filename="E01.mp4",
            content_type="video/mp4",
            size_bytes=96,
            part_size_bytes=32 * 1024 * 1024,
            sha256=sha256,
        ),
        "source/E01.mp4",
        "provider-upload-id",
    )
    completed = await repository.complete_upload(
        workspace_id,
        upload_id,
        [UploadPart(part_number=1, size_bytes=96, etag="etag")],
        sha256,
        "s3://vtv/source/E01.mp4",
        "video/mp4",
        96,
    )
    assert completed.status == "COMPLETED"
    assert completed.ingest_job_id

    job = await repository.create_analysis_job(workspace_id, project.id)

    assert job.total_stages == 7
    assert (await repository.get_project(workspace_id, project.id)).status == "ANALYZING"
    async with database() as session:
        assert await session.scalar(select(func.count()).select_from(Episode)) == 1
        assert await session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        ingest = await session.get(Job, completed.ingest_job_id)
        ingest_stage_count = await session.scalar(
            select(func.count())
            .select_from(StageRun)
            .where(StageRun.job_id == completed.ingest_job_id)
        )
        assert ingest and ingest.kind == "EPISODE_INGEST"
        assert ingest.total_stages == 8
        assert ingest_stage_count == 8
        runs = list(
            await session.scalars(
                select(StageRun).where(StageRun.job_id == job.id).order_by(StageRun.created_at)
            )
        )
        run_ids = [run.id for run in runs]
        dependency_count = await session.scalar(
            select(func.count())
            .select_from(StageDependency)
            .where(StageDependency.stage_run_id.in_(run_ids))
        )
        analysis_outbox_count = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.event_type == "analysis.requested")
        )
        stored_job = await session.get(Job, job.id)

    assert len(runs) == 7
    assert [run.status for run in runs].count("READY") == 1
    assert dependency_count == 8
    assert analysis_outbox_count == 1
    assert stored_job and stored_job.idempotency_key == "project-analysis:1"

    processed = await OrchestratorLoop(Scheduler(database), execute).run_until_idle()
    assert processed == 15
    async with database() as session:
        job_statuses = list(await session.scalars(select(Job.status).order_by(Job.created_at)))
        generated_asset_count = await session.scalar(
            select(func.count()).select_from(MediaAsset)
        )
    assert job_statuses == ["SUCCEEDED", "SUCCEEDED"]
    assert generated_asset_count == 16


async def test_rights_release_is_versioned_revocable_and_workspace_scoped(
    database: async_sessionmaker,
) -> None:
    repository = SqlAlchemyProjectRepository(database)
    workspace_id = UUID(int=501)
    project = await repository.create_project(
        workspace_id,
        ProjectCreate(name="Rights SQL", target_market="US", locale="en-US"),
    )
    actor_id = UUID(int=502)
    release = await repository.create_rights_release(
        workspace_id,
        project.id,
        RightsReleaseCreate(
            subject_type="VOICE",
            subject_id="character-1",
            allowed_operations=frozenset({"voice_clone"}),
            allowed_markets=frozenset({"US"}),
            allowed_languages=frozenset({"en-US"}),
            commercial_scope="COMMERCIAL",
            valid_from=datetime.now(UTC) - timedelta(days=1),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            evidence_uri="s3://rights/evidence.pdf",
            evidence_sha256="e" * 64,
            created_by=actor_id,
        ),
    )
    decision = await repository.check_rights_release(
        workspace_id,
        release.id,
        RightsExecutionCheck(operation="voice_clone", market="US", language="en-US"),
    )
    assert decision.allowed is True

    revoked = await repository.revoke_rights_release(
        workspace_id, release.id, actor_id, "withdrawn", 1
    )
    assert revoked.status == "REVOKED"
    async with database() as session:
        assert await session.scalar(select(func.count()).select_from(RightsRelease)) == 1


async def test_dubbing_job_persists_registry_and_rights_bound_stages(
    database: async_sessionmaker,
) -> None:
    repository = SqlAlchemyProjectRepository(database)
    workspace_id = UUID(int=601)
    project = await repository.create_project(
        workspace_id,
        ProjectCreate(name="Dubbing SQL", target_market="US", locale="en-US"),
    )
    source_asset_id = UUID(int=602)
    episode_id = UUID(int=603)
    localization_id = UUID(int=604)
    voice_id = UUID(int=605)
    model_id = UUID(int=606)
    async with database.begin() as session:
        session.add(
            MediaAsset(
                id=source_asset_id,
                workspace_id=workspace_id,
                project_id=project.id,
                object_uri="s3://bucket/source.mp4",
                sha256="f" * 64,
                size_bytes=100,
                content_type="video/mp4",
            )
        )
        session.add(
            Episode(
                id=episode_id,
                project_id=project.id,
                episode_no=1,
                source_asset_id=source_asset_id,
            )
        )
        session.add_all(
            (
                ArtifactRelease(
                    id=localization_id,
                    project_id=project.id,
                    artifact_type="LOCALIZATION_UTTERANCES",
                    version=1,
                    status="RELEASED",
                    state_version=3,
                    content_asset_id=source_asset_id,
                ),
                ArtifactRelease(
                    id=voice_id,
                    project_id=project.id,
                    artifact_type="VOICE_RELEASE",
                    version=1,
                    status="RELEASED",
                    state_version=3,
                    content_asset_id=source_asset_id,
                ),
            )
        )
        session.add(
            ModelRelease(
                id=model_id,
                workspace_id=workspace_id,
                model_key="TTS",
                release_name="voxcpm2@approved-sql",
                provider="self-hosted",
                endpoint="https://tts.example.invalid/v1/synthesize",
                license_id="license-sql",
                license_status="APPROVED",
                automation_status="ACTIVE",
                traffic_percent=100,
                model_card_uri="https://models.example.invalid/voxcpm2",
                config_json={"adapter_mode": "remote_tts"},
            )
        )
    rights = await repository.create_rights_release(
        workspace_id,
        project.id,
        RightsReleaseCreate(
            subject_type="VOICE",
            subject_id="character-1",
            allowed_operations=frozenset({"voice_clone"}),
            allowed_markets=frozenset({"US"}),
            allowed_languages=frozenset({"en-US"}),
            commercial_scope="COMMERCIAL",
            valid_from=datetime.now(UTC) - timedelta(days=1),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            evidence_uri="s3://rights/voice.pdf",
            evidence_sha256="e" * 64,
            created_by=UUID(int=607),
        ),
    )
    job = await repository.create_dubbing_job(
        workspace_id,
        project.id,
        DubbingJobCreate(
            episode_id=episode_id,
            localization_release_id=localization_id,
            utterances=(
                DubbingUtteranceCreate(
                    utterance_id="utterance-1",
                    character_id="character-1",
                    source_text="你好",
                    source_language="zh-CN",
                    target_text="Hello",
                    target_language="en-US",
                    start_seconds=0,
                    end_seconds=1.5,
                    voice_release_id=voice_id,
                    rights_release_id=rights.id,
                    seed=42,
                ),
            ),
        ),
    )

    async with database() as session:
        run = await session.scalar(select(StageRun).where(StageRun.job_id == job.id))
        event_count = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.event_type == "dubbing.requested")
        )
    assert run and run.stage_type == "TTS_GENERATE"
    assert run.model_release_id == model_id
    assert run.params["rights_state_version"] == 1
    assert run.params["tts_request"]["voice_release"]["rights"]["rights_release_id"] == str(
        rights.id
    )
    assert event_count == 1

    scheduler = Scheduler(database)
    claim = await scheduler.claim_one("tts-test-worker")
    assert claim and claim.stage_run_id == run.id
    await repository.revoke_rights_release(
        workspace_id, rights.id, UUID(int=608), "withdrawn during inference", 1
    )
    committed = await scheduler.commit_result(
        claim,
        StageResult(
            stage_run_id=claim.stage_run_id,
            stage_attempt_id=claim.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[
                VariantResult(
                    variant_no=1,
                    output_assets=[
                        AssetRef(
                            uri="s3://bucket/late.wav",
                            sha256="a" * 64,
                            media_type="audio/wav",
                            size_bytes=10,
                        )
                    ],
                )
            ],
        ),
    )
    assert committed is False
    async with database() as session:
        failed_run = await session.get(StageRun, run.id)
        orphan_count = await session.scalar(select(func.count()).select_from(OrphanAsset))
    assert failed_run and failed_run.status == "EXECUTION_FAILED"
    assert orphan_count == 1
