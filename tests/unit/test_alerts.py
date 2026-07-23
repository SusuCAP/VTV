from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_schemas.alerts import AlertFilter, ProductionAlert
from vtv_schemas.concurrency import ConcurrencyPolicy

_VALID_ALERT = dict(
    alert_id="alert-001",
    project_id=uuid4(),
    severity="WARN",
    alert_type="budget_warning",
    message="Budget at 80%",
    created_at=datetime.now(UTC),
)


def test_production_alert_required_fields():
    alert = ProductionAlert(**_VALID_ALERT)
    assert alert.alert_id == "alert-001"
    assert alert.severity == "WARN"
    assert alert.alert_type == "budget_warning"
    assert alert.message == "Budget at 80%"


def test_severity_must_be_valid():
    with pytest.raises(ValidationError):
        ProductionAlert(**{**_VALID_ALERT, "severity": "DEBUG"})


def test_alert_type_enum_validation():
    with pytest.raises(ValidationError):
        ProductionAlert(**{**_VALID_ALERT, "alert_type": "unknown_type"})


def test_acknowledged_defaults_false():
    alert = ProductionAlert(**_VALID_ALERT)
    assert alert.acknowledged is False
    assert alert.acknowledged_by is None
    assert alert.acknowledged_at is None


def test_alert_filter_defaults():
    f = AlertFilter()
    assert f.severity is None
    assert f.alert_type is None
    assert f.acknowledged is None
    assert f.limit == 50
    assert f.offset == 0


def test_alert_filter_limit_offset_bounds():
    with pytest.raises(ValidationError):
        AlertFilter(limit=0)
    with pytest.raises(ValidationError):
        AlertFilter(limit=501)
    with pytest.raises(ValidationError):
        AlertFilter(offset=-1)


def test_concurrency_policy_defaults():
    policy = ConcurrencyPolicy()
    assert policy.max_concurrent_episodes == 3
    assert policy.max_concurrent_visual_stages == 8
    assert policy.max_concurrent_tts_stages == 10
    assert policy.max_concurrent_lipsync_stages == 5
    assert policy.max_concurrent_assembly_stages == 2
    assert policy.priority_episodes == ()


def test_get_stage_limit_per_type():
    policy = ConcurrencyPolicy()
    assert policy.get_stage_limit("VISUAL_GENERATE") == 8
    assert policy.get_stage_limit("TTS_GENERATE") == 10
    assert policy.get_stage_limit("LIPSYNC_GENERATE") == 5
    assert policy.get_stage_limit("ASSEMBLE_EPISODE") == 2
