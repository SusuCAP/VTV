from datetime import UTC, datetime
from uuid import uuid4

import pytest
from vtv_db.releases import (
    ArtifactReleaseState,
    ArtifactReleaseStatus,
    InvalidArtifactTransitionError,
    confirm_release,
    propagate_stale,
    publish_release,
)


def test_confirm_and_publish_require_cas_and_released_dependencies() -> None:
    actor = uuid4()
    now = datetime(2026, 7, 22, tzinfo=UTC)
    draft = ArtifactReleaseState(release_id=uuid4())
    confirmed = confirm_release(draft, actor_id=actor, expected_state_version=1, now=now)
    dependency = ArtifactReleaseState(
        release_id=uuid4(), status=ArtifactReleaseStatus.RELEASED
    )

    released = publish_release(
        confirmed, dependencies=(dependency,), expected_state_version=2, now=now
    )

    assert released.status is ArtifactReleaseStatus.RELEASED
    assert released.state_version == 3
    assert released.confirmed_by == actor


def test_publish_rejects_unreleased_dependency() -> None:
    confirmed = ArtifactReleaseState(
        release_id=uuid4(), status=ArtifactReleaseStatus.CONFIRMED
    )
    with pytest.raises(InvalidArtifactTransitionError, match="dependencies"):
        publish_release(
            confirmed,
            dependencies=(ArtifactReleaseState(release_id=uuid4()),),
            expected_state_version=1,
        )


def test_stale_propagates_transitively_and_handles_cycles() -> None:
    bible, anchors, continuity, render = (uuid4() for _ in range(4))
    states = {
        release_id: ArtifactReleaseState(
            release_id=release_id, status=ArtifactReleaseStatus.RELEASED
        )
        for release_id in (bible, anchors, continuity, render)
    }
    graph = {
        bible: {anchors, continuity},
        anchors: {render},
        continuity: {render},
        render: {anchors},
    }

    changed = propagate_stale(bible, states, graph)

    assert set(changed) == {anchors, continuity, render}
    assert all(state.status is ArtifactReleaseStatus.STALE for state in changed.values())
