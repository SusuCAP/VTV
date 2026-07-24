# VTV Database Schema

## Overview

45 tables across 21 migrations (0001–0021). See `migrations/` for SQL DDL.
All tenant data is workspace-scoped; cascade deletes propagate from `workspaces → projects → episodes/shots/…`.

| Migration | Description |
|-----------|-------------|
| 0001 | Core entities: workspaces, projects, episodes, shots, stage pipeline, media assets, events |
| 0002 | Job tracking and stage-run linkage |
| 0003 | Multipart upload sessions |
| 0004 | Artifact releases and release dependency DAG |
| 0005 | Analysis documents (JSON payloads from analysis stages) |
| 0006 | Model releases registry |
| 0007 | Benchmark releases and per-sample results |
| 0008 | Rights releases for talent/IP clearance |
| 0009 | Render variants and QC results |
| 0010 | Deliveries and delivery asset roles |
| 0011 | C2PA signing status on deliveries |
| 0012 | Evaluator releases |
| 0013 | Project archive support |
| 0014 | Characters, character releases, look states |
| 0015 | Locations and location releases |
| 0016 | Anchor assets and continuity snapshots |
| 0017 | Governance: audit logs, cost events, runtime profiles |
| 0018 | Workflow plans and human review tasks |
| 0019 | Localization releases |
| 0020 | Provenance manifests, benchmark runs, provider usage |
| 0021 | Model capability and access profiles |

---

## Core Entities

### workspaces
Tenant isolation root. Every data row in the system is owned by a workspace via cascade FK.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | gen_random_uuid() |
| name | VARCHAR(200) | Human label |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

Indexes: PK only (workspace_id is FK on almost every table).

---

### projects
Top-level production unit scoped to a workspace. Carries budget limits, locale, and quality profile.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id | UUID FK → workspaces | Cascade delete |
| name | VARCHAR(200) | |
| target_market | VARCHAR(16) | e.g. `CN`, `US` |
| locale | VARCHAR(35) | BCP-47 locale string |
| quality_profile | VARCHAR(64) | Pipeline quality tier |
| status | VARCHAR(40) | `DRAFT / ACTIVE / DONE / CANCELLED / ARCHIVED` |
| state_version | BIGINT | OCC version counter |
| budget_currency | VARCHAR(3) | ISO-4217; default `USD` |
| budget_warning_at | NUMERIC(14,4) | Soft budget alert threshold |
| budget_hard_limit | NUMERIC(14,4) | Hard stop; blocks stage dispatch |
| output_spec | JSONB | Target resolution, codec, format |
| archived_at | TIMESTAMPTZ | NULL = not archived (added migration 0013) |
| archive_reason | VARCHAR(500) | Optional reason text |

Indexes: `ix_projects_workspace_status(workspace_id, status)`, `ix_projects_archived(workspace_id, archived_at) WHERE archived_at IS NOT NULL`.

---

### episodes
One episode per production unit within a project. Holds source media reference and timing.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | Cascade delete |
| episode_no | INTEGER | 1-based, unique per project |
| title | VARCHAR(200) | Nullable |
| source_asset_id | UUID FK → media_assets | Set NULL on asset delete |
| duration_ms | BIGINT | Nullable until asset analyzed |

Indexes: UNIQUE(project_id, episode_no).

---

### shots
Shot-level segments within an episode. Defines timing window and routing classification.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| episode_id | UUID FK → episodes | Cascade delete |
| shot_no | INTEGER | 1-based, unique per episode |
| start_ms | BIGINT | Inclusive start in ms |
| end_ms | BIGINT | Exclusive end; CHECK end_ms > start_ms |
| route | VARCHAR(8) | `A`, `B`, `C`, `S` routing tier |
| reason_codes | JSONB | Array of classifier tags |

Indexes: UNIQUE(episode_id, shot_no).

---

### execution_controls
1-to-1 with projects (PK = project_id). Centralised pause/cancel/budget-block flags read by dispatchers.

