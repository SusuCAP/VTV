from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RetentionRule(BaseModel):
    asset_type: Literal[
        "source_video",  # permanent
        "master_video",  # permanent
        "proxy_video",  # 30-90 days
        "shot_clip",  # 14-30 days
        "render_candidate",  # 7-14 days (unadopted candidates)
        "tts_candidate",  # 7 days
        "qc_report",  # permanent
        "shot_list",  # permanent
        "subtitle",  # permanent
        "keyframe_preview",  # 7 days
    ]
    retain_days: int | None = Field(default=None, ge=0)
    # None = keep forever; 0 = purge immediately after task completes


class RetentionPolicy(BaseModel):
    policy_key: str = Field(min_length=1, max_length=64)
    rules: tuple[RetentionRule, ...] = Field(min_length=1)
    delete_orphans_after_days: int = Field(default=1, ge=0)

    def get_retain_days(self, asset_type: str) -> int | None:
        for rule in self.rules:
            if rule.asset_type == asset_type:
                return rule.retain_days
        return None  # default: permanent


# Default policy
DEFAULT_RETENTION_POLICY = RetentionPolicy(
    policy_key="default",
    rules=(
        RetentionRule(asset_type="source_video", retain_days=None),
        RetentionRule(asset_type="master_video", retain_days=None),
        RetentionRule(asset_type="proxy_video", retain_days=60),
        RetentionRule(asset_type="shot_clip", retain_days=14),
        RetentionRule(asset_type="render_candidate", retain_days=7),
        RetentionRule(asset_type="tts_candidate", retain_days=7),
        RetentionRule(asset_type="qc_report", retain_days=None),
        RetentionRule(asset_type="shot_list", retain_days=None),
        RetentionRule(asset_type="subtitle", retain_days=None),
        RetentionRule(asset_type="keyframe_preview", retain_days=7),
    ),
    delete_orphans_after_days=1,
)
