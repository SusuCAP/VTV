from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from vtv_db.model_registry import (
    AutomationStatus,
    InvalidModelReleaseTransitionError,
    LicenseStatus,
    ModelReleaseState,
    review_license,
    set_automation_status,
)
from vtv_db.releases import (
    ArtifactReleaseState,
    ArtifactReleaseStatus,
    InvalidArtifactTransitionError,
    confirm_release,
    publish_release,
)
from vtv_db.repository import (
    LIPSYNC_MODEL_KEYS,
    LOUDNESS_PRESETS,
    REQUIRED_QC_METRICS_BY_PURPOSE,
    AnalysisNotReadyError,
    ArtifactConflictError,
    CandidateConflictError,
    DeliveryConflictError,
    ModelReleaseConflictError,
    ProductionNotReadyError,
    ProjectNotFoundError,
    RightsReleaseConflictError,
    UploadConflictError,
    UploadRecord,
    _build_delivery_manifest,
    _build_tts_request,
)
from vtv_db.rights import evaluate_rights_release
from vtv_delivery import DeliveryApprove, DeliveryCreate, DeliveryManifestBuilder, DeliveryRead
from vtv_evaluation import evaluate_release
from vtv_production import LipSyncRequest, ShotDialogueFeatures, TieredLipSyncRouter
from vtv_schemas.analysis import AnalysisDocumentRead
from vtv_schemas.assembly import EpisodeAssemblyJobCreate
from vtv_schemas.benchmarks import BenchmarkReleaseCreate, BenchmarkReleaseRead
from vtv_schemas.candidates import (
    CandidateAdopt,
    CandidateGroupRead,
    CandidateQcCreate,
    CandidateVariantRead,
    QcMetricRead,
)
from vtv_schemas.enums import JobStatus, ProjectStatus
from vtv_schemas.episodes import EpisodeRead
from vtv_schemas.jobs import JobRead, ProduceRequest
from vtv_schemas.model_releases import ModelReleaseCreate, ModelReleaseRead
from vtv_schemas.production import DubbingJobCreate, LipSyncJobCreate
from vtv_schemas.projects import ProjectCreate, ProjectRead
from vtv_schemas.releases import ArtifactReleaseCreate, ArtifactReleaseRead
from vtv_schemas.rights import (
    RightsExecutionCheck,
    RightsExecutionDecision,
    RightsReleaseCreate,
    RightsReleaseRead,
)
from vtv_schemas.uploads import MultipartInit, UploadPart, UploadRead