| Column | Type | Notes |
|--------|------|-------|
| project_id | UUID PK FK → projects | Cascade delete |
| control_version | BIGINT | OCC counter |
| paused | BOOLEAN | Dispatcher skips PENDING runs when true |
| cancel_requested | BOOLEAN | Triggers graceful teardown |
| hard_budget_blocked | BOOLEAN | Set when budget_hard_limit exceeded |

---

## Job Orchestration

### jobs
High-level coarse-grained job tracking (e.g. ingest job, assembly job). Wraps multiple stage_runs.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | Cascade delete |
| kind | VARCHAR(64) | e.g. `INGEST`, `ASSEMBLY` |
| status | VARCHAR(32) | `QUEUED / RUNNING / DONE / FAILED` |
| idempotency_key | VARCHAR(255) | Unique per project |
| total_stages | INTEGER | Expected stage_run count |
| completed_stages | INTEGER | Incremented on completion |
| error_detail | JSONB | Nullable; last error |

Indexes: `ix_jobs_project_status(project_id, status)`, UNIQUE(project_id, idempotency_key).

---

### stage_runs
Central work-item table. Each row is one stage of the pipeline for a shot or episode.
Workers claim rows by setting `lease_owner` / `lease_expires_at`.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | Cascade delete |
| episode_id | UUID FK → episodes | Nullable |
| shot_id | UUID FK → shots | Nullable |
| candidate_group_id | UUID FK → candidate_groups | Set NULL on group delete |
| stage_type | VARCHAR(64) | e.g. `FACE_SWAP`, `LIPSYNC`, `ASSEMBLY` |
| status | VARCHAR(32) | `PENDING / RUNNING / DONE / FAILED / CANCELLED` |
| idempotency_key | VARCHAR(255) | Unique per project |
| model_release_id | UUID FK → model_releases | Nullable |
| runtime_profile_id | VARCHAR(100) | References runtime_profiles.profile_name |
| state_version | BIGINT | OCC counter |
| observed_control_version | BIGINT | Must match execution_controls to dispatch |
| priority | INTEGER | Higher = dispatch first |
| available_at | TIMESTAMPTZ | Earliest dispatch time |
| lease_owner | VARCHAR(200) | Worker ID holding current lease |
| lease_expires_at | TIMESTAMPTZ | Lease expiry for heartbeat |
| params | JSONB | Stage-specific input parameters |
| job_id | UUID FK → jobs | Nullable; links to parent job |

Indexes: `ix_stage_runs_claim(status, available_at, priority DESC)` — hot dispatcher index.
`ix_stage_runs_job_status(job_id, status)`.

---

### stage_dependencies
DAG edges between stage_runs. A stage_run cannot be dispatched until all upstream dependencies reach DONE.

| Column | Type | Notes |
|--------|------|-------|
| stage_run_id | UUID FK → stage_runs | Cascade delete |
| depends_on_stage_run_id | UUID FK → stage_runs | Cascade delete |

PK: (stage_run_id, depends_on_stage_run_id). CHECK: no self-loops.

---

### stage_attempts
Individual execution attempts for a stage_run. A run may have multiple attempts (retries).

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| stage_run_id | UUID FK → stage_runs | Cascade delete |
| attempt_no | INTEGER | 1-based, unique per run |
| status | VARCHAR(32) | `RUNNING / DONE / FAILED / CANCELLED` |
| modal_call_id | VARCHAR(200) | Modal function call ID |
| worker_id | VARCHAR(200) | Worker pod/container ID |
| lease_token | UUID | Rotating token for heartbeat validation |
| started_at | TIMESTAMPTZ | |
| finished_at | TIMESTAMPTZ | Nullable |
| usage | JSONB | Token/GPU usage snapshot |
| cost_usd | NUMERIC(14,6) | Attributed cost |
| error_class | VARCHAR(100) | Exception class name |
| error_detail | JSONB | Full traceback / context |

Indexes: UNIQUE(stage_run_id, attempt_no).

---

## Media & Ingest

