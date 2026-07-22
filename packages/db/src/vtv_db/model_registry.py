from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID


class LicenseStatus(StrEnum):
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AutomationStatus(StrEnum):
    OBSERVE = "OBSERVE"
    CANARY = "CANARY"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class InvalidModelReleaseTransitionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ModelReleaseState:
    release_id: UUID
    endpoint: str
    license_id: str
    model_card_uri: str
    license_status: LicenseStatus = LicenseStatus.REVIEW
    automation_status: AutomationStatus = AutomationStatus.OBSERVE
    traffic_percent: int = 0
    state_version: int = 1
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    approved_benchmark_release_id: UUID | None = None


def canary_receives_job(job_id: UUID, model_key: str, traffic_percent: int) -> bool:
    if not 0 <= traffic_percent <= 100:
        raise ValueError("traffic_percent must be between 0 and 100")
    bucket = int.from_bytes(
        sha256(f"{job_id}:{model_key}".encode()).digest()[:4], "big"
    ) % 100 + 1
    return bucket <= traffic_percent


def review_license(
    state: ModelReleaseState,
    *,
    decision: LicenseStatus,
    actor_id: UUID,
    expected_state_version: int,
    now: datetime | None = None,
) -> ModelReleaseState:
    _check_version(state, expected_state_version)
    if decision is LicenseStatus.REVIEW:
        raise InvalidModelReleaseTransitionError("license review decision must be final")
    if state.automation_status in {AutomationStatus.CANARY, AutomationStatus.ACTIVE}:
        raise InvalidModelReleaseTransitionError("disable automated traffic before license change")
    return replace(
        state,
        license_status=decision,
        state_version=state.state_version + 1,
        reviewed_by=actor_id,
        reviewed_at=now or datetime.now(UTC),
    )


def set_automation_status(
    state: ModelReleaseState,
    *,
    target: AutomationStatus,
    traffic_percent: int,
    expected_state_version: int,
) -> ModelReleaseState:
    _check_version(state, expected_state_version)
    allowed = {
        AutomationStatus.OBSERVE: {
            AutomationStatus.CANARY,
            AutomationStatus.ACTIVE,
            AutomationStatus.DISABLED,
        },
        AutomationStatus.CANARY: {AutomationStatus.ACTIVE, AutomationStatus.DISABLED},
        AutomationStatus.ACTIVE: {AutomationStatus.DISABLED},
        AutomationStatus.DISABLED: {AutomationStatus.OBSERVE},
    }
    if target not in allowed[state.automation_status]:
        raise InvalidModelReleaseTransitionError(
            f"invalid automation transition {state.automation_status} -> {target}"
        )
    if target in {AutomationStatus.CANARY, AutomationStatus.ACTIVE}:
        _assert_admissible(state)
    expected_traffic = {
        AutomationStatus.OBSERVE: range(0, 1),
        AutomationStatus.CANARY: range(1, 100),
        AutomationStatus.ACTIVE: range(100, 101),
        AutomationStatus.DISABLED: range(0, 1),
    }
    if traffic_percent not in expected_traffic[target]:
        raise InvalidModelReleaseTransitionError(
            f"invalid traffic percent {traffic_percent} for {target}"
        )
    return replace(
        state,
        automation_status=target,
        traffic_percent=traffic_percent,
        state_version=state.state_version + 1,
    )


def _assert_admissible(state: ModelReleaseState) -> None:
    if state.license_status is not LicenseStatus.APPROVED:
        raise InvalidModelReleaseTransitionError("model license is not approved")
    if not state.license_id.strip() or not state.model_card_uri.strip():
        raise InvalidModelReleaseTransitionError("model license and model card are required")
    if not state.endpoint.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise InvalidModelReleaseTransitionError("model endpoint must use HTTPS or localhost")
    if state.approved_benchmark_release_id is None:
        raise InvalidModelReleaseTransitionError("model release has no approved benchmark release")


def _check_version(state: ModelReleaseState, expected: int) -> None:
    if state.state_version != expected:
        raise InvalidModelReleaseTransitionError(
            "model release state version mismatch: "
            f"expected {expected}, actual {state.state_version}"
        )
