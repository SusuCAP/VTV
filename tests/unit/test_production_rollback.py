from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_db.repository import (
    EpisodeProductionRollback,
    EpisodeRollbackResult,
    ModelPromoteRequest,
)


def test_episode_production_rollback_valid() -> None:
    r = EpisodeProductionRollback(reason="rerun needed", actor_id="op-001")
    assert r.reason == "rerun needed"
    assert r.actor_id == "op-001"
    assert r.reset_to_route is None


def test_episode_rollback_result_fields() -> None:
    now = datetime.now(UTC)
    result = EpisodeRollbackResult(
        episode_id=uuid4(),
        stages_reset=3,
        candidates_rejected=2,
        reason="rerun needed",
        actor_id="admin",
        rolled_back_at=now,
    )
    assert result.stages_reset == 3
    assert result.candidates_rejected == 2
    assert result.reason == "rerun needed"


def test_stages_reset_ge_zero() -> None:
    with pytest.raises(ValidationError):
        EpisodeRollbackResult(
            episode_id=uuid4(),
            stages_reset=-1,
            candidates_rejected=0,
            reason="x",
            actor_id="a",
            rolled_back_at=datetime.now(UTC),
        )


def test_reason_min_length() -> None:
    with pytest.raises(ValidationError):
        EpisodeProductionRollback(reason="", actor_id="op-001")


def test_model_promote_request_valid() -> None:
    req = ModelPromoteRequest(expected_state_version=3, actor_id="reviewer")
    assert req.reason == "promoted-from-canary"
    assert req.expected_state_version == 3
    assert req.actor_id == "reviewer"


def test_actor_id_min_length() -> None:
    with pytest.raises(ValidationError):
        ModelPromoteRequest(expected_state_version=1, actor_id="")
