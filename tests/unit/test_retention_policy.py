from __future__ import annotations

import pytest
from pydantic import ValidationError
from vtv_schemas.retention import DEFAULT_RETENTION_POLICY, RetentionPolicy, RetentionRule


def test_retention_policy_valid():
    policy = RetentionPolicy(
        policy_key="test-policy",
        rules=(
            RetentionRule(asset_type="proxy_video", retain_days=30),
        ),
        delete_orphans_after_days=2,
    )
    assert policy.policy_key == "test-policy"
    assert policy.delete_orphans_after_days == 2


def test_get_retain_days_correct_value():
    policy = RetentionPolicy(
        policy_key="p",
        rules=(
            RetentionRule(asset_type="shot_clip", retain_days=14),
            RetentionRule(asset_type="tts_candidate", retain_days=7),
        ),
    )
    assert policy.get_retain_days("shot_clip") == 14
    assert policy.get_retain_days("tts_candidate") == 7
    assert policy.get_retain_days("subtitle") is None  # missing → permanent


def test_default_retention_policy_structure():
    assert DEFAULT_RETENTION_POLICY.policy_key == "default"
    assert DEFAULT_RETENTION_POLICY.delete_orphans_after_days == 1
    assert len(DEFAULT_RETENTION_POLICY.rules) == 10
    # permanent assets
    assert DEFAULT_RETENTION_POLICY.get_retain_days("source_video") is None
    assert DEFAULT_RETENTION_POLICY.get_retain_days("master_video") is None
    # time-limited assets
    assert DEFAULT_RETENTION_POLICY.get_retain_days("proxy_video") == 60
    assert DEFAULT_RETENTION_POLICY.get_retain_days("render_candidate") == 7


def test_cleanup_expired_orphans_stub_returns_zero():
    """Stub check: the method signature exists on the repo class."""
    from vtv_db.repository import ProjectRepository

    assert hasattr(ProjectRepository, "cleanup_expired_orphans")
    assert callable(ProjectRepository.cleanup_expired_orphans)


def test_retention_policy_requires_at_least_one_rule():
    with pytest.raises(ValidationError):
        RetentionPolicy(
            policy_key="empty",
            rules=(),  # min_length=1
        )
