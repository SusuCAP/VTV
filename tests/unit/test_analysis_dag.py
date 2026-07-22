import pytest
from vtv_db.dag import (
    EPISODE_BASELINE_DAG,
    PROJECT_ANALYSIS_DAG,
    StageDefinition,
    validate_dag,
)


def test_project_analysis_dag_is_topologically_valid() -> None:
    validate_dag(PROJECT_ANALYSIS_DAG)
    assert [stage.key for stage in PROJECT_ANALYSIS_DAG] == [
        "ingest",
        "proxy",
        "shots",
        "asr",
        "vision",
        "synthesis",
    ]
    assert PROJECT_ANALYSIS_DAG[-1].depends_on == ("asr", "vision")


def test_dag_rejects_forward_dependency() -> None:
    invalid = (
        StageDefinition("first", "FIRST", "cpu", ("second",)),
        StageDefinition("second", "SECOND", "cpu"),
    )
    with pytest.raises(ValueError, match="unresolved dependencies"):
        validate_dag(invalid)


def test_episode_baseline_dag_reaches_delivery_manifest() -> None:
    validate_dag(EPISODE_BASELINE_DAG)
    assert len(EPISODE_BASELINE_DAG) == 8
    assert EPISODE_BASELINE_DAG[0].stage_type == "INGEST_VALIDATE"
    assert EPISODE_BASELINE_DAG[-1].stage_type == "DELIVERY_MANIFEST"