### media_assets
Content-addressed binary assets. URI + SHA-256 pair is the canonical identity.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id | UUID FK → workspaces | Cascade delete |
| project_id | UUID FK → projects | Cascade delete |
| source_stage_run_id | UUID FK → stage_runs | Set NULL on run delete |
| object_uri | TEXT | S3 / object-store URI |
| sha256 | VARCHAR(64) | Hex SHA-256; CHECK regex |
| size_bytes | BIGINT | CHECK > 0 |
| content_type | VARCHAR(200) | MIME type |
| metadata | JSONB | Codec, resolution, duration, etc. |

Indexes: UNIQUE(workspace_id, sha256, object_uri).

---

### upload_sessions
Tracks multipart S3 uploads before they are confirmed and promoted to media_assets.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id | UUID FK → workspaces | Cascade delete |
| project_id | UUID FK → projects | Cascade delete |
| filename | VARCHAR(255) | Original filename |
| size_bytes | BIGINT | Declared upload size |
| part_size_bytes | BIGINT | 32 MiB–128 MiB range |
| declared_sha256 | VARCHAR(64) | Client-declared hash for integrity check |
| object_key | TEXT UNIQUE | S3 object key |
| provider_upload_id | TEXT | S3 multipart upload ID |
| status | VARCHAR(32) | `UPLOADING / COMPLETED / FAILED` |
| completed_parts | JSONB | Array of {part_no, etag} |
| episode_id | UUID FK → episodes | Set NULL on delete |
| media_asset_id | UUID FK → media_assets | Set NULL; populated on completion |
| ingest_job_id | UUID FK → jobs | Set NULL on delete |

Indexes: `ix_upload_sessions_project_status(project_id, status)`, UNIQUE(workspace_id, provider_upload_id).

---

### orphan_assets
Staging table for assets that failed to link to a stage_attempt. Cleaned up after `delete_after`.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | Cascade delete |
| stage_attempt_id | UUID FK → stage_attempts | Set NULL on delete |
| object_uri | TEXT | Storage path to clean |
| reason | VARCHAR(100) | Why it was orphaned |
| delete_after | TIMESTAMPTZ | GC deadline |

---

## Candidates & QC

### candidate_groups
Groups one or more render variants for a shot. Tracks which variant was adopted.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | Cascade delete |
| shot_id | UUID FK → shots | Nullable; cascade delete |
| purpose | VARCHAR(64) | e.g. `FACE_SWAP`, `LIPSYNC` |
| status | VARCHAR(16) | `OPEN / ADOPTED`; CHECK constraint |
| state_version | BIGINT | OCC counter |
| adopted_variant_id | UUID UNIQUE FK → render_variants | Set NULL on delete |

Indexes: UNIQUE on adopted_variant_id.

---

### render_variants
Individual output variants produced by a stage_run within a candidate_group.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| candidate_group_id | UUID FK → candidate_groups | Cascade delete |
| stage_run_id | UUID FK → stage_runs | Cascade delete |
| variant_no | INTEGER | 1-based per stage_run; CHECK >= 1 |
| status | VARCHAR(16) | `GENERATED / QC_PASSED / QC_FAILED / REVIEW / ADOPTED / REJECTED` |
| seed | BIGINT | RNG seed for reproducibility; nullable |
| output_asset_id | UUID FK → media_assets | RESTRICT delete |
| raw_metrics | JSONB | Raw model output metrics |
| allocated_cost | JSONB | Cost breakdown |

Indexes: `ix_render_variants_group_status(candidate_group_id, status)`, UNIQUE(stage_run_id, variant_no).

---

### qc_results
Per-metric QC evaluation record for a render_variant. Multiple rows per variant (one per metric/version/evaluator).

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| render_variant_id | UUID FK → render_variants | Cascade delete |
| metric_name | VARCHAR(100) | e.g. `lip_sync_score`, `face_consistency` |
| metric_version | VARCHAR(100) | Metric algorithm version |
| evaluator_release | VARCHAR(200) | Evaluator release identifier |
| score | DOUBLE PRECISION | 0.0–1.0; CHECK constraint |
| verdict | VARCHAR(16) | `PASS / FAIL / REVIEW` |
| hard_failure | BOOLEAN | True = blocks adoption regardless |
| details | JSONB | Sub-scores, frame-level data |

