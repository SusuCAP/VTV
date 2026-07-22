from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_schemas.model_hotupdate import ModelChangeover, ModelHotUpdateConfig

# ---------------------------------------------------------------------------
# ModelHotUpdateConfig
# ---------------------------------------------------------------------------


def test_model_hotupdate_config_defaults() -> None:
    cfg = ModelHotUpdateConfig(model_key="TTS")
    assert cfg.changeover_strategy == "drain_then_switch"
    assert cfg.max_drain_seconds == 300
    assert cfg.rollback_on_failure_rate == 0.5


def test_model_hotupdate_config_immediate_strategy() -> None:
    cfg = ModelHotUpdateConfig(model_key="LIPSYNC_L1", changeover_strategy="immediate")
    assert cfg.changeover_strategy == "immediate"


def test_model_hotupdate_config_invalid_strategy() -> None:
    with pytest.raises(ValidationError):
        ModelHotUpdateConfig(model_key="TTS", changeover_strategy="hot_swap")


def test_model_hotupdate_config_rollback_rate_bounds() -> None:
    # valid bounds
    cfg_low = ModelHotUpdateConfig(model_key="TTS", rollback_on_failure_rate=0.0)
    cfg_high = ModelHotUpdateConfig(model_key="TTS", rollback_on_failure_rate=1.0)
    assert cfg_low.rollback_on_failure_rate == 0.0
    assert cfg_high.rollback_on_failure_rate == 1.0

    with pytest.raises(ValidationError):
        ModelHotUpdateConfig(model_key="TTS", rollback_on_failure_rate=1.1)

    with pytest.raises(ValidationError):
        ModelHotUpdateConfig(model_key="TTS", rollback_on_failure_rate=-0.1)


def test_model_hotupdate_config_max_drain_seconds_bounds() -> None:
    cfg = ModelHotUpdateConfig(model_key="TTS", max_drain_seconds=3600)
    assert cfg.max_drain_seconds == 3600
    with pytest.raises(ValidationError):
        ModelHotUpdateConfig(model_key="TTS", max_drain_seconds=3601)


# ---------------------------------------------------------------------------
# ModelChangeover
# ---------------------------------------------------------------------------


def test_model_changeover_fields() -> None:
    now = datetime.now(UTC)
    changeover = ModelChangeover(
        model_key="TTS",
        previous_release_id=uuid4(),
        new_release_id=uuid4(),
        strategy="drain_then_switch",
        triggered_by="operator@example.com",
        started_at=now,
    )
    assert changeover.rolled_back is False
    assert changeover.completed_at is None
    assert changeover.rollback_reason is None
    assert changeover.stages_completed_with_new == 0
