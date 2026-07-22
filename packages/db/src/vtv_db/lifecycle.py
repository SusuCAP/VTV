from vtv_schemas.enums import StageStatus


class InvalidStageTransitionError(ValueError):
    pass


ALLOWED_STAGE_TRANSITIONS: dict[StageStatus, frozenset[StageStatus]] = {
    StageStatus.PENDING: frozenset({StageStatus.READY, StageStatus.CANCELLED, StageStatus.STALE}),
    StageStatus.READY: frozenset({StageStatus.RUNNING, StageStatus.CANCELLED, StageStatus.STALE}),
    StageStatus.RUNNING: frozenset(
        {
            StageStatus.OUTPUT_READY,
            StageStatus.EXECUTION_FAILED,
            StageStatus.CANCELLED,
            StageStatus.STALE,
        }
    ),
    StageStatus.OUTPUT_READY: frozenset(
        {StageStatus.COMPLETED, StageStatus.ADOPTED, StageStatus.CANCELLED, StageStatus.STALE}
    ),
    StageStatus.EXECUTION_FAILED: frozenset(
        {StageStatus.READY, StageStatus.CANCELLED, StageStatus.STALE}
    ),
    StageStatus.COMPLETED: frozenset({StageStatus.ADOPTED, StageStatus.STALE}),
    StageStatus.ADOPTED: frozenset({StageStatus.STALE}),
    StageStatus.CANCELLED: frozenset(),
    StageStatus.STALE: frozenset({StageStatus.READY, StageStatus.CANCELLED}),
}


def assert_stage_transition(current: StageStatus, target: StageStatus) -> None:
    if target not in ALLOWED_STAGE_TRANSITIONS[current]:
        raise InvalidStageTransitionError(f"illegal stage transition: {current} -> {target}")