Indexes: `ix_qc_results_variant_verdict(render_variant_id, verdict)`, UNIQUE(render_variant_id, metric_name, metric_version, evaluator_release).

---

## Releases

### artifact_releases
Versioned binary artifact releases (scripts, translated scripts, audio masters, etc.).

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | Cascade delete |
| artifact_type | VARCHAR(64) | e.g. `SCRIPT`, `AUDIO_MASTER` |
| version | INTEGER | 1-based; UNIQUE per (project, artifact_type) |
| status | VARCHAR(32) | `DRAFT / CONFIRMED / RELEASED / STALE` |
| state_version | BIGINT | OCC counter |
| content_asset_id | UUID FK → media_assets | RESTRICT delete |
| supersedes_release_id | UUID FK → artifact_releases | Self-referential; Set NULL |
| confirmed_by | UUID | User ID; nullable |
| confirmed_at | TIMESTAMPTZ | Nullable |
| released_at | TIMESTAMPTZ | Nullable |

Indexes: `ix_artifact_releases_project_type_status(project_id, artifact_type, status)`.

### artifact_release_dependencies
DAG edges between artifact_releases. Used to block downstream releases until upstream is released.

| Column | Type | Notes |
|--------|------|-------|
| upstream_release_id | UUID FK → artifact_releases | Cascade delete |
| downstream_release_id | UUID FK → artifact_releases | Cascade delete |

PK: (upstream, downstream). CHECK: no self-loops.

---

### model_releases
Registry of AI model versions with licensing, routing, and traffic-percent tracking.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id | UUID FK → workspaces | Cascade delete |
| model_key | VARCHAR(64) | Logical model identifier |
| release_name | VARCHAR(200) | e.g. `v2.1.0-finetune-A` |
| provider | VARCHAR(100) | Infrastructure provider |
| endpoint | TEXT | Inference endpoint URL |
| license_status | VARCHAR(32) | `REVIEW / APPROVED / REJECTED` |
| automation_status | VARCHAR(32) | `OBSERVE / CANARY / ACTIVE / DISABLED` |
| traffic_percent | INTEGER | 0–100; canary traffic split |
| state_version | BIGINT | OCC counter |
| model_card_uri | TEXT | S3 URI to model card document |
| fallback_release_id | UUID FK → model_releases | Self-referential; Set NULL |
| approved_benchmark_release_id | UUID FK → benchmark_releases | Set NULL |

Indexes: `ix_model_releases_workspace_key_status(workspace_id, model_key, automation_status)`.

---

### rights_releases
Talent and IP rights clearance records. Exactly one non-revoked release per (project, subject_type, subject_id) enforced by partial unique index.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | Cascade delete |
| subject_type | VARCHAR(32) | e.g. `ACTOR`, `IP_ASSET` |
| subject_id | VARCHAR(128) | External talent or asset identifier |
| version | INTEGER | 1-based version |
| status | VARCHAR(16) | `ACTIVE / REVOKED` |
| allowed_operations | JSONB | Array of permitted operation codes |
| allowed_markets | JSONB | Array of market codes |
| commercial_scope | VARCHAR(32) | `RESEARCH_ONLY / COMMERCIAL` |
| valid_from | TIMESTAMPTZ | |
| expires_at | TIMESTAMPTZ | Nullable |
| evidence_uri | TEXT | S3 URI to signed consent document |
| evidence_sha256 | VARCHAR(64) | Hash of consent document |
| minor_guardian_consent | BOOLEAN | True if subject is a minor |

Indexes: `uq_rights_releases_current_subject(project_id, subject_type, subject_id) WHERE revoked_at IS NULL`, `ix_rights_releases_project_status`.

---

### evaluator_releases
Versioned evaluator configurations (metric definitions + thresholds) used by QC workers.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id | UUID FK → workspaces | Cascade delete |
| evaluator_key | VARCHAR(64) | Logical evaluator ID |
| version | INTEGER | 1-based |
| status | VARCHAR(16) | `ACTIVE / DEPRECATED` |
| metric_definitions | JSONB | Array of metric spec objects |
| thresholds | JSONB | Map of metric_name → threshold |
| state_version | BIGINT | OCC counter |

