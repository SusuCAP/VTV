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
    CandidateGroup,
    Episode,
    Job,
    MediaAsset,
    ModelRelease,
    OrphanAsset,
    OutboxEvent,
    RenderVariant,
    RightsRelease,
    Shot,
    StageDependency,
    StageRun,
)
from vtv_db.repository import SqlAlchemyProjectRepository
from vtv_orchestrator.mock_worker import execute
from vtv_orchestrator.runner import OrchestratorLoop
from vtv_orchestrator.scheduler import Scheduler
from vtv_schemas.assembly import (
    AdoptedDialogueSelection,
    AdoptedPictureSelection,
    AssemblySubtitleCue,
    EpisodeAssemblyJobCreate,
    StemSelection,
)
from vtv_schemas.candidates import CandidateAdopt, CandidateQcCreate, QcMetricCreate
from vtv_schemas.jobs import AssetRef, StageResult, VariantResult
from vtv_schemas.production import (
    DubbingJobCreate,
    DubbingUtteranceCreate,
    LipSyncJobCreate,
    LipSyncShotCreate,
)
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
            allowed_operations=frozenset({"voice_clone", "lipsync"}),
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
            allowed_operations=frozenset({"voice_clone", "lipsync"}),
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
                DubbingUtteranceCreate(
                    utterance_id="utterance-2",
                    character_id="character-1",
                    source_text="再见",
                    source_language="zh-CN",
                    target_text="Goodbye",
                    target_language="en-US",
                    start_seconds=2,
                    end_seconds=3.5,
                    voice_release_id=voice_id,
                    rights_release_id=rights.id,
                    seed=84,
                ),
            ),
        ),
    )

    async with database() as session:
        runs = list(await session.scalars(select(StageRun).where(StageRun.job_id == job.id)))
        event_count = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.event_type == "dubbing.requested")
        )
    assert len(runs) == 2
    assert all(run.stage_type == "TTS_GENERATE" for run in runs)
    assert all(run.model_release_id == model_id for run in runs)
    assert all(run.params["rights_state_version"] == 1 for run in runs)
    assert all(
        run.params["tts_request"]["voice_release"]["rights"]["rights_release_id"]
        == str(rights.id)
        for run in runs
    )
    assert event_count == 1

    scheduler = Scheduler(database)
    first_claim = await scheduler.claim_one("tts-test-worker")
    assert first_claim
    first_committed = await scheduler.commit_result(
        first_claim,
        StageResult(
            stage_run_id=first_claim.stage_run_id,
            stage_attempt_id=first_claim.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[
                VariantResult(
                    variant_no=index,
                    seed=40 + index,
                    output_assets=[
                        AssetRef(
                            uri=f"s3://bucket/candidate-{index}.wav",
                            sha256=str(index) * 64,
                            media_type="audio/wav",
                            size_bytes=10,
                        )
                    ],
                )
                for index in (1, 2)
            ],
        ),
    )
    assert first_committed is True
    await scheduler.finalize_stage(first_claim)
    groups = await repository.list_candidate_groups(workspace_id, project.id, job.id)
    completed_group = next(item for item in groups if item.variants)
    passed = await repository.submit_candidate_qc(
        workspace_id,
        completed_group.variants[0].id,
        CandidateQcCreate(
            metrics=tuple(
                QcMetricCreate(
                    metric_name=name,
                    metric_version="metric@1",
                    evaluator_release="evaluator@1",
                    score=0.95,
                    verdict="PASS",
                )
                for name in (
                    "tts_intelligibility",
                    "speaker_similarity",
                    "emotion_fidelity",
                    "duration_fit",
                    "audio_artifact_control",
                )
            )
        ),
    )
    adopted = await repository.adopt_candidate(
        workspace_id,
        completed_group.id,
        CandidateAdopt(
            variant_id=passed.id,
            expected_state_version=1,
            actor_id=UUID(int=609),
        ),
    )
    assert adopted.adopted_variant_id == passed.id

    shot_id = UUID(int=610)
    shot_asset_id = UUID(int=611)
    lipsync_model_id = UUID(int=612)
    async with database.begin() as session:
        session.add(
            Shot(
                id=shot_id,
                episode_id=episode_id,
                shot_no=1,
                start_ms=0,
                end_ms=1500,
            )
        )
        session.add(
            MediaAsset(
                id=shot_asset_id,
                workspace_id=workspace_id,
                project_id=project.id,
                object_uri="s3://bucket/shot-1.mp4",
                sha256="9" * 64,
                size_bytes=20,
                content_type="video/mp4",
                metadata_json={"duration_seconds": 1.5, "shot_id": str(shot_id)},
            )
        )
        session.add(
            ModelRelease(
                id=lipsync_model_id,
                workspace_id=workspace_id,
                model_key="LIPSYNC_L2",
                release_name="latentsync@1.6-approved-sql",
                provider="self-hosted",
                endpoint="https://lipsync.example.invalid/v1/render",
                license_id="lipsync-license-sql",
                license_status="APPROVED",
                automation_status="ACTIVE",
                traffic_percent=100,
                model_card_uri="https://models.example.invalid/latentsync",
                config_json={"adapter_mode": "remote_lipsync"},
            )
        )
    lipsync_job = await repository.create_lipsync_job(
        workspace_id,
        project.id,
        LipSyncJobCreate(
            episode_id=episode_id,
            shots=(
                LipSyncShotCreate(
                    shot_id=shot_id,
                    source_video_asset_id=shot_asset_id,
                    adopted_tts_variant_id=passed.id,
                    mouth_visible=True,
                    face_scale=0.3,
                    occlusion=0.1,
                    body_visible=False,
                    dialogue_duration_seconds=1.5,
                    seed=100,
                    candidate_count=2,
                ),
            ),
        ),
    )
    async with database.begin() as session:
        lipsync_run = await session.scalar(
            select(StageRun).where(StageRun.job_id == lipsync_job.id)
        )
        assert lipsync_run
        assert lipsync_run.params["lipsync_request"]["decision"]["level"] == "L2_PRESERVE_SOURCE"
        assert lipsync_run.params["input_asset_ids"] == [
            str(shot_asset_id),
            str(passed.output_asset_id),
        ]
        assert lipsync_run.model_release_id == lipsync_model_id
        lipsync_run.priority = 10

    lipsync_claim = await scheduler.claim_one("lipsync-test-worker")
    assert lipsync_claim and lipsync_claim.stage_type == "LIPSYNC_GENERATE"
    lipsync_stage_job = await scheduler.build_job(lipsync_claim)
    assert {item.sha256 for item in lipsync_stage_job.input_assets} == {
        "9" * 64,
        "1" * 64,
    }
    assert len(lipsync_stage_job.input_assets) == 2
    assert await scheduler.commit_result(
        lipsync_claim,
        StageResult(
            stage_run_id=lipsync_claim.stage_run_id,
            stage_attempt_id=lipsync_claim.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[
                VariantResult(
                    variant_no=1,
                    seed=100,
                    output_assets=[
                        AssetRef(
                            uri="s3://bucket/lipsync-1.mp4",
                            sha256="8" * 64,
                            media_type="video/mp4",
                            size_bytes=20,
                        )
                    ],
                )
            ],
        ),
    )
    await scheduler.finalize_stage(lipsync_claim)

    claim = await scheduler.claim_one("tts-test-worker")
    assert claim and claim.stage_run_id != first_claim.stage_run_id
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
        failed_run = await session.get(StageRun, claim.stage_run_id)
        orphan_count = await session.scalar(select(func.count()).select_from(OrphanAsset))
        variant_count = await session.scalar(select(func.count()).select_from(RenderVariant))
    assert failed_run and failed_run.status == "EXECUTION_FAILED"
    assert orphan_count == 1
    assert variant_count == 2


