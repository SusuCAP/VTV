# VTV Database ERD (ASCII)

Key relationships among the major entity groups.

```
WORKSPACE
│
└── PROJECT
    │
    ├── EXECUTION_CONTROLS (1:1)
    │
    ├── RIGHTS_RELEASES
    │
    ├── LOCALIZATION_RELEASES
    │
    ├── WORKFLOW_PLANS
    │   └── (shot_id, route, reason_codes, estimated_cost_usd)
    │
    ├── EPISODE
    │   │
    │   └── SHOT
    │       │
    │       ├── STAGE_RUN ─────────────────────────────────────────────┐
    │       │   │  (stage_type, status, priority, lease_owner)         │
    │       │   │                                                       │
    │       │   ├── STAGE_DEPENDENCIES (DAG edge)                      │
    │       │   │   └── depends_on → STAGE_RUN                        │
    │       │   │                                                       │
    │       │   ├── STAGE_ATTEMPT                                      │
    │       │   │   │  (attempt_no, modal_call_id, cost_usd)           │
    │       │   │   └── COST_EVENTS ◄──────────────────────────────────┘
    │       │   │
    │       │   └── CANDIDATE_GROUP
    │       │       │  (purpose, status, adopted_variant_id)
    │       │       │
    │       │       └── RENDER_VARIANT
    │       │               │  (variant_no, status, seed, output_asset_id)
    │       │               │
    │       │               └── QC_RESULTS
    │       │                   (metric_name, score, verdict, hard_failure)
    │       │
    │       └── CONTINUITY_SNAPSHOT
    │           │  (snapshot_version, continuity_fingerprint)
    │           ├── character_releases[]  ──► CHARACTER_RELEASE
    │           ├── look_states[]         ──► LOOK_STATE
    │           └── location_release_id  ──► LOCATION_RELEASE
    │
    ├── CHARACTER
    │   ├── CHARACTER_RELEASE
    │   │   └── (anchor_pack_uri, model_release_ids[])
    │   └── LOOK_STATE
    │       └── (episode_id, first_shot_no..last_shot_no, state_payload)
    │
    └── LOCATION
        └── LOCATION_RELEASE
            └── (anchor_pack_uri, model_release_ids[])


MODEL_RELEASE
│  (model_key, automation_status, traffic_percent)
│
├── MODEL_CAPABILITY_PROFILE (1:1)
│   └── (capabilities[], supported_resolutions[], conditioning_types[])
│
├── MODEL_ACCESS_PROFILE (1:1)
│   └── (weight_sha256, min_vram_gib, availability_status)
│
├── BENCHMARK_RELEASE
│   └── BENCHMARK_SAMPLE_RESULTS
│       (sample_id, critical, result)
│
├── BENCHMARK_RUN
│   └── (gpu_type, runtime_profile_id, p95_latency_seconds)
│
└── RUNTIME_PROFILE
    └── (profile_class, supported_gpu_types[], minimum_cuda_version)


DELIVERY
│  (episode_id, version, status, c2pa_status, manifest)
│
├── DELIVERY_ASSETS
│   └── MEDIA_ASSET (role: VIDEO / AUDIO / SUBTITLE / …)
│
└── PROVENANCE_MANIFEST
    └── (edit_chain[], human_approvals[], c2pa_embedded)


AUDIT_LOGS
└── (workspace_id, actor_id, action, target_type/id, before/after_state)

OUTBOX_EVENTS
└── (aggregate_type, aggregate_id, event_type, payload, published_at)
```

## Relationship Summary

| From | To | Cardinality | Notes |
|------|----|-------------|-------|
| workspace | projects | 1:N | all data workspace-scoped |
| project | episodes | 1:N | |
| episode | shots | 1:N | ordered by shot_no |
| shot | stage_runs | 1:N | multiple stage types per shot |
| stage_run | stage_dependencies | N:M (self) | DAG; no self-loops |
| stage_run | stage_attempts | 1:N | retry history |
| stage_run | candidate_groups | 1:N | groups per stage purpose |
| candidate_group | render_variants | 1:N | variants per generation run |
| render_variant | qc_results | 1:N | one row per metric/evaluator |
| stage_attempt | cost_events | 1:N | GPU + API cost attribution |
| project | execution_controls | 1:1 | PK = project_id |
| project | rights_releases | 1:N | per subject_type/subject_id |
| project | workflow_plans | 1:N | per shot + plan_version |
| project | localization_releases | 1:N | versioned locale config |
| project | characters | 1:N | cross-episode identity |
| character | character_releases | 1:N | versioned anchor packs |
| character | look_states | 1:N | per episode/shot range |
| project | locations | 1:N | scene clusters |
| location | location_releases | 1:N | versioned anchor packs |
| shot | continuity_snapshots | 1:N | frozen state per version |
| continuity_snapshot | character_releases | N:M (JSONB) | embedded array |
| continuity_snapshot | location_releases | N:1 | |
| model_release | model_capability_profile | 1:1 | |
| model_release | model_access_profile | 1:1 | |
| model_release | benchmark_releases | 1:N | |
| benchmark_release | benchmark_sample_results | 1:N | |
| model_release | benchmark_runs | 1:N | per GPU type |
| benchmark_run | runtime_profiles | N:1 | |
| episode | deliveries | 1:N | versioned delivery packages |
| delivery | delivery_assets | 1:N | media_asset roles |
| delivery | provenance_manifests | 1:N | C2PA provenance chain |
