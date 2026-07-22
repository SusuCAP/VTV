from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class ArtifactReleaseStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    STALE = "STALE"


class InvalidArtifactTransitionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ArtifactReleaseState:
    release_id: UUID
    status: ArtifactReleaseStatus = ArtifactReleaseStatus.DRAFT
    state_version: int = 1
    confirmed_by: UUID | None = None
    confirmed_at: datetime | None = None
    released_at: datetime | None = None
    stale_at: datetime | None = None


def confirm_release(
    state: ArtifactReleaseState,
    *,
    actor_id: UUID,
    expected_state_version: int,
    now: datetime | None = None,
) -> ArtifactReleaseState:
    _check_version(state, expected_state_version)
    if state.status is not ArtifactReleaseStatus.DRAFT:
        raise InvalidArtifactTransitionError("only a DRAFT artifact can be confirmed")
    instant = now or datetime.now(UTC)
    return replace(
        state,
        status=ArtifactReleaseStatus.CONFIRMED,
        state_version=state.state_version + 1,
        confirmed_by=actor_id,
        confirmed_at=instant,
    )


def publish_release(
    state: ArtifactReleaseState,
    *,
    dependencies: tuple[ArtifactReleaseState, ...],
    expected_state_version: int,
    now: datetime | None = None,
) -> ArtifactReleaseState:
    _check_version(state, expected_state_version)
    if state.status is not ArtifactReleaseStatus.CONFIRMED:
        raise InvalidArtifactTransitionError("only a CONFIRMED artifact can be released")
    if any(dependency.status is not ArtifactReleaseStatus.RELEASED for dependency in dependencies):
        raise InvalidArtifactTransitionError("all artifact dependencies must be RELEASED")
    return replace(
        state,
        status=ArtifactReleaseStatus.RELEASED,
        state_version=state.state_version + 1,
        released_at=now or datetime.now(UTC),
    )


def propagate_stale(
    root_release_id: UUID,
    states: dict[UUID, ArtifactReleaseState],
    dependencies: dict[UUID, set[UUID]],
    *,
    now: datetime | None = None,
) -> dict[UUID, ArtifactReleaseState]:
    instant = now or datetime.now(UTC)
    changed: dict[UUID, ArtifactReleaseState] = {}
    pending = list(dependencies.get(root_release_id, set()))
    visited: set[UUID] = set()
    while pending:
        release_id = pending.pop()
        if release_id in visited:
            continue
        visited.add(release_id)
        state = states.get(release_id)
        if state is None:
            raise KeyError(f"missing artifact release state: {release_id}")
        if state.status is not ArtifactReleaseStatus.STALE:
            changed[release_id] = replace(
                state,
                status=ArtifactReleaseStatus.STALE,
                state_version=state.state_version + 1,
                stale_at=instant,
            )
        pending.extend(dependencies.get(release_id, set()))
    return changed


def _check_version(state: ArtifactReleaseState, expected: int) -> None:
    if state.state_version != expected:
        raise InvalidArtifactTransitionError(
            f"artifact state version mismatch: expected {expected}, actual {state.state_version}"
        )