Indexes: `ix_evaluator_releases_key_status(workspace_id, evaluator_key, status)`.

---

### localization_releases
Versioned localization rules and terminology bundles for a project's target locale.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | |
| version | INTEGER | UNIQUE per project |
| status | VARCHAR(32) | `DRAFT / CONFIRMED / RELEASED / SUPERSEDED` |
| target_market | VARCHAR(16) | |
| locale | VARCHAR(35) | BCP-47 |
| rules_payload | JSONB | Grammar, tone, style rules |
| terminology_payload | JSONB | Glossary and forbidden terms |
| fingerprint | VARCHAR(64) | SHA-256 of payload for cache keying |

---

## Benchmarks

### benchmark_releases
Immutable benchmark run results proving a model_release met quality gates before promotion.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id | UUID FK → workspaces | Cascade delete |
| model_release_id | UUID FK → model_releases | Cascade delete |
| dataset_fingerprint | VARCHAR(64) | SHA-256 of dataset |
| policy_fingerprint | VARCHAR(64) | SHA-256 of policy spec |
| weights_sha256 | VARCHAR(64) | SHA-256 of model weights |
| approved | BOOLEAN | True = all gates passed |
| failed_gates | JSONB | Array of gate names that failed |
| evidence | JSONB | Evaluation evidence blob |
| report | JSONB | Summary report blob |

Indexes: `ix_benchmark_releases_workspace_model`. UNIQUE(model_release_id, dataset_fingerprint, policy_fingerprint, weights_sha256).

### benchmark_sample_results
Per-sample results for a benchmark_release.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| benchmark_release_id | UUID FK → benchmark_releases | Cascade delete |
| sample_id | VARCHAR(128) | Dataset sample identifier |
| source_sha256 | VARCHAR(64) | Hash of input sample |
| critical | BOOLEAN | True = failure is a hard gate block |
| result | JSONB | Detailed per-sample result |

UNIQUE(benchmark_release_id, sample_id).

### benchmark_runs
Performance benchmark results linking model_release + GPU type + runtime_profile.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| model_release_id | UUID FK → model_releases | |
| gpu_type | VARCHAR(64) | e.g. `H100`, `B200` |
| runtime_profile_id | UUID FK → runtime_profiles | |
| dataset_version | VARCHAR(64) | |
| total_samples / passed_samples | INTEGER | Throughput counts |
| critical_failure_rate | NUMERIC(6,4) | |
| p95_latency_seconds | NUMERIC(10,3) | |
| human_reject_rate | NUMERIC(6,4) | Human review rejection rate |

UNIQUE(model_release_id, dataset_version).

---

## Deliveries

### deliveries
Versioned episode delivery packages. Requires human approval before status moves to APPROVED.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id | UUID FK → workspaces | Cascade delete |
| project_id | UUID FK → projects | Cascade delete |
| episode_id | UUID FK → episodes | Cascade delete |
| version | INTEGER | 1-based; UNIQUE per episode |
| status | VARCHAR(16) | `DRAFT / APPROVED / REVOKED` |
| state_version | BIGINT | OCC counter |
| c2pa_status | VARCHAR(16) | `NOT_REQUESTED / PENDING / SIGNING / SIGNED / SIGN_FAILED` |
| c2pa_requested | BOOLEAN | |
| manifest | JSONB | Delivery manifest (NULL until approved) |
| manifest_fingerprint | VARCHAR(64) | SHA-256 of manifest |
| approved_by | VARCHAR(200) | Approver identifier |
| approved_at | TIMESTAMPTZ | |

Indexes: `ix_deliveries_project_episode_status`, `ix_deliveries_c2pa_status WHERE c2pa_status IN ('PENDING','SIGNING')`.

### delivery_assets
Join table linking deliveries to their constituent media_assets with a role label.

| Column | Type | Notes |
|--------|------|-------|
| delivery_id | UUID FK → deliveries | Cascade delete |
| asset_id | UUID FK → media_assets | RESTRICT delete |
| role | VARCHAR(32) | e.g. `VIDEO`, `AUDIO`, `SUBTITLE` |