class MemoryRepository:
    """Development repository; PostgreSQL replaces it in the next increment."""

    def __init__(self) -> None:
        self._projects: dict[UUID, ProjectRead] = {}
        self._jobs: dict[UUID, JobRead] = {}
        self._uploads: dict[UUID, UploadRecord] = {}
        self._episodes: dict[UUID, list[EpisodeRead]] = {}
        self._releases: dict[UUID, ArtifactReleaseRead] = {}
        self._analysis_documents: list[AnalysisDocumentRead] = []
        self._model_releases: dict[UUID, ModelReleaseRead] = {}
        self._benchmark_releases: dict[UUID, BenchmarkReleaseRead] = {}
        self._rights_releases: dict[UUID, RightsReleaseRead] = {}
        self._asset_sha256s: dict[UUID, str] = {}
        self._job_idempotency: dict[tuple[UUID, str], UUID] = {}
        self._production_stage_params: dict[UUID, list[dict]] = {}
        self._candidate_groups: dict[UUID, CandidateGroupRead] = {}
        self._variant_stage_params: dict[UUID, dict] = {}
        self._lipsync_shots: dict[UUID, dict] = {}
        self._lipsync_assets: dict[UUID, dict] = {}
        self._deliveries: dict[UUID, DeliveryRead] = {}
        self._delivery_inputs: dict[UUID, dict] = {}
        self._lock = RLock()

    async def create_project(self, workspace_id: UUID, payload: ProjectCreate) -> ProjectRead:
        now = datetime.now(UTC)
        project = ProjectRead(
            **payload.model_dump(),
            id=uuid4(),
            workspace_id=workspace_id,
            status=ProjectStatus.DRAFT,
            state_version=1,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._projects[project.id] = project
        return project

    async def create_benchmark_release(
        self, workspace_id: UUID, model_release_id: UUID, payload: BenchmarkReleaseCreate
    ) -> BenchmarkReleaseRead:
        with self._lock:
            model = self._model_releases.get(model_release_id)
            if model is None or model.workspace_id != workspace_id:
                raise ProjectNotFoundError(model_release_id)
            if model.state_version != payload.expected_model_state_version:
                raise ModelReleaseConflictError(
                    "model release state version mismatch: "
                    f"expected {payload.expected_model_state_version}, actual {model.state_version}"
                )
            report = evaluate_release(
                model_key=model.model_key,
                model_release=model.release_name,
                dataset=payload.dataset,
                policy=payload.policy,
                evidence=payload.evidence,
                results=payload.results,
            )
            if any(
                item.model_release_id == model_release_id
                and item.dataset_fingerprint == payload.dataset.fingerprint
                and item.policy_fingerprint == payload.policy.fingerprint
                and item.weights_sha256 == payload.evidence.weights_sha256
                for item in self._benchmark_releases.values()
            ):
                raise ModelReleaseConflictError("benchmark release already exists")
            benchmark = BenchmarkReleaseRead(
                id=uuid4(),
                workspace_id=workspace_id,
                model_release_id=model_release_id,
                dataset_key=payload.dataset.dataset_key,
                dataset_release=payload.dataset.release,
                dataset_fingerprint=payload.dataset.fingerprint,
                annotation_release=payload.dataset.annotation_release,
                policy_key=payload.policy.policy_key,
                policy_release=payload.policy.release,
                policy_fingerprint=payload.policy.fingerprint,
                weights_sha256=payload.evidence.weights_sha256,
                runtime_fingerprint=payload.evidence.runtime_fingerprint,
                report=report,
                approved=report.approved,
                failed_gates=report.failed_gates,
                created_at=datetime.now(UTC),
            )
            self._benchmark_releases[benchmark.id] = benchmark
            if report.approved:
                self._model_releases[model.id] = model.model_copy(
                    update={
                        "approved_benchmark_release_id": benchmark.id,
                        "state_version": model.state_version + 1,
                        "updated_at": datetime.now(UTC),
                    }
                )
            return benchmark

    async def list_benchmark_releases(
        self, workspace_id: UUID, model_release_id: UUID
    ) -> list[BenchmarkReleaseRead]:
        with self._lock:
            model = self._model_releases.get(model_release_id)
            if model is None or model.workspace_id != workspace_id:
                raise ProjectNotFoundError(model_release_id)
            return [
                item
                for item in self._benchmark_releases.values()
                if item.workspace_id == workspace_id and item.model_release_id == model_release_id
            ]

    async def create_model_release(
        self, workspace_id: UUID, payload: ModelReleaseCreate
    ) -> ModelReleaseRead:
        with self._lock:
            if any(
                item.workspace_id == workspace_id
                and item.model_key == payload.model_key
                and item.release_name == payload.release_name
                for item in self._model_releases.values()
            ):
                raise ModelReleaseConflictError("model release already exists")
            if payload.fallback_release_id:
                fallback = self._model_releases.get(payload.fallback_release_id)
                if (
                    fallback is None
                    or fallback.workspace_id != workspace_id
                    or fallback.model_key != payload.model_key
                ):
                    raise ProjectNotFoundError(payload.fallback_release_id)
            now = datetime.now(UTC)
            release = ModelReleaseRead(
                id=uuid4(),
                workspace_id=workspace_id,
                model_key=payload.model_key,
                release_name=payload.release_name,
                provider=payload.provider,
                endpoint=payload.endpoint,
                license_id=payload.license_id,
                license_status="REVIEW",
                automation_status="OBSERVE",
                traffic_percent=0,
                state_version=1,
                model_card_uri=payload.model_card_uri,
                config=payload.config,
                fallback_release_id=payload.fallback_release_id,
                created_at=now,
                updated_at=now,
            )
            self._model_releases[release.id] = release
            return release

    async def list_model_releases(
        self, workspace_id: UUID, model_key: str | None = None
    ) -> list[ModelReleaseRead]:
        with self._lock:
            return [
                item
                for item in self._model_releases.values()
                if item.workspace_id == workspace_id
                and (model_key is None or item.model_key == model_key)
            ]

    async def review_model_license(
        self,
        workspace_id: UUID,
        release_id: UUID,
        decision: str,
        actor_id: UUID,
        expected_state_version: int,
    ) -> ModelReleaseRead:
        release = self._get_model_release(workspace_id, release_id)
        try:
            state = review_license(
                _memory_model_state(release),
                decision=LicenseStatus(decision),
                actor_id=actor_id,
                expected_state_version=expected_state_version,
            )
        except InvalidModelReleaseTransitionError as exc:
            raise ModelReleaseConflictError(str(exc)) from exc
        return self._store_model_state(release, state)

    async def update_model_automation(
        self,
        workspace_id: UUID,
        release_id: UUID,
        target: str,
        traffic_percent: int,
        expected_state_version: int,
    ) -> ModelReleaseRead:
        release = self._get_model_release(workspace_id, release_id)
        target_status = AutomationStatus(target)
        with self._lock:
            if target_status in {AutomationStatus.CANARY, AutomationStatus.ACTIVE}:
                benchmark = self._benchmark_releases.get(
                    release.approved_benchmark_release_id
                )
                if (
                    benchmark is None
                    or benchmark.workspace_id != workspace_id
                    or benchmark.model_release_id != release.id
                    or not benchmark.approved
                ):
                    raise ModelReleaseConflictError(
                        "model release has no valid approved benchmark release"
                    )
            others = [
                item
                for item in self._model_releases.values()
                if item.id != release.id
                and item.workspace_id == workspace_id
                and item.model_key == release.model_key
                and item.automation_status in {"CANARY", "ACTIVE"}
            ]
            active = [item for item in others if item.automation_status == "ACTIVE"]
            canary = [item for item in others if item.automation_status == "CANARY"]
            if target_status is AutomationStatus.CANARY and (canary or not active):
                raise ModelReleaseConflictError(
                    "canary requires one ACTIVE baseline and no other canary"
                )
            if target_status is AutomationStatus.ACTIVE:
                if canary:
                    raise ModelReleaseConflictError("another canary release must be disabled")
                if active and release.automation_status != "CANARY":
                    raise ModelReleaseConflictError("activate through canary first")
                if active:
                    previous = active[0]
                    disabled = set_automation_status(
                        _memory_model_state(previous),
                        target=AutomationStatus.DISABLED,
                        traffic_percent=0,
                        expected_state_version=previous.state_version,
                    )
                    self._store_model_state(previous, disabled)
        try:
            state = set_automation_status(
                _memory_model_state(release),
                target=target_status,
                traffic_percent=traffic_percent,
                expected_state_version=expected_state_version,
            )
        except InvalidModelReleaseTransitionError as exc:
            raise ModelReleaseConflictError(str(exc)) from exc
        return self._store_model_state(release, state)

    def _get_model_release(self, workspace_id: UUID, release_id: UUID) -> ModelReleaseRead:
        with self._lock:
            release = self._model_releases.get(release_id)
        if release is None or release.workspace_id != workspace_id:
            raise ProjectNotFoundError(release_id)
        return release

    def _store_model_state(
        self, release: ModelReleaseRead, state: ModelReleaseState
    ) -> ModelReleaseRead:
        changed = release.model_copy(
            update={
                "license_status": state.license_status,
                "automation_status": state.automation_status,
                "traffic_percent": state.traffic_percent,
                "state_version": state.state_version,
                "reviewed_by": state.reviewed_by,
                "reviewed_at": state.reviewed_at,
                "updated_at": datetime.now(UTC),
            }
        )
        with self._lock:
            self._model_releases[release.id] = changed
        return changed

    async def get_project(self, workspace_id: UUID, project_id: UUID) -> ProjectRead:
        with self._lock:
            project = self._projects.get(project_id)
        if project is None or project.workspace_id != workspace_id:
            raise ProjectNotFoundError(project_id)
        return project

    async def list_projects(self, workspace_id: UUID) -> list[ProjectRead]:
        with self._lock:
            return [
                project
                for project in self._projects.values()
                if project.workspace_id == workspace_id
            ]

    async def list_episodes(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[EpisodeRead]:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            return list(self._episodes.get(project_id, []))

    async def list_jobs(self, workspace_id: UUID, project_id: UUID) -> list[JobRead]:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            return [job for job in self._jobs.values() if job.project_id == project_id]

    async def create_analysis_job(self, workspace_id: UUID, project_id: UUID) -> JobRead:
        project = await self.get_project(workspace_id, project_id)
        with self._lock:
            episodes = list(self._episodes.get(project_id, []))
        if not episodes:
            raise AnalysisNotReadyError("project analysis requires an uploaded episode")
        job = JobRead(
            id=uuid4(),
            project_id=project.id,
            kind="PROJECT_ANALYSIS",
            status=JobStatus.QUEUED,
            progress=0,
            total_stages=len(episodes) * 6 + 1,
            completed_stages=0,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._projects[project.id] = project.model_copy(
                update={
                    "status": ProjectStatus.ANALYZING,
                    "state_version": project.state_version + 1,
                    "updated_at": datetime.now(UTC),
                }
            )
        return job

    async def create_production_job(
        self, workspace_id: UUID, project_id: UUID, payload: ProduceRequest
    ) -> JobRead:
        project = await self.get_project(workspace_id, project_id)
        if project.state_version != payload.expected_project_state_version:
            raise ProductionNotReadyError(
                f"project state version mismatch: "
                f"expected {payload.expected_project_state_version}, "
                f"actual {project.state_version}"
            )
        with self._lock:
            episodes = [
                ep
                for ep in self._episodes.get(project_id, [])
                if ep.source_asset_id is not None
            ]
        if not episodes:
            raise ProductionNotReadyError(
                "visual production requires at least one uploaded episode"
            )
        job = JobRead(
            id=uuid4(),
            project_id=project_id,
            kind="VISUAL_PRODUCTION",
            status=JobStatus.QUEUED,
            progress=0,
            total_stages=len(episodes),
            completed_stages=0,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._projects[project.id] = project.model_copy(
                update={
                    "state_version": project.state_version + 1,
                    "updated_at": datetime.now(UTC),
                }
            )
        return job

    async def create_dubbing_job(
        self, workspace_id: UUID, project_id: UUID, payload: DubbingJobCreate
    ) -> JobRead:
        project = await self.get_project(workspace_id, project_id)
        idempotency_key = f"episode-dubbing:{payload.fingerprint}"
        with self._lock:
            existing_id = self._job_idempotency.get((project_id, idempotency_key))
            if existing_id is not None:
                return self._jobs[existing_id]
            episode = next(
                (
                    item
                    for item in self._episodes.get(project_id, [])
                    if item.id == payload.episode_id and item.source_asset_id is not None
                ),
                None,
            )
            localization = self._releases.get(payload.localization_release_id)
            selected = next(
                (
                    item
                    for item in self._model_releases.values()
                    if item.workspace_id == workspace_id
                    and item.model_key == "TTS"
                    and item.license_status == "APPROVED"
                    and item.automation_status == "ACTIVE"
                    and item.config.get("adapter_mode") == "remote_tts"
                ),
                None,
            )
        if episode is None:
            raise ProjectNotFoundError(payload.episode_id)
        if (
            localization is None
            or localization.project_id != project_id
            or localization.status != "RELEASED"
            or localization.artifact_type
            not in {"LOCALIZATION_BIBLE", "LOCALIZATION_UTTERANCES"}
        ):
            raise ProductionNotReadyError(
                "dubbing requires a released localization artifact"
            )
        if selected is None:
            raise ProductionNotReadyError("no ACTIVE TTS model release is available")
        stage_params: list[dict] = []
        now = datetime.now(UTC)
        for item in payload.utterances:
            if item.target_language != project.locale:
                raise ProductionNotReadyError(
                    "utterance target language must match project locale"
                )
            with self._lock:
                voice = self._releases.get(item.voice_release_id)
                voice_hash = self._asset_sha256s.get(
                    voice.content_asset_id if voice is not None else UUID(int=0)
                )
                rights = self._rights_releases.get(item.rights_release_id)
            if (
                voice is None
                or voice.project_id != project_id
                or voice.artifact_type != "VOICE_RELEASE"
                or voice.status != "RELEASED"
                or voice_hash is None
            ):
                raise ProductionNotReadyError(
                    "dubbing requires released voice artifacts with valid content assets"
                )
            if rights is None or rights.project_id != project_id:
                raise ProjectNotFoundError(item.rights_release_id)
            if rights.subject_type != "VOICE" or rights.subject_id != item.character_id:
                raise ProductionNotReadyError(
                    "voice rights subject must match utterance character"
                )
            decision = evaluate_rights_release(
                rights,
                RightsExecutionCheck(
                    operation="voice_clone",
                    market=project.target_market,
                    language=project.locale,
                    commercial_use=payload.commercial_use,
                    at=now,
                ),
            )
            if not decision.allowed:
                raise ProductionNotReadyError(
                    f"RIGHTS_BLOCKED: {','.join(decision.reason_codes)}"
                )
            request = _build_tts_request(
                item,
                target_market=project.target_market,
                localization_release_id=localization.id,
                voice_release_id=voice.id,
                voice_reference_sha256=voice_hash,
                rights=rights,
                selected_model_release=selected.release_name,
                commercial_use=payload.commercial_use,
            )
            stage_params.append(
                {
                    "tts_request": request.model_dump(mode="json"),
                    "maximum_duration_deviation": item.maximum_duration_deviation,
                    "rights_state_version": rights.state_version,
                    "model_runtime": {
                        "model_key": selected.model_key,
                        "endpoint": selected.endpoint,
                        "release": selected.release_name,
                        "license_id": selected.license_id,
                        "approved_for_automation": True,
                        "config": selected.config,
                    },
                }
            )
        job = JobRead(
            id=uuid4(),
            project_id=project_id,
            kind="EPISODE_DUBBING_CANDIDATES",
            status=JobStatus.QUEUED,
            progress=0,
            total_stages=len(stage_params),
            completed_stages=0,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._job_idempotency[(project_id, idempotency_key)] = job.id
            self._production_stage_params[job.id] = stage_params
            self._projects[project.id] = project.model_copy(
                update={
                    "status": ProjectStatus.PRODUCING,
                    "state_version": project.state_version + 1,
                    "updated_at": datetime.now(UTC),
                }
            )
        return job

    async def create_lipsync_job(
        self, workspace_id: UUID, project_id: UUID, payload: LipSyncJobCreate
    ) -> JobRead:
        project = await self.get_project(workspace_id, project_id)
        idempotency_key = f"episode-lipsync:{payload.fingerprint}"
        with self._lock:
            existing_id = self._job_idempotency.get((project_id, idempotency_key))
            if existing_id is not None:
                return self._jobs[existing_id]
            episode = next(
                (
                    item
                    for item in self._episodes.get(project_id, [])
                    if item.id == payload.episode_id
                ),
                None,
            )
        if episode is None:
            raise ProjectNotFoundError(payload.episode_id)
        router = TieredLipSyncRouter()
        stage_params: list[dict] = []
        now = datetime.now(UTC)
        for item in payload.shots:
            with self._lock:
                shot = self._lipsync_shots.get(item.shot_id)
                source = self._lipsync_assets.get(item.source_video_asset_id)
                group = next(
                    (
                        value
                        for value in self._candidate_groups.values()
                        if value.project_id == project_id
                        and value.purpose == "TTS"
                        and value.adopted_variant_id == item.adopted_tts_variant_id
                    ),
                    None,
                )
            if shot is None or shot.get("episode_id") != payload.episode_id:
                raise ProjectNotFoundError(item.shot_id)
            shot_duration = float(shot["duration_seconds"])
            if item.dialogue_duration_seconds > shot_duration + 0.05:
                raise ProductionNotReadyError(
                    "dialogue duration cannot exceed authoritative shot duration"
                )
            if (
                source is None
                or source.get("project_id") != project_id
                or source.get("shot_id") != item.shot_id
                or not str(source.get("content_type", "")).startswith("video/")
                or abs(float(source.get("duration_seconds", 0)) - shot_duration)
                > max(0.05, shot_duration * 0.02)
            ):
                raise ProductionNotReadyError(
                    "lipsync source must be a duration-matched project video asset"
                )
            if group is None:
                raise ProductionNotReadyError(
                    "lipsync requires the uniquely adopted TTS variant"
                )
            variant = next(
                value for value in group.variants if value.id == item.adopted_tts_variant_id
            )
            if variant.status != "ADOPTED":
                raise ProductionNotReadyError(
                    "lipsync requires the uniquely adopted TTS variant"
                )
            with self._lock:
                audio = self._lipsync_assets.get(variant.output_asset_id)
                tts_params = self._variant_stage_params.get(variant.id)
            if (
                audio is None
                or not str(audio.get("content_type", "")).startswith("audio/")
                or not isinstance(tts_params, dict)
            ):
                raise ProductionNotReadyError("adopted TTS provenance is incomplete")
            try:
                tts_request = tts_params["tts_request"]
                localized = tts_request["localized"]
                rights_id = UUID(
                    tts_request["voice_release"]["rights"]["rights_release_id"]
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProductionNotReadyError(
                    "adopted TTS variant has invalid rights provenance"
                ) from exc
            with self._lock:
                rights = self._rights_releases.get(rights_id)
            if rights is None or rights.project_id != project_id:
                raise ProductionNotReadyError("RIGHTS_BLOCKED: RIGHTS_RELEASE_MISSING")
            rights_decision = evaluate_rights_release(
                rights,
                RightsExecutionCheck(
                    operation="lipsync",
                    market=project.target_market,
                    language=project.locale,
                    commercial_use=payload.commercial_use,
                    at=now,
                ),
            )
            if not rights_decision.allowed:
                raise ProductionNotReadyError(
                    f"RIGHTS_BLOCKED: {','.join(rights_decision.reason_codes)}"
                )
            features = ShotDialogueFeatures(
                shot_id=item.shot_id,
                mouth_visible=item.mouth_visible,
                face_scale=item.face_scale,
                occlusion=item.occlusion,
                body_visible=item.body_visible,
                dialogue_duration_seconds=item.dialogue_duration_seconds,
                original_performance_reusable=item.original_performance_reusable,
                full_regeneration_required=item.full_regeneration_required,
            )
            route = router.route(features)
            candidate_count = 1 if route.level == "L0_NONE" else item.candidate_count
            selected = None
            if route.level != "L0_NONE":
                model_key = LIPSYNC_MODEL_KEYS[route.level]
                with self._lock:
                    selected = next(
                        (
                            model
                            for model in self._model_releases.values()
                            if model.workspace_id == workspace_id
                            and model.model_key == model_key
                            and model.license_status == "APPROVED"
                            and model.automation_status == "ACTIVE"
                            and model.config.get("adapter_mode") == "remote_lipsync"
                        ),
                        None,
                    )
                if selected is None:
                    raise ProductionNotReadyError(
                        f"no ACTIVE/CANARY model release is available for {model_key}"
                    )
            request = LipSyncRequest(
                features=features,
                decision=route,
                source_video_sha256=source["sha256"],
                source_video_duration_seconds=source["duration_seconds"],
                adopted_tts_variant_id=variant.id,
                audio_sha256=audio["sha256"],
                target_language=localized["target_language"],
                target_market=localized["target_market"],
                rights={
                    "rights_release_id": str(rights.id),
                    "state_version": rights.state_version,
                    "subject_id": rights.subject_id,
                    "allowed_operations": rights.allowed_operations,
                    "allowed_languages": rights.allowed_languages,
                    "allowed_markets": rights.allowed_markets,
                    "commercial_allowed": rights.commercial_scope == "COMMERCIAL",
                    "valid_at_execution": True,
                },
                seed=item.seed,
                candidate_count=candidate_count,
                commercial_use=payload.commercial_use,
            )
            params = {
                "lipsync_request": request.model_dump(mode="json"),
                "router_release": router.router_release,
                "rights_state_version": rights.state_version,
                "input_asset_ids": [str(item.source_video_asset_id), str(variant.output_asset_id)],
            }
            if selected is not None:
                params["model_runtime"] = {
                    "model_key": selected.model_key,
                    "endpoint": selected.endpoint,
                    "release": selected.release_name,
                    "license_id": selected.license_id,
                    "approved_for_automation": True,
                    "config": selected.config,
                }
            stage_params.append(params)
        job = JobRead(
            id=uuid4(),
            project_id=project_id,
            kind="EPISODE_LIPSYNC_CANDIDATES",
            status=JobStatus.QUEUED,
            progress=0,
            total_stages=len(stage_params),
            completed_stages=0,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._job_idempotency[(project_id, idempotency_key)] = job.id
            self._production_stage_params[job.id] = stage_params
            self._projects[project.id] = project.model_copy(
                update={
                    "status": ProjectStatus.PRODUCING,
                    "state_version": project.state_version + 1,
                    "updated_at": datetime.now(UTC),
                }
            )
        return job

    async def create_episode_assembly_job(
        self, workspace_id: UUID, project_id: UUID, payload: EpisodeAssemblyJobCreate
    ) -> JobRead:
        project = await self.get_project(workspace_id, project_id)
        idempotency_key = f"episode-assembly:{payload.fingerprint}"
        with self._lock:
            existing_id = self._job_idempotency.get((project_id, idempotency_key))
            if existing_id is not None:
                return self._jobs[existing_id]
            episode = next(
                (
                    item
                    for item in self._episodes.get(project_id, [])
                    if item.id == payload.episode_id
                ),
                None,
            )
            source = self._lipsync_assets.get(payload.source_video_asset_id)
        if episode is None:
            raise ProjectNotFoundError(payload.episode_id)
        if (
            source is None
            or source.get("project_id") != project_id
            or source.get("episode_id") != episode.id
            or not str(source.get("content_type", "")).startswith("video/")
            or float(source.get("duration_seconds", 0)) <= 0
        ):
            raise ProductionNotReadyError(
                "assembly source must be a duration-bound same-episode video"
            )
        duration = float(source["duration_seconds"])
        picture_assets: list[tuple[dict, dict]] = []
        for item in payload.picture_selections:
            with self._lock:
                group = next(
                    (
                        value
                        for value in self._candidate_groups.values()
                        if value.project_id == project_id
                        and value.purpose in {"LIPSYNC", "RENDER"}
                        and value.shot_id == item.shot_id
                        and value.adopted_variant_id == item.adopted_variant_id
                    ),
                    None,
                )
                shot = self._lipsync_shots.get(item.shot_id)
            if group is None or shot is None or shot.get("episode_id") != episode.id:
                raise ProductionNotReadyError(
                    "picture conform requires adopted same-episode video variants"
                )
            variant = next(
                value for value in group.variants if value.id == item.adopted_variant_id
            )
            with self._lock:
                asset = self._lipsync_assets.get(variant.output_asset_id)
            if (
                variant.status != "ADOPTED"
                or asset is None
                or not str(asset.get("content_type", "")).startswith("video/")
            ):
                raise ProductionNotReadyError(
                    "picture conform requires adopted same-episode video variants"
                )
            picture_assets.append((shot, asset))
        picture_assets.sort(key=lambda value: value[0]["start_seconds"])
        previous_end = 0.0
        picture_edits: list[dict] = []
        for shot, asset in picture_assets:
            start = float(shot["start_seconds"])
            end = float(shot["end_seconds"])
            if start < previous_end or end > duration + 0.05:
                raise ProductionNotReadyError(
                    "adopted picture intervals overlap or exceed episode duration"
                )
            previous_end = end
            picture_edits.append(
                {
                    "shot_id": str(shot["id"]),
                    "replacement_sha256": asset["sha256"],
                    "start_seconds": start,
                    "end_seconds": end,
                }
            )
        dialogue_assets: list[dict] = []
        mix_tracks: list[dict] = []
        for item in payload.dialogue_selections:
            with self._lock:
                group = next(
                    (
                        value
                        for value in self._candidate_groups.values()
                        if value.project_id == project_id
                        and value.purpose == "TTS"
                        and value.adopted_variant_id == item.adopted_variant_id
                    ),
                    None,
                )
            if group is None:
                raise ProductionNotReadyError(
                    "audio mix requires adopted same-episode TTS variants"
                )
            variant = next(
                value for value in group.variants if value.id == item.adopted_variant_id
            )
            with self._lock:
                asset = self._lipsync_assets.get(variant.output_asset_id)
                params = self._variant_stage_params.get(variant.id)
            if (
                variant.status != "ADOPTED"
                or asset is None
                or asset.get("episode_id") != episode.id
                or not str(asset.get("content_type", "")).startswith("audio/")
                or not isinstance(params, dict)
            ):
                raise ProductionNotReadyError(
                    "audio mix requires adopted same-episode TTS variants"
                )
            try:
                utterance = params["tts_request"]["localized"]["utterance"]
                start = float(utterance["start_seconds"])
                end = float(utterance["end_seconds"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProductionNotReadyError(
                    "adopted TTS variant has invalid timeline provenance"
                ) from exc
            if end <= start or end > duration + 0.05:
                raise ProductionNotReadyError("adopted TTS timeline exceeds episode")
            dialogue_assets.append(asset)
            mix_tracks.append(
                {
                    "asset_sha256": asset["sha256"],
                    "role": "DIALOGUE",
                    "start_seconds": start,
                    "gain_db": item.gain_db,
                    "room_reverb": item.room_reverb,
                }
            )
        stem_assets: list[dict] = []
        for item in payload.stem_selections:
            with self._lock:
                asset = self._lipsync_assets.get(item.asset_id)
            if (
                asset is None
                or asset.get("episode_id") != episode.id
                or asset.get("stem_kind") != item.role
            ):
                raise ProductionNotReadyError(
                    "stem asset must match the requested episode and role"
                )
            stem_assets.append(asset)
            mix_tracks.append(
                {
                    "asset_sha256": asset["sha256"],
                    "role": item.role,
                    "start_seconds": 0,
                    "gain_db": item.gain_db,
                    "room_reverb": 0,
                }
            )
        if any(item.end_seconds > duration + 0.05 for item in payload.subtitle_cues):
            raise ProductionNotReadyError("subtitle cue exceeds episode duration")
        subtitle_document = {
            "locale": project.locale,
            "cues": [item.model_dump(mode="json") for item in payload.subtitle_cues],
        }
        formats = [item for item in project.output.subtitle_formats if item in {"srt", "vtt"}]
        if payload.burn_subtitles and "srt" not in formats:
            formats.insert(0, "srt")
        with self._lock:
            episode_shots = sorted(
                (
                    value
                    for value in self._lipsync_shots.values()
                    if value.get("episode_id") == episode.id
                ),
                key=lambda value: float(value["start_seconds"]),
            )
        if (
            not episode_shots
            or abs(float(episode_shots[0]["start_seconds"])) > 0.001
            or abs(float(episode_shots[-1]["end_seconds"]) - duration) > 0.001
            or any(
                abs(float(previous["end_seconds"]) - float(current["start_seconds"]))
                > 0.001
                for previous, current in zip(
                    episode_shots, episode_shots[1:], strict=False
                )
            )
        ):
            raise ProductionNotReadyError(
                "delivery shot list must continuously span the full episode"
            )
        selection_by_shot = {
            item.shot_id: item.adopted_variant_id for item in payload.picture_selections
        }
        picture_asset_by_shot = {item[0]["id"]: item[1] for item in picture_assets}
        delivery_shots = []
        for shot_no, shot in enumerate(episode_shots, 1):
            shot_id = shot["id"]
            variant_id = selection_by_shot.get(shot_id)
            selected_asset = picture_asset_by_shot.get(shot_id)
            route = shot.get("route")
            if route not in {"L0", "L1", "L2", "L3", "L4", "L5"}:
                route = "L2" if variant_id else "L0"
            delivery_shots.append(
                {
                    "shot_id": str(shot_id),
                    "shot_no": shot.get("shot_no", shot_no),
                    "start_ms": round(float(shot["start_seconds"]) * 1000),
                    "end_ms": round(float(shot["end_seconds"]) * 1000),
                    "route": route,
                    "adopted_variant_id": str(variant_id) if variant_id else None,
                    "output_asset_id": (
                        str(selected_asset["id"]) if selected_asset is not None else None
                    ),
                    "qc_verdict": "PASS" if variant_id else "SOURCE_UNCHANGED",
                }
            )
        output = project.output
        stage_params = [
            {
                "stage_type": "PICTURE_CONFORM",
                "input_asset_ids": [
                    str(payload.source_video_asset_id),
                    *(str(item[1]["id"]) for item in picture_assets),
                ],
                "picture_conform_request": {
                    "source_video_sha256": source["sha256"],
                    "duration_seconds": duration,
                    "edits": picture_edits,
                },
            },
            {
                "stage_type": "SUBTITLE_RENDER",
                "subtitle_document": subtitle_document,
                "formats": formats or ["srt"],
            },
            {
                "stage_type": "AUDIO_MIX",
                "input_asset_ids": [
                    *(str(item["id"]) for item in dialogue_assets),
                    *(str(item["id"]) for item in stem_assets),
                ],
                "audio_mix_request": {
                    "duration_seconds": duration,
                    "tracks": mix_tracks,
                    "preset": LOUDNESS_PRESETS[payload.loudness_preset],
                    "sample_rate": 48_000,
                    "channels": 2,
                },
            },
            {
                "stage_type": "ASSEMBLE_EPISODE",
                "episode_assembly_template": {
                    "duration_seconds": duration,
                    "width": output.width,
                    "height": output.height,
                    "fps": output.fps,
                    "video_codec": output.video_codec,
                    "audio_codec": output.audio_codec,
                    "burn_subtitles": payload.burn_subtitles,
                    "subtitle_document": subtitle_document,
                },
            },
            {
                "stage_type": "DELIVERY_EVIDENCE",
                "delivery_evidence_template": {
                    "source_video_sha256": source["sha256"],
                    "project_state_version": project.state_version + 1,
                    "duration_ms": round(duration * 1000),
                    "shots": delivery_shots,
                    "qc": [],
                },
            },
        ]
        job = JobRead(
            id=uuid4(),
            project_id=project_id,
            kind="EPISODE_ASSEMBLY",
            status=JobStatus.QUEUED,
            progress=0,
            total_stages=5,
            completed_stages=0,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._job_idempotency[(project_id, idempotency_key)] = job.id
            self._production_stage_params[job.id] = stage_params
            self._projects[project.id] = project.model_copy(
                update={
                    "status": ProjectStatus.PRODUCING,
                    "state_version": project.state_version + 1,
                    "updated_at": datetime.now(UTC),
                }
            )
        return job

    async def create_delivery(
        self, workspace_id: UUID, project_id: UUID, payload: DeliveryCreate
    ) -> DeliveryRead:
        project = await self.get_project(workspace_id, project_id)
        if project.state_version != payload.expected_project_state_version:
            raise DeliveryConflictError(
                "project state version mismatch: "
                f"expected {payload.expected_project_state_version}, "
                f"actual {project.state_version}"
            )
        with self._lock:
            episode = next(
                (
                    item
                    for item in self._episodes.get(project_id, [])
                    if item.id == payload.episode_id
                ),
                None,
            )
        if episode is None or episode.source_asset_id is None:
            raise ProjectNotFoundError(payload.episode_id)
        role_by_id: dict[UUID, str] = {
            payload.master_asset_id: "MASTER_VIDEO",
            payload.quality_report_asset_id: "QUALITY_REPORT",
            payload.shot_list_asset_id: "SHOT_LIST",
        }
        requested_ids = set(role_by_id)
        requested_ids.update(payload.subtitle_asset_ids)
        requested_ids.update(payload.additional_asset_ids)
        with self._lock:
            asset_by_id = {
                asset_id: self._lipsync_assets.get(asset_id) for asset_id in requested_ids
            }
        if any(asset is None for asset in asset_by_id.values()):
            raise ProjectNotFoundError("delivery asset")
        for asset_id in payload.subtitle_asset_ids:
            asset = asset_by_id[asset_id]
            assert asset is not None
            role = (
                "SUBTITLE_VTT"
                if str(asset.get("object_uri", "")).lower().endswith(".vtt")
                else "SUBTITLE_SRT"
            )
            if role in role_by_id.values():
                raise DeliveryConflictError("subtitle formats must be unique")
            role_by_id[asset_id] = role
        allowed_additional = {"POSTER", "TRAILER", "AD_CUT"}
        for asset_id in payload.additional_asset_ids:
            asset = asset_by_id[asset_id]
            assert asset is not None
            role = asset.get("metadata", {}).get("delivery_role")
            if role not in allowed_additional or role in role_by_id.values():
                raise DeliveryConflictError("additional asset has invalid delivery role")
            role_by_id[asset_id] = role
        for asset in asset_by_id.values():
            assert asset is not None
            if asset.get("project_id") != project_id or asset.get("episode_id") != episode.id:
                raise DeliveryConflictError("delivery assets must belong to the episode")
        master = asset_by_id[payload.master_asset_id]
        report = asset_by_id[payload.quality_report_asset_id]
        shot_list = asset_by_id[payload.shot_list_asset_id]
        assert master is not None and report is not None and shot_list is not None
        if not str(master.get("content_type", "")).startswith("video/"):
            raise DeliveryConflictError("master asset must be video")
        if not str(report.get("content_type", "")).endswith("json"):
            raise DeliveryConflictError("quality report must be JSON")
        if not str(shot_list.get("content_type", "")).endswith("json"):
            raise DeliveryConflictError("shot list must be JSON")
        now = datetime.now(UTC)
        with self._lock:
            version = 1 + max(
                (
                    item.version
                    for item in self._deliveries.values()
                    if item.episode_id == episode.id
                ),
                default=0,
            )
            delivery = DeliveryRead(
                id=uuid4(),
                workspace_id=workspace_id,
                project_id=project_id,
                episode_id=episode.id,
                version=version,
                status="DRAFT",
                state_version=1,
                created_at=now,
                updated_at=now,
            )
            self._deliveries[delivery.id] = delivery
            self._delivery_inputs[delivery.id] = {
                "project_state_version": project.state_version,
                "c2pa_requested": payload.c2pa_requested,
                "roles": role_by_id,
            }
        return delivery

    async def list_deliveries(
        self, workspace_id: UUID, project_id: UUID, episode_id: UUID | None = None
    ) -> list[DeliveryRead]:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            result = [
                item
                for item in self._deliveries.values()
                if item.workspace_id == workspace_id
                and item.project_id == project_id
                and (episode_id is None or item.episode_id == episode_id)
            ]
        return sorted(result, key=lambda item: (str(item.episode_id), -item.version))

    async def get_delivery(
        self, workspace_id: UUID, delivery_id: UUID
    ) -> DeliveryRead:
        with self._lock:
            delivery = self._deliveries.get(delivery_id)
        if delivery is None or delivery.workspace_id != workspace_id:
            raise ProjectNotFoundError(delivery_id)
        return delivery

    async def approve_delivery(
        self, workspace_id: UUID, delivery_id: UUID, payload: DeliveryApprove
    ) -> DeliveryRead:
        with self._lock:
            delivery = self._deliveries.get(delivery_id)
            inputs = self._delivery_inputs.get(delivery_id)
        if delivery is None or delivery.workspace_id != workspace_id or inputs is None:
            raise ProjectNotFoundError(delivery_id)
        if delivery.state_version != payload.expected_state_version:
            raise DeliveryConflictError(
                "delivery state version mismatch: "
                f"expected {payload.expected_state_version}, actual {delivery.state_version}"
            )
        if delivery.status != "DRAFT":
            raise DeliveryConflictError("only draft deliveries can be approved")
        project = await self.get_project(workspace_id, delivery.project_id)
        if project.state_version != inputs["project_state_version"]:
            raise DeliveryConflictError("project changed after delivery draft was created")
        with self._lock:
            episode = next(
                item
                for item in self._episodes[delivery.project_id]
                if item.id == delivery.episode_id
            )
            source = self._lipsync_assets.get(episode.source_asset_id)
            selected = [
                (role, self._lipsync_assets[asset_id])
                for asset_id, role in inputs["roles"].items()
            ]
        if source is None:
            raise DeliveryConflictError("delivery source asset is missing")
        now = datetime.now(UTC)
        manifest_json = _build_delivery_manifest(
            delivery_id=delivery.id,
            workspace_id=workspace_id,
            project_id=delivery.project_id,
            episode_id=delivery.episode_id,
            project_state_version=inputs["project_state_version"],
            source=source,
            selected_assets=selected,
            actor_id=payload.actor_id,
            approved_at=now,
            c2pa_requested=inputs["c2pa_requested"],
        )
        manifest = DeliveryManifestBuilder.build(**manifest_json)
        approved = delivery.model_copy(
            update={
                "status": "APPROVED",
                "state_version": delivery.state_version + 1,
                "manifest": manifest,
                "manifest_fingerprint": manifest.fingerprint,
                "approved_by": payload.actor_id,
                "approved_at": now,
                "updated_at": now,
            }
        )
        with self._lock:
            current = self._deliveries.get(delivery.id)
            if current is None or current.state_version != delivery.state_version:
                raise DeliveryConflictError("delivery changed during approval")
            self._deliveries[delivery.id] = approved
        return approved

    async def request_c2pa_signing(
        self, workspace_id: UUID, delivery_id: UUID
    ) -> DeliveryRead:
        with self._lock:
            delivery = self._deliveries.get(delivery_id)
            inputs = self._delivery_inputs.get(delivery_id)
        if delivery is None or delivery.workspace_id != workspace_id or inputs is None:
            raise ProjectNotFoundError(delivery_id)
        if not inputs.get("c2pa_requested", False):
            raise DeliveryConflictError("delivery was not created with c2pa_requested=True")
        if delivery.status != "APPROVED":
            raise DeliveryConflictError("only approved deliveries can be submitted for signing")
        if delivery.c2pa_status not in ("NOT_REQUESTED", "SIGN_FAILED"):
            raise DeliveryConflictError(
                f"c2pa_status must be NOT_REQUESTED or SIGN_FAILED, got {delivery.c2pa_status}"
            )
        updated = delivery.model_copy(
            update={
                "c2pa_status": "PENDING",
                "state_version": delivery.state_version + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        with self._lock:
            current = self._deliveries.get(delivery_id)
            if current is None or current.state_version != delivery.state_version:
                raise DeliveryConflictError("delivery changed during request")
            self._deliveries[delivery_id] = updated
        return updated

    async def complete_c2pa_signing(
        self,
        workspace_id: UUID,
        delivery_id: UUID,
        success: bool,
        credential_uri: str | None = None,
    ) -> DeliveryRead:
        with self._lock:
            delivery = self._deliveries.get(delivery_id)
        if delivery is None or delivery.workspace_id != workspace_id:
            raise ProjectNotFoundError(delivery_id)
        if delivery.c2pa_status != "SIGNING":
            raise DeliveryConflictError(
                f"c2pa_status must be SIGNING, got {delivery.c2pa_status}"
            )
        new_c2pa_status = "SIGNED" if success else "SIGN_FAILED"
        updated = delivery.model_copy(
            update={
                "c2pa_status": new_c2pa_status,
                "state_version": delivery.state_version + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        with self._lock:
            current = self._deliveries.get(delivery_id)
            if current is None or current.state_version != delivery.state_version:
                raise DeliveryConflictError("delivery changed during completion")
            self._deliveries[delivery_id] = updated
        return updated

    async def list_candidate_groups(
        self, workspace_id: UUID, project_id: UUID, job_id: UUID | None = None
    ) -> list[CandidateGroupRead]:
        await self.get_project(workspace_id, project_id)
        if job_id is not None:
            await self.get_job(workspace_id, job_id)
        with self._lock:
            groups = [
                item for item in self._candidate_groups.values() if item.project_id == project_id
            ]
            if job_id is None:
                return groups
            stage_ids = {
                variant.stage_run_id
                for group in groups
                for variant in group.variants
                if self._variant_stage_params.get(variant.id, {}).get("job_id") == str(job_id)
            }
            return [
                group
                for group in groups
                if any(item.stage_run_id in stage_ids for item in group.variants)
            ]

    async def submit_candidate_qc(
        self, workspace_id: UUID, variant_id: UUID, payload: CandidateQcCreate
    ) -> CandidateVariantRead:
        group, variant = await self._get_candidate_variant(workspace_id, variant_id)
        if variant.status != "GENERATED":
            raise CandidateConflictError("QC can only be submitted once for a generated variant")
        metric_names = {item.metric_name for item in payload.metrics}
        required_metrics = REQUIRED_QC_METRICS_BY_PURPOSE.get(group.purpose)
        if required_metrics and not required_metrics.issubset(metric_names):
            missing = sorted(required_metrics - metric_names)
            raise CandidateConflictError(
                f"{group.purpose} QC evidence is incomplete: {missing}"
            )
        now = datetime.now(UTC)
        metrics = tuple(
            QcMetricRead(id=uuid4(), created_at=now, **item.model_dump())
            for item in payload.metrics
        )
        if any(item.hard_failure or item.verdict == "FAIL" for item in payload.metrics):
            status = "QC_FAILED"
        elif any(item.verdict == "REVIEW" for item in payload.metrics):
            status = "REVIEW"
        else:
            status = "QC_PASSED"
        changed = variant.model_copy(
            update={"status": status, "qc_results": metrics, "updated_at": now}
        )
        self._replace_memory_variant(group, changed)
        return changed

    async def adopt_candidate(
        self, workspace_id: UUID, group_id: UUID, payload: CandidateAdopt
    ) -> CandidateGroupRead:
        with self._lock:
            group = self._candidate_groups.get(group_id)
        if group is None:
            raise ProjectNotFoundError(group_id)
        await self.get_project(workspace_id, group.project_id)
        if group.state_version != payload.expected_state_version:
            raise CandidateConflictError("candidate group state version mismatch")
        if group.status != "OPEN" or group.adopted_variant_id is not None:
            raise CandidateConflictError("candidate group already has an adopted variant")
        selected = next((item for item in group.variants if item.id == payload.variant_id), None)
        if selected is None:
            raise ProjectNotFoundError(payload.variant_id)
        if selected.status != "QC_PASSED":
            raise CandidateConflictError("only a QC_PASSED variant can be adopted")
        params = self._variant_stage_params.get(selected.id)
        if params:
            if "lipsync_request" in params:
                request = params["lipsync_request"]
                snapshot = request["rights"]
                operation = "lipsync"
                market = request["target_market"]
                language = request["target_language"]
            else:
                request = params["tts_request"]
                snapshot = request["voice_release"]["rights"]
                operation = "voice_clone"
                market = request["localized"]["target_market"]
                language = request["localized"]["target_language"]
            rights = await self._get_rights_release(
                workspace_id, UUID(snapshot["rights_release_id"])
            )
            if rights.state_version != int(snapshot["state_version"]):
                raise CandidateConflictError("RIGHTS_BLOCKED: RIGHTS_STATE_CHANGED")
            decision = evaluate_rights_release(
                rights,
                RightsExecutionCheck(
                    operation=operation,
                    market=market,
                    language=language,
                    commercial_use=request.get("commercial_use", True),
                ),
            )
            if not decision.allowed:
                raise CandidateConflictError(
                    f"RIGHTS_BLOCKED: {','.join(decision.reason_codes)}"
                )
        now = datetime.now(UTC)
        changed = group.model_copy(
            update={
                "status": "ADOPTED",
                "state_version": group.state_version + 1,
                "adopted_variant_id": selected.id,
                "variants": tuple(
                    item.model_copy(
                        update={
                            "status": "ADOPTED" if item.id == selected.id else "REJECTED",
                            "updated_at": now,
                        }
                    )
                    for item in group.variants
                ),
                "updated_at": now,
            }
        )
        with self._lock:
            self._candidate_groups[group.id] = changed
        return changed

    async def _get_candidate_variant(
        self, workspace_id: UUID, variant_id: UUID
    ) -> tuple[CandidateGroupRead, CandidateVariantRead]:
        with self._lock:
            found = next(
                (
                    (group, variant)
                    for group in self._candidate_groups.values()
                    for variant in group.variants
                    if variant.id == variant_id
                ),
                None,
            )
        if found is None:
            raise ProjectNotFoundError(variant_id)
        await self.get_project(workspace_id, found[0].project_id)
        return found

    def _replace_memory_variant(
        self, group: CandidateGroupRead, changed: CandidateVariantRead
    ) -> None:
        updated = group.model_copy(
            update={
                "variants": tuple(
                    changed if item.id == changed.id else item for item in group.variants
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        with self._lock:
            self._candidate_groups[group.id] = updated

    async def get_job(self, workspace_id: UUID, job_id: UUID) -> JobRead:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ProjectNotFoundError(job_id)
        await self.get_project(workspace_id, job.project_id)
        return job

    async def create_rights_release(
        self, workspace_id: UUID, project_id: UUID, payload: RightsReleaseCreate
    ) -> RightsReleaseRead:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            current = next(
                (
                    item
                    for item in self._rights_releases.values()
                    if item.project_id == project_id
                    and item.subject_type == payload.subject_type
                    and item.subject_id == payload.subject_id
                    and item.revoked_at is None
                ),
                None,
            )
            if current is not None and payload.supersedes_release_id != current.id:
                raise RightsReleaseConflictError(
                    "current rights release must be explicitly superseded"
                )
            if current is None and payload.supersedes_release_id is not None:
                raise RightsReleaseConflictError("superseded rights release is not current")
            now = datetime.now(UTC)
            if current is not None:
                self._rights_releases[current.id] = current.model_copy(
                    update={
                        "status": "REVOKED",
                        "state_version": current.state_version + 1,
                        "revoked_at": now,
                        "revoked_by": payload.created_by,
                        "revocation_reason": "SUPERSEDED",
                        "updated_at": now,
                    }
                )
            version = 1 + max(
                (
                    item.version
                    for item in self._rights_releases.values()
                    if item.project_id == project_id
                    and item.subject_type == payload.subject_type
                    and item.subject_id == payload.subject_id
                ),
                default=0,
            )
            release = RightsReleaseRead(
                id=uuid4(),
                project_id=project_id,
                subject_type=payload.subject_type,
                subject_id=payload.subject_id,
                version=version,
                status="ACTIVE",
                state_version=1,
                allowed_operations=payload.allowed_operations,
                allowed_markets=payload.allowed_markets,
                allowed_languages=payload.allowed_languages,
                commercial_scope=payload.commercial_scope,
                valid_from=payload.valid_from,
                expires_at=payload.expires_at,
                minor_guardian_consent=payload.minor_guardian_consent,
                source_asset_ids=payload.source_asset_ids,
                evidence_uri=payload.evidence_uri,
                evidence_sha256=payload.evidence_sha256,
                supersedes_release_id=payload.supersedes_release_id,
                created_by=payload.created_by,
                created_at=now,
                updated_at=now,
            )
            self._rights_releases[release.id] = release
            return release

    async def list_rights_releases(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[RightsReleaseRead]:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            return [
                item for item in self._rights_releases.values() if item.project_id == project_id
            ]

    async def revoke_rights_release(
        self,
        workspace_id: UUID,
        release_id: UUID,
        actor_id: UUID,
        reason: str,
        expected_state_version: int,
    ) -> RightsReleaseRead:
        release = await self._get_rights_release(workspace_id, release_id)
        if release.state_version != expected_state_version:
            raise RightsReleaseConflictError("rights release state version mismatch")
        if release.status != "ACTIVE" or release.revoked_at is not None:
            raise RightsReleaseConflictError("rights release is already revoked")
        now = datetime.now(UTC)
        changed = release.model_copy(
            update={
                "status": "REVOKED",
                "state_version": release.state_version + 1,
                "revoked_at": now,
                "revoked_by": actor_id,
                "revocation_reason": reason,
                "updated_at": now,
            }
        )
        with self._lock:
            self._rights_releases[release.id] = changed
        return changed

    async def check_rights_release(
        self, workspace_id: UUID, release_id: UUID, request: RightsExecutionCheck
    ) -> RightsExecutionDecision:
        release = await self._get_rights_release(workspace_id, release_id)
        return evaluate_rights_release(release, request)

    async def _get_rights_release(
        self, workspace_id: UUID, release_id: UUID
    ) -> RightsReleaseRead:
        with self._lock:
            release = self._rights_releases.get(release_id)
        if release is None:
            raise ProjectNotFoundError(release_id)
        await self.get_project(workspace_id, release.project_id)
        return release

    async def create_artifact_release(
        self, workspace_id: UUID, project_id: UUID, payload: ArtifactReleaseCreate
    ) -> ArtifactReleaseRead:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            dependencies = set(payload.dependency_release_ids)
            if any(
                release_id not in self._releases
                or self._releases[release_id].project_id != project_id
                for release_id in dependencies
            ):
                raise ProjectNotFoundError("artifact dependency")
            if payload.supersedes_release_id:
                superseded = self._releases.get(payload.supersedes_release_id)
                if (
                    superseded is None
                    or superseded.project_id != project_id
                    or superseded.artifact_type != payload.artifact_type
                ):
                    raise ArtifactConflictError(
                        "superseded release must have the same artifact type"
                    )
            version = 1 + max(
                (
                    item.version
                    for item in self._releases.values()
                    if item.project_id == project_id and item.artifact_type == payload.artifact_type
                ),
                default=0,
            )
            now = datetime.now(UTC)
            release = ArtifactReleaseRead(
                id=uuid4(),
                project_id=project_id,
                artifact_type=payload.artifact_type,
                version=version,
                status="DRAFT",
                state_version=1,
                content_asset_id=payload.content_asset_id,
                supersedes_release_id=payload.supersedes_release_id,
                dependency_release_ids=tuple(sorted(dependencies)),
                created_at=now,
                updated_at=now,
            )
            self._releases[release.id] = release
            if payload.supersedes_release_id:
                self._invalidate_memory_graph(payload.supersedes_release_id)
            return release

    async def list_artifact_releases(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[ArtifactReleaseRead]:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            return [item for item in self._releases.values() if item.project_id == project_id]

    async def list_analysis_documents(
        self,
        workspace_id: UUID,
        project_id: UUID,
        episode_id: UUID | None = None,
        document_type: str | None = None,
    ) -> list[AnalysisDocumentRead]:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            return [
                item
                for item in self._analysis_documents
                if item.project_id == project_id
                and (episode_id is None or item.episode_id == episode_id)
                and (document_type is None or item.document_type == document_type)
            ]

    async def confirm_artifact_release(
        self, workspace_id: UUID, release_id: UUID, actor_id: UUID, expected_state_version: int
    ) -> ArtifactReleaseRead:
        release = await self._get_release(workspace_id, release_id)
        try:
            changed = confirm_release(
                _memory_state(release),
                actor_id=actor_id,
                expected_state_version=expected_state_version,
            )
        except InvalidArtifactTransitionError as exc:
            raise ArtifactConflictError(str(exc)) from exc
        return self._store_release_state(release, changed)

    async def publish_artifact_release(
        self, workspace_id: UUID, release_id: UUID, expected_state_version: int
    ) -> ArtifactReleaseRead:
        release = await self._get_release(workspace_id, release_id)
        with self._lock:
            dependencies = tuple(
                _memory_state(self._releases[item]) for item in release.dependency_release_ids
            )
        try:
            changed = publish_release(
                _memory_state(release),
                dependencies=dependencies,
                expected_state_version=expected_state_version,
            )
        except InvalidArtifactTransitionError as exc:
            raise ArtifactConflictError(str(exc)) from exc
        return self._store_release_state(release, changed)

    async def invalidate_artifact_release(
        self, workspace_id: UUID, release_id: UUID, expected_state_version: int
    ) -> list[ArtifactReleaseRead]:
        root = await self._get_release(workspace_id, release_id)
        if root.state_version != expected_state_version:
            raise ArtifactConflictError("artifact state version mismatch")
        with self._lock:
            pending = [root.id]
            visited: set[UUID] = set()
            changed: list[ArtifactReleaseRead] = []
            while pending:
                current_id = pending.pop()
                if current_id in visited:
                    continue
                visited.add(current_id)
                current = self._releases[current_id]
                if current.status != "STALE":
                    current = current.model_copy(
                        update={
                            "status": "STALE",
                            "state_version": current.state_version + 1,
                            "stale_at": datetime.now(UTC),
                            "updated_at": datetime.now(UTC),
                        }
                    )
                    self._releases[current.id] = current
                    changed.append(current)
                pending.extend(
                    item.id
                    for item in self._releases.values()
                    if current_id in item.dependency_release_ids
                )
            return changed

    async def _get_release(
        self, workspace_id: UUID, release_id: UUID
    ) -> ArtifactReleaseRead:
        with self._lock:
            release = self._releases.get(release_id)
        if release is None:
            raise ProjectNotFoundError(release_id)
        await self.get_project(workspace_id, release.project_id)
        return release

    def _store_release_state(
        self, release: ArtifactReleaseRead, state: ArtifactReleaseState
    ) -> ArtifactReleaseRead:
        changed = release.model_copy(
            update={
                "status": state.status,
                "state_version": state.state_version,
                "confirmed_by": state.confirmed_by,
                "confirmed_at": state.confirmed_at,
                "released_at": state.released_at,
                "stale_at": state.stale_at,
                "updated_at": datetime.now(UTC),
            }
        )
        with self._lock:
            self._releases[release.id] = changed
        return changed

    def _invalidate_memory_graph(self, root_release_id: UUID) -> list[ArtifactReleaseRead]:
        pending = [root_release_id]
        visited: set[UUID] = set()
        changed: list[ArtifactReleaseRead] = []
        now = datetime.now(UTC)
        while pending:
            current_id = pending.pop()
            if current_id in visited:
                continue
            visited.add(current_id)
            current = self._releases[current_id]
            if current.status != "STALE":
                current = current.model_copy(
                    update={
                        "status": "STALE",
                        "state_version": current.state_version + 1,
                        "stale_at": now,
                        "updated_at": now,
                    }
                )
                self._releases[current.id] = current
                changed.append(current)
            pending.extend(
                item.id
                for item in self._releases.values()
                if current_id in item.dependency_release_ids
            )
        return changed

    async def create_upload_session(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        payload: MultipartInit,
        object_key: str,
        provider_upload_id: str,
    ) -> UploadRead:
        await self.get_project(workspace_id, payload.project_id)
        upload = UploadRead(
            upload_id=upload_id,
            project_id=payload.project_id,
            object_key=object_key,
            size_bytes=payload.size_bytes,
            status="UPLOADING",
        )
        record = UploadRecord(
            upload=upload,
            provider_upload_id=provider_upload_id,
            declared_sha256=payload.sha256,
            content_type=payload.content_type,
            part_size_bytes=payload.part_size_bytes,
            filename=payload.filename,
            episode_no=payload.episode_no,
        )
        with self._lock:
            self._uploads[upload_id] = record
        return upload

    async def get_upload(self, workspace_id: UUID, upload_id: UUID) -> UploadRecord:
        with self._lock:
            record = self._uploads.get(upload_id)
        if record is None:
            raise ProjectNotFoundError(upload_id)
        await self.get_project(workspace_id, record.upload.project_id)
        return record

    async def find_active_upload(
        self,
        workspace_id: UUID,
        project_id: UUID,
        sha256: str,
    ) -> UploadRecord | None:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            matches = [
                record
                for record in self._uploads.values()
                if record.upload.project_id == project_id
                and record.declared_sha256 == sha256
                and record.upload.status == "UPLOADING"
            ]
        return matches[-1] if matches else None

    async def record_upload_part(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        part: UploadPart,
    ) -> UploadRead:
        record = await self.get_upload(workspace_id, upload_id)
        if record.upload.status != "UPLOADING":
            raise UploadConflictError(f"upload is already {record.upload.status}")
        if part.size_bytes > record.part_size_bytes:
            raise UploadConflictError("part exceeds declared part size")
        completed = {item.part_number: item for item in record.upload.completed_parts}
        completed[part.part_number] = part
        upload = record.upload.model_copy(
            update={"completed_parts": [completed[number] for number in sorted(completed)]}
        )
        with self._lock:
            self._uploads[upload_id] = UploadRecord(
                upload=upload,
                provider_upload_id=record.provider_upload_id,
                declared_sha256=record.declared_sha256,
                content_type=record.content_type,
                part_size_bytes=record.part_size_bytes,
                filename=record.filename,
                episode_no=record.episode_no,
            )
        return upload

    async def complete_upload(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        parts: list[UploadPart],
        object_checksum_sha256: str,
        object_uri: str,
        content_type: str,
        size_bytes: int,
    ) -> UploadRead:
        record = await self.get_upload(workspace_id, upload_id)
        if record.upload.status != "UPLOADING":
            raise UploadConflictError(f"upload is already {record.upload.status}")
        if record.declared_sha256 != object_checksum_sha256:
            raise UploadConflictError("object SHA-256 does not match upload declaration")
        if record.upload.size_bytes != size_bytes:
            raise UploadConflictError("stored object size does not match upload declaration")
        episode_id = uuid4()
        media_asset_id = uuid4()
        ingest_job_id = uuid4()
        completed = record.upload.model_copy(
            update={
                "status": "COMPLETED",
                "completed_parts": parts,
                "episode_id": episode_id,
                "media_asset_id": media_asset_id,
                "ingest_job_id": ingest_job_id,
            }
        )
        with self._lock:
            self._uploads[upload_id] = UploadRecord(
                upload=completed,
                provider_upload_id=record.provider_upload_id,
                declared_sha256=record.declared_sha256,
                content_type=content_type,
                part_size_bytes=record.part_size_bytes,
                filename=record.filename,
                episode_no=record.episode_no,
            )
            episodes = self._episodes.setdefault(record.upload.project_id, [])
            episode_no = record.episode_no or len(episodes) + 1
            episodes.append(
                EpisodeRead(
                    id=episode_id,
                    project_id=record.upload.project_id,
                    episode_no=episode_no,
                    title=record.filename,
                    processing_status="QUEUED",
                    source_asset_id=media_asset_id,
                )
            )
            self._jobs[ingest_job_id] = JobRead(
                id=ingest_job_id,
                project_id=record.upload.project_id,
                kind="EPISODE_INGEST",
                status=JobStatus.QUEUED,
                progress=0,
                total_stages=8,
                completed_stages=0,
            )
        return completed

    async def register_orphan_asset(
        self,
        workspace_id: UUID,
        project_id: UUID,
        object_uri: str,
        reason: str,
    ) -> None:
        await self.get_project(workspace_id, project_id)


def _memory_state(release: ArtifactReleaseRead) -> ArtifactReleaseState:
    return ArtifactReleaseState(
        release_id=release.id,
        status=ArtifactReleaseStatus(release.status),
        state_version=release.state_version,
        confirmed_by=release.confirmed_by,
        confirmed_at=release.confirmed_at,
        released_at=release.released_at,
        stale_at=release.stale_at,
    )


def _memory_model_state(release: ModelReleaseRead) -> ModelReleaseState:
    return ModelReleaseState(
        release_id=release.id,
        endpoint=release.endpoint,
        license_id=release.license_id,
        model_card_uri=release.model_card_uri,
        license_status=LicenseStatus(release.license_status),
        automation_status=AutomationStatus(release.automation_status),
        traffic_percent=release.traffic_percent,
        state_version=release.state_version,
        reviewed_by=release.reviewed_by,
        reviewed_at=release.reviewed_at,
        approved_benchmark_release_id=release.approved_benchmark_release_id,
    )
