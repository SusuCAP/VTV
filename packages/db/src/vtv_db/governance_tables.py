"""SQLAlchemy table metadata for the post-MVP governance entities.

These tables are migration-owned and intentionally exposed through the same
``Base.metadata`` as the operational ORM models. Keeping the metadata complete
prevents schema diff tools and repository extensions from silently omitting
continuity, release-governance, provenance, and review entities.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.sql import func

from .models import Base

metadata = Base.metadata


def _timestamps() -> tuple[Column, Column]:
    return (
        Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
        Column(
            "updated_at",
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )


characters = Table(
    "characters",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("display_name", String(200), nullable=False),
    Column("localized_name", String(200)),
    Column("gender", String(32)),
    Column("cluster_fingerprint", String(64)),
    Column("confirmed", Boolean, nullable=False, server_default="false"),
    Column("notes", Text),
    *_timestamps(),
    Index("ix_characters_project", "project_id"),
    Index("ix_characters_project_confirmed", "project_id", "confirmed"),
)

character_releases = Table(
    "character_releases",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("character_id", PGUUID(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("status", String(32), nullable=False, server_default="DRAFT"),
    Column("anchor_pack_uri", String(2048)),
    Column("anchor_pack_sha256", String(64)),
    Column("model_release_ids", JSONB, nullable=False, server_default="[]"),
    *_timestamps(),
    UniqueConstraint("character_id", "version", name="uq_character_releases_version"),
)

look_states = Table(
    "look_states",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("character_id", PGUUID(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
    Column("episode_id", PGUUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False),
    Column("first_shot_no", Integer, nullable=False),
    Column("last_shot_no", Integer),
    Column("state_payload", JSONB, nullable=False, server_default="{}"),
    Column("reference_uri", String(2048)),
    Column("confirmed", Boolean, nullable=False, server_default="false"),
    *_timestamps(),
)

locations = Table(
    "locations",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("display_name", String(200), nullable=False),
    Column("localized_name", String(200)),
    Column("location_type", String(32)),
    Column("cluster_fingerprint", String(64)),
    Column("confirmed", Boolean, nullable=False, server_default="false"),
    Column("notes", Text),
    *_timestamps(),
    Index("ix_locations_project", "project_id"),
)

location_releases = Table(
    "location_releases",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("location_id", PGUUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("status", String(32), nullable=False, server_default="DRAFT"),
    Column("anchor_pack_uri", String(2048)),
    Column("anchor_pack_sha256", String(64)),
    Column("model_release_ids", JSONB, nullable=False, server_default="[]"),
    *_timestamps(),
    UniqueConstraint("location_id", "version", name="uq_location_releases_version"),
)

anchor_assets = Table(
    "anchor_assets",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("anchor_type", String(32), nullable=False),
    Column("owner_type", String(64), nullable=False),
    Column("owner_id", PGUUID(as_uuid=True), nullable=False),
    Column("label", String(200), nullable=False),
    Column("asset_uri", String(2048), nullable=False),
    Column("asset_sha256", String(64), nullable=False),
    Column("media_type", String(128), nullable=False),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Index("ix_anchor_assets_project", "project_id"),
    Index("ix_anchor_assets_owner", "owner_type", "owner_id"),
)

continuity_snapshots = Table(
    "continuity_snapshots",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("episode_id", PGUUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False),
    Column("shot_id", PGUUID(as_uuid=True), nullable=False),
    Column("snapshot_version", Integer, nullable=False, server_default="1"),
    Column("character_releases", JSONB, nullable=False, server_default="[]"),
    Column("look_states", JSONB, nullable=False, server_default="[]"),
    Column("location_release_id", PGUUID(as_uuid=True), ForeignKey("location_releases.id")),
    Column("geometry_payload", JSONB, nullable=False, server_default="{}"),
    Column("neighbor_frames", JSONB, nullable=False, server_default="{}"),
    Column("localization_release_id", PGUUID(as_uuid=True)),
    Column("continuity_fingerprint", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    UniqueConstraint("shot_id", "snapshot_version", name="uq_continuity_snapshots_shot_version"),
)

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("workspace_id", PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")),
    Column("actor_id", PGUUID(as_uuid=True)),
    Column("action", String(128), nullable=False),
    Column("target_type", String(64)),
    Column("target_id", PGUUID(as_uuid=True)),
    Column("before_state", JSONB),
    Column("after_state", JSONB),
    Column("reason", Text),
    Column("ip_address", String(45)),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

cost_events = Table(
    "cost_events",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("workspace_id", PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("stage_run_id", PGUUID(as_uuid=True), ForeignKey("stage_runs.id", ondelete="SET NULL")),
    Column("stage_attempt_id", PGUUID(as_uuid=True), ForeignKey("stage_attempts.id", ondelete="SET NULL")),
    Column("event_type", String(64), nullable=False),
    Column("provider", String(64)),
    Column("resource_type", String(64)),
    Column("quantity", Numeric(20, 6), nullable=False, server_default="0"),
    Column("unit_price_usd", Numeric(14, 8), nullable=False, server_default="0"),
    Column("total_usd", Numeric(14, 6), nullable=False, server_default="0"),
    Column("gpu_type", String(64)),
    Column("model_release_id", PGUUID(as_uuid=True)),
    Column("provider_usage_id", String(256), unique=True),
    Column("occurred_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

runtime_profiles = Table(
    "runtime_profiles",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("profile_name", String(128), nullable=False, unique=True),
    Column("profile_class", String(64), nullable=False),
    Column("supported_gpu_types", JSONB, nullable=False, server_default="[]"),
    Column("minimum_cuda_version", String(16), nullable=False),
    Column("image_digest", String(128)),
    Column("framework_versions", JSONB, nullable=False, server_default="{}"),
    Column("validated_at", DateTime(timezone=True)),
    Column("validated_by", String(128)),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

workflow_plans = Table(
    "workflow_plans",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False),
    Column("episode_id", PGUUID(as_uuid=True), ForeignKey("episodes.id")),
    Column("shot_id", PGUUID(as_uuid=True), ForeignKey("shots.id")),
    Column("plan_version", Integer, nullable=False, server_default="1"),
    Column("route", String(2), nullable=False),
    Column("reason_codes", JSONB, nullable=False, server_default="[]"),
    Column("estimated_cost_usd", Numeric(10, 4)),
    Column("model_release_id", PGUUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    UniqueConstraint("shot_id", "plan_version"),
)

review_tasks = Table(
    "review_tasks",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("workspace_id", PGUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False),
    Column("task_type", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("assignee_id", PGUUID(as_uuid=True)),
    Column("shot_id", PGUUID(as_uuid=True)),
    Column("episode_id", PGUUID(as_uuid=True)),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    *_timestamps(),
)

localization_releases = Table(
    "localization_releases",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("source_locale", String(35), nullable=False),
    Column("target_locale", String(35), nullable=False),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    Column("status", String(32), nullable=False, server_default="DRAFT"),
    *_timestamps(),
    UniqueConstraint("project_id", "version"),
)

provenance_manifests = Table(
    "provenance_manifests",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False),
    Column("delivery_id", PGUUID(as_uuid=True)),
    Column("episode_id", PGUUID(as_uuid=True)),
    Column("manifest_version", Integer, nullable=False, server_default="1"),
    Column("source_asset_sha256", String(64), nullable=False),
    Column("edit_chain", JSONB, nullable=False, server_default="[]"),
    Column("human_approvals", JSONB, nullable=False, server_default="[]"),
    Column("c2pa_embedded", Boolean, nullable=False, server_default="false"),
    Column("manifest_uri", String(2048)),
    Column("manifest_sha256", String(64)),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

benchmark_runs = Table(
    "benchmark_runs",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("model_release_id", PGUUID(as_uuid=True), ForeignKey("model_releases.id"), nullable=False),
    Column("gpu_type", String(64), nullable=False),
    Column("runtime_profile_id", PGUUID(as_uuid=True), ForeignKey("runtime_profiles.id"), nullable=False),
    Column("dataset_version", String(64), nullable=False),
    Column("total_samples", Integer, nullable=False),
    Column("passed_samples", Integer, nullable=False),
    Column("critical_failure_rate", Numeric(6, 4), nullable=False),
    Column("cost_per_passed_second", Numeric(10, 6), nullable=False),
    Column("p95_latency_seconds", Numeric(10, 3), nullable=False),
    Column("human_reject_rate", Numeric(6, 4), nullable=False),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    UniqueConstraint("model_release_id", "dataset_version"),
)

provider_usage = Table(
    "provider_usage",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("workspace_id", PGUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False),
    Column("project_id", PGUUID(as_uuid=True), ForeignKey("projects.id")),
    Column("stage_attempt_id", PGUUID(as_uuid=True)),
    Column("provider", String(64), nullable=False),
    Column("model_id", String(256), nullable=False),
    Column("request_tokens", Integer, nullable=False, server_default="0"),
    Column("response_tokens", Integer, nullable=False, server_default="0"),
    Column("total_cost_usd", Numeric(14, 6), nullable=False),
    Column("vendor_request_id", String(256), unique=True),
    Column("data_retention_policy", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

model_capability_profiles = Table(
    "model_capability_profiles",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("model_release_id", PGUUID(as_uuid=True), ForeignKey("model_releases.id"), nullable=False, unique=True),
    Column("capabilities", JSONB, nullable=False, server_default="[]"),
    Column("supported_resolutions", JSONB, nullable=False, server_default="[]"),
    Column("max_frame_count", Integer),
    Column("reference_input_types", JSONB, nullable=False, server_default="[]"),
    Column("conditioning_types", JSONB, nullable=False, server_default="[]"),
    Column("known_limitations", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

model_access_profiles = Table(
    "model_access_profiles",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("model_release_id", PGUUID(as_uuid=True), ForeignKey("model_releases.id"), nullable=False, unique=True),
    Column("weight_download_url", String(2048)),
    Column("weight_sha256", String(64)),
    Column("checkpoint_filename", String(512)),
    Column("required_packages", JSONB, nullable=False, server_default="[]"),
    Column("min_cuda_version", String(16), nullable=False),
    Column("min_vram_gib", Integer),
    Column("reproducibility_config", JSONB, nullable=False, server_default="{}"),
    Column("availability_status", String(32), nullable=False, server_default="UNRELEASED"),
    Column("verified_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("workspace_id", PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("email", String(320), nullable=False),
    Column("display_name", String(200)),
    Column("role", String(32), nullable=False, server_default="developer"),
    *_timestamps(),
    UniqueConstraint("workspace_id", "email"),
)