PK: (delivery_id, asset_id). UNIQUE(delivery_id, role).

---

## Characters & Locations

### characters
Cross-episode character cluster identity, merged from face-embedding clustering.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | Cascade delete |
| display_name | VARCHAR(200) | Original name |
| localized_name | VARCHAR(200) | Target-market localized name; nullable |
| gender | VARCHAR(32) | Nullable |
| cluster_fingerprint | VARCHAR(64) | Hash of merged embeddings |
| confirmed | BOOLEAN | True = human reviewer verified |
| notes | TEXT | Nullable freetext |

Indexes: `ix_characters_project`, `ix_characters_project_confirmed`.

### character_releases
Versioned anchor pack releases for a character (reference images, voice samples).

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id / character_id | UUIDs | Cascade delete |
| version | INTEGER | 1-based; UNIQUE per character |
| status | VARCHAR(32) | `DRAFT / CONFIRMED / RELEASED / SUPERSEDED` |
| anchor_pack_uri | VARCHAR(2048) | S3 URI to anchor pack JSON |
| anchor_pack_sha256 | VARCHAR(64) | Integrity hash |
| model_release_ids | JSONB | Array of model release IDs used |

Indexes: `ix_character_releases_project(project_id, status)`.

### look_states
Per-episode costume state for a character covering a shot range.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| character_id | UUID FK → characters | Cascade delete |
| episode_id | UUID FK → episodes | Cascade delete |
| first_shot_no / last_shot_no | INTEGER | Shot range this look covers |
| state_payload | JSONB | `{hair, makeup, clothing, wounds, accessories, notes}` |
| reference_uri | VARCHAR(2048) | Representative reference image |
| confirmed | BOOLEAN | Human-reviewed flag |

Indexes: `ix_look_states_character`, `ix_look_states_episode`.

### locations
Scene location clusters (interior/exterior/vehicle/other), analogous to characters.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | Cascade delete |
| display_name / localized_name | VARCHAR(200) | |
| location_type | VARCHAR(32) | `INTERIOR / EXTERIOR / VEHICLE / OTHER` |
| cluster_fingerprint | VARCHAR(64) | |
| confirmed | BOOLEAN | |

### location_releases
Versioned anchor pack for a location (establishing shots, key surfaces, lighting).
Same lifecycle as `character_releases`. Columns mirror that table with `location_id` instead.

---

## Continuity

### anchor_assets
Named reference assets for characters, looks, locations, voices, and neighbor frames.
Owned by a polymorphic (owner_type, owner_id) reference.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | Cascade delete |
| anchor_type | VARCHAR(32) | `CHARACTER / LOOK / LOCATION / VOICE / NEIGHBOR` |
| owner_type / owner_id | VARCHAR(64) + UUID | Polymorphic FK |
| label | VARCHAR(200) | Human label |
| asset_uri / asset_sha256 | TEXT + VARCHAR(64) | Storage location and integrity |
| media_type | VARCHAR(128) | MIME type |
| metadata | JSONB | Pose, expression, lighting descriptors |

Indexes: `ix_anchor_assets_project`, `ix_anchor_assets_owner(owner_type, owner_id)`.

### continuity_snapshots
Immutable per-shot continuity state snapshot. Created before each visual production stage
to freeze the active character/look/location/geometry state at that shot boundary.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id / episode_id | UUIDs | Cascade delete |
| shot_id | UUID | References shots(id) — no FK constraint |
| snapshot_version | INTEGER | 1-based; UNIQUE per (shot_id, version) |
| character_releases | JSONB | Array of `{character_id, release_id}` |
| look_states | JSONB | Array of `{character_id, look_state_id}` |
| location_release_id | UUID FK → location_releases | Nullable |
| geometry_payload | JSONB | Screen direction, camera pose, depth URIs |
| neighbor_frames | JSONB | Prev tail + next head frame URIs |
| localization_release_id | UUID | Nullable |
| continuity_fingerprint | VARCHAR(64) | SHA-256 of entire snapshot payload |

