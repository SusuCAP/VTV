from uuid import uuid4

import pytest
from vtv_db.model_registry import (
    AutomationStatus,
    InvalidModelReleaseTransitionError,
    LicenseStatus,
    ModelReleaseState,
    review_license,
    set_automation_status,
)


def _state() -> ModelReleaseState:
    return ModelReleaseState(
        release_id=uuid4(),
        endpoint="https://models.example.test/infer",
        license_id="license-1",
        model_card_uri="s3://registry/cards/model.json",
    )


def test_approved_release_can_progress_canary_to_active() -> None:
    approved = review_license(
        _state(),
        decision=LicenseStatus.APPROVED,
        actor_id=uuid4(),
        expected_state_version=1,
    )
    canary = set_automation_status(
        approved,
        target=AutomationStatus.CANARY,
        traffic_percent=10,
        expected_state_version=2,
    )
    active = set_automation_status(
        canary,
        target=AutomationStatus.ACTIVE,
        traffic_percent=100,
        expected_state_version=3,
    )
    assert active.automation_status is AutomationStatus.ACTIVE
    assert active.state_version == 4


def test_unapproved_release_cannot_receive_traffic() -> None:
    with pytest.raises(InvalidModelReleaseTransitionError, match="license"):
        set_automation_status(
            _state(),
            target=AutomationStatus.CANARY,
            traffic_percent=5,
            expected_state_version=1,
        )


@pytest.mark.parametrize(
    ("target", "traffic"),
    [(AutomationStatus.CANARY, 100), (AutomationStatus.ACTIVE, 99)],
)
def test_automation_status_enforces_traffic_range(
    target: AutomationStatus, traffic: int
) -> None:
    approved = review_license(
        _state(),
        decision=LicenseStatus.APPROVED,
        actor_id=uuid4(),
        expected_state_version=1,
    )
    with pytest.raises(InvalidModelReleaseTransitionError, match="traffic"):
        set_automation_status(
            approved,
            target=target,
            traffic_percent=traffic,
            expected_state_version=2,
        )