async def test_episode_assembly_job_persists_authoritative_four_stage_dag(
    database: async_sessionmaker,
) -> None:
    repository = SqlAlchemyProjectRepository(database)
    workspace_id = UUID(int=701)
    project = await repository.create_project(
        workspace_id,
        ProjectCreate(name="Assembly SQL", target_market="US", locale="en-US"),
    )
    source_id, episode_id, shot_id = UUID(int=702), UUID(int=703), UUID(int=704)
    picture_asset_id, dialogue_asset_id, stem_asset_id = (
        UUID(int=705),
        UUID(int=706),
        UUID(int=707),
    )
    picture_group_id, dialogue_group_id = UUID(int=708), UUID(int=709)
    picture_run_id, dialogue_run_id = UUID(int=710), UUID(int=711)
    picture_variant_id, dialogue_variant_id = UUID(int=712), UUID(int=713)
    async with database.begin() as session:
        session.add_all(
            (
                MediaAsset(
                    id=source_id,
                    workspace_id=workspace_id,
                    project_id=project.id,
                    object_uri="s3://bucket/assembly-source.mp4",
                    sha256="a" * 64,
                    size_bytes=100,
                    content_type="video/mp4",
                    metadata_json={
                        "episode_id": str(episode_id),
                        "duration_seconds": 3.0,
                    },
                ),
                MediaAsset(
                    id=picture_asset_id,
                    workspace_id=workspace_id,
                    project_id=project.id,
                    object_uri="s3://bucket/adopted-picture.mp4",
                    sha256="b" * 64,
                    size_bytes=30,
                    content_type="video/mp4",
                    metadata_json={"episode_id": str(episode_id)},
                ),
                MediaAsset(
                    id=dialogue_asset_id,
                    workspace_id=workspace_id,
                    project_id=project.id,
                    object_uri="s3://bucket/adopted-dialogue.wav",
                    sha256="c" * 64,
                    size_bytes=30,
                    content_type="audio/wav",
                    metadata_json={"episode_id": str(episode_id)},
                ),
                MediaAsset(
                    id=stem_asset_id,
                    workspace_id=workspace_id,
                    project_id=project.id,
                    object_uri="s3://bucket/background.wav",
                    sha256="d" * 64,
                    size_bytes=30,
                    content_type="audio/wav",
                    metadata_json={
                        "episode_id": str(episode_id),
                        "stem_kind": "BACKGROUND",
                    },
                ),
            )
        )
        session.add(
            Episode(
                id=episode_id,
                project_id=project.id,
                episode_no=1,
                source_asset_id=source_id,
            )
        )
        session.add(
            Shot(
                id=shot_id,
                episode_id=episode_id,
                shot_no=1,
                start_ms=1000,
                end_ms=2000,
            )
        )
        session.add_all(
            (
                CandidateGroup(
                    id=picture_group_id,
                    project_id=project.id,
                    shot_id=shot_id,
                    purpose="LIPSYNC",
                ),
                CandidateGroup(
                    id=dialogue_group_id,
                    project_id=project.id,
                    purpose="TTS",
                ),
                StageRun(
                    id=picture_run_id,
                    project_id=project.id,
                    episode_id=episode_id,
                    shot_id=shot_id,
                    candidate_group_id=picture_group_id,
                    stage_type="LIPSYNC_GENERATE",
                    status="ADOPTED",
                    idempotency_key="assembly-sql-picture",
                    runtime_profile_id="gpu-render",
                    observed_control_version=1,
                ),
                StageRun(
                    id=dialogue_run_id,
                    project_id=project.id,
                    episode_id=episode_id,
                    candidate_group_id=dialogue_group_id,
                    stage_type="TTS_GENERATE",
                    status="ADOPTED",
                    idempotency_key="assembly-sql-dialogue",
                    runtime_profile_id="gpu-audio",
                    observed_control_version=1,
                    params={
                        "tts_request": {
                            "localized": {
                                "utterance": {
                                    "start_seconds": 1.0,
                                    "end_seconds": 2.0,
                                }
                            }
                        }
                    },
                ),
            )
        )
    async with database.begin() as session:
        session.add_all(
            (
                RenderVariant(
                    id=picture_variant_id,
                    candidate_group_id=picture_group_id,
                    stage_run_id=picture_run_id,
                    variant_no=1,
                    status="ADOPTED",
                    output_asset_id=picture_asset_id,
                ),
                RenderVariant(
                    id=dialogue_variant_id,
                    candidate_group_id=dialogue_group_id,
                    stage_run_id=dialogue_run_id,
                    variant_no=1,
                    status="ADOPTED",
                    output_asset_id=dialogue_asset_id,
                ),
            )
        )
    async with database.begin() as session:
        picture_group = await session.get(CandidateGroup, picture_group_id)
        dialogue_group = await session.get(CandidateGroup, dialogue_group_id)
        assert picture_group and dialogue_group
        picture_group.status = "ADOPTED"
        picture_group.state_version = 2
        picture_group.adopted_variant_id = picture_variant_id
        dialogue_group.status = "ADOPTED"
        dialogue_group.state_version = 2
        dialogue_group.adopted_variant_id = dialogue_variant_id

    job = await repository.create_episode_assembly_job(
        workspace_id,
        project.id,
        EpisodeAssemblyJobCreate(
            episode_id=episode_id,
            source_video_asset_id=source_id,
            picture_selections=(
                AdoptedPictureSelection(
                    shot_id=shot_id,
                    adopted_variant_id=picture_variant_id,
                ),
            ),
            dialogue_selections=(
                AdoptedDialogueSelection(
                    adopted_variant_id=dialogue_variant_id,
                    gain_db=-1,
                    room_reverb=0.2,
                ),
            ),
            stem_selections=(
                StemSelection(asset_id=stem_asset_id, role="BACKGROUND", gain_db=-12),
            ),
            subtitle_cues=(
                AssemblySubtitleCue(
                    index=1,
                    start_seconds=1,
                    end_seconds=2,
                    text="Hello.",
                ),
            ),
        ),
    )
    async with database() as session:
        runs = list(await session.scalars(select(StageRun).where(StageRun.job_id == job.id)))
        dependency_count = await session.scalar(
            select(func.count())
            .select_from(StageDependency)
            .where(StageDependency.stage_run_id.in_([item.id for item in runs]))
        )
    assert {item.stage_type for item in runs} == {
        "PICTURE_CONFORM",
        "SUBTITLE_RENDER",
        "AUDIO_MIX",
        "ASSEMBLE_EPISODE",
    }
    assert sum(item.status == "READY" for item in runs) == 3
    assert sum(item.status == "PENDING" for item in runs) == 1
    assert dependency_count == 3