Indexes: `ix_continuity_snapshots_project/episode/shot`.

---

## Governance

### audit_logs
Append-only record of all configuration, approval, retry, and deletion actions.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id | UUID FK → workspaces | Cascade delete |
| project_id | UUID FK → projects | Set NULL on delete |
| actor_id | UUID | User or service account |
| action | VARCHAR(128) | e.g. `project.cancel`, `model_release.approve` |
| target_type / target_id | VARCHAR(64) + UUID | Polymorphic target |
| before_state / after_state | JSONB | State snapshots (secrets redacted) |
| reason | TEXT | Nullable operator note |
| ip_address | VARCHAR(45) | IPv4 or IPv6 |

Indexes: `ix_audit_logs_workspace(workspace_id, created_at DESC)`, `ix_audit_logs_project`, `ix_audit_logs_target(target_type, target_id) WHERE target_type IS NOT NULL`.

---

### cost_events
Per-attempt cost attribution for GPU seconds, storage writes, and external API calls.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id / project_id | UUIDs FK | Cascade delete |
| stage_run_id | UUID FK → stage_runs | Set NULL on delete |
| stage_attempt_id | UUID FK → stage_attempts | Set NULL on delete |
| event_type | VARCHAR(64) | `GPU_USAGE / STORAGE_WRITE / EXTERNAL_API / CANCELLED` |
| provider | VARCHAR(64) | e.g. `modal`, `s3`, `anthropic` |
| resource_type | VARCHAR(64) | `gpu_seconds`, `storage_gib_seconds`, etc. |
| quantity | NUMERIC(20,6) | Resource units consumed |
| unit_price_usd / total_usd | NUMERIC | Price per unit and total cost |
| gpu_type | VARCHAR(64) | Nullable; `L40S`, `H100`, etc. |
| model_release_id | UUID | Nullable; for attribution |
| provider_usage_id | VARCHAR(256) UNIQUE | Dedup key from provider |

Indexes: `ix_cost_events_project(project_id, occurred_at DESC)`, `ix_cost_events_stage_run`.

---

### runtime_profiles
Immutable GPU-family / CUDA / container configuration records. Pre-seeded with 5 standard profiles.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| profile_name | VARCHAR(128) UNIQUE | e.g. `render-cuda12-mature` |
| profile_class | VARCHAR(64) | CHECK IN (`render-cuda12-mature`, `render-blackwell-validated`, `render-b300-cuda13`, `cpu-standard`, `audio-standard`) |
| supported_gpu_types | JSONB | Array of GPU strings |
| minimum_cuda_version | VARCHAR(16) | e.g. `12.0` |
| image_digest | VARCHAR(128) | Container image digest |
| framework_versions | JSONB | `{torch, diffusers, …}` version map |
| validated_at / validated_by | TIMESTAMPTZ + VARCHAR | Validation audit |

---

### model_capability_profiles
1-to-1 with model_releases. Declares what a model can accept and produce.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| model_release_id | UUID UNIQUE FK → model_releases | |
| capabilities | JSONB | Array of capability strings |
| supported_resolutions | JSONB | Array of `{w, h}` objects |
| max_frame_count | INTEGER | Nullable |
| reference_input_types | JSONB | Accepted conditioning input types |
| conditioning_types | JSONB | |
| known_limitations | TEXT | Freetext notes |

### model_access_profiles
1-to-1 with model_releases. Tracks weight download, VRAM requirements, and availability status.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| model_release_id | UUID UNIQUE FK → model_releases | |
| weight_download_url | VARCHAR(2048) | Nullable |
| weight_sha256 | VARCHAR(64) | Nullable |
| required_packages | JSONB | pip package list |
| min_cuda_version | VARCHAR(16) | |
| min_vram_gib | INTEGER | Nullable |
| availability_status | VARCHAR(32) | `AVAILABLE / GATED / UNRELEASED / BROKEN / OOM_RISK` |
| verified_at | TIMESTAMPTZ | Nullable |

---

## Workflow & Review

