import pytest
from vtv_db.lifecycle import InvalidStageTransitionError, assert_stage_transition
from vtv_schemas.enums import StageStatus


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (StageStatus.PENDING, StageStatus.READY),
        (StageStatus.READY, StageStatus.RUNNING),
        (StageStatus.RUNNING, StageStatus.OUTPUT_READY),
        (StageStatus.OUTPUT_READY, StageStatus.COMPLETED),
        (StageStatus.COMPLETED, StageStatus.ADOPTED),
        (StageStatus.EXECUTION_FAILED, StageStatus.READY),
        (StageStatus.STALE, StageStatus.READY),
    ],
)
def test_valid_stage_transitions(current: StageStatus, target: StageStatus) -> None:
    assert_stage_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (StageStatus.PENDING, StageStatus.ADOPTED),
        (StageStatus.READY, StageStatus.COMPLETED),
        (StageStatus.CANCELLED, StageStatus.READY),
        (StageStatus.ADOPTED, StageStatus.RUNNING),
    ],
)
def test_invalid_stage_transitions(current: StageStatus, target: StageStatus) -> None:
    with pytest.raises(InvalidStageTransitionError):
        assert_stage_transition(current, target)