### workflow_plans
Shot-level routing plan generated by the orchestrator. Records the route, reason codes, and estimated cost.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id / episode_id / shot_id | UUIDs | FKs to projects/episodes/shots |
| plan_version | INTEGER | 1-based; UNIQUE per shot |
| route | VARCHAR(2) | `A / B / C / S` routing tier |
| reason_codes | JSONB | Array of classifier tags |
| estimated_cost_usd | NUMERIC(10,4) | Nullable pre-run estimate |
| model_release_id | UUID | Nullable; assigned model |

### review_tasks
Human-in-the-loop review tasks assigned to reviewers for character confirmation, dialogue review, etc.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id / project_id | UUIDs | |
| task_type | VARCHAR(64) | `CHARACTER_CONFIRMATION / SCENE_CONFIRMATION / DIALOGUE_REVIEW / EXCEPTION_SHOT / FINAL_SPOT_CHECK` |
| status | VARCHAR(32) | `PENDING / ASSIGNED / DONE / SKIPPED` |
| assignee_id | UUID | Nullable reviewer ID |
| shot_id / episode_id | UUIDs | Nullable scope |
| payload | JSONB | Task-specific context |

Indexes: `idx_review_tasks_project_status`, `idx_review_tasks_status_assignee`.

---

## Analysis

### analysis_documents
Structured JSON analysis outputs (scene breakdowns, face maps, audio transcripts, etc.) produced by analysis stage_runs.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id / episode_id | UUIDs | Cascade delete |
| source_stage_run_id | UUID FK → stage_runs | Cascade delete |
| media_asset_id | UUID FK → media_assets | RESTRICT delete |
| document_type | VARCHAR(64) | e.g. `FACE_MAP`, `SCENE_GRAPH` |
| schema_version | INTEGER | Payload schema version |
| payload | JSONB | Full analysis document |

Indexes: `ix_analysis_documents_project_type`, `ix_analysis_documents_payload_gin` (GIN index for JSONB queries).

---

## Provenance

### provenance_manifests
C2PA-compatible provenance records linking deliveries to their edit chain and human approvals.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id / delivery_id / episode_id | UUIDs | |
| manifest_version | INTEGER | |
| source_asset_sha256 | VARCHAR(64) | Origin media hash |
| edit_chain | JSONB | Ordered array of processing steps |
| human_approvals | JSONB | Array of approval events |
| c2pa_embedded | BOOLEAN | True = C2PA manifest embedded in output file |
| manifest_uri / manifest_sha256 | TEXT + VARCHAR(64) | Nullable signed manifest storage |

### provider_usage
Per-request external API usage records for billing reconciliation and data-retention auditing.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id | UUID FK → workspaces | |
| project_id / stage_attempt_id | UUIDs | Nullable |
| provider | VARCHAR(64) | e.g. `anthropic`, `openai` |
| model_id | VARCHAR(256) | Provider model string |
| request_tokens / response_tokens | INTEGER | Token counts |
| total_cost_usd | NUMERIC(14,6) | |
| vendor_request_id | VARCHAR(256) UNIQUE | Provider dedup ID |
| data_retention_policy | VARCHAR(128) | Retention classification label |

---

## Events & Housekeeping

### outbox_events
Transactional outbox for event publishing. Unpublished events are polled and forwarded to the message bus.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| workspace_id | UUID | Not FK (for cross-shard tolerance) |
| aggregate_type | VARCHAR(64) | e.g. `Project`, `StageRun` |
| aggregate_id | UUID | Source aggregate ID |
| event_type | VARCHAR(100) | e.g. `project.status_changed` |
| payload | JSONB | Full event payload |
| published_at | TIMESTAMPTZ | NULL = not yet published |
| publish_attempts | INTEGER | Retry counter |

Indexes: `ix_outbox_unpublished(published_at, created_at)` — hot poll index.

---

### deletion_tombstones
Soft-delete registry. Records resource deletions for async cleanup and audit.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| resource_type | VARCHAR(64) | e.g. `Project`, `MediaAsset` |
| resource_id | UUID | Deleted resource ID |
| requested_by | UUID | Nullable actor |
| reason | TEXT | Nullable reason |

UNIQUE(resource_type, resource_id).


