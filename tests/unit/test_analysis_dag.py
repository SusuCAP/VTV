import pytest
from vtv_db.dag import PROJECT_ANALYSIS_DAG, StageDefinition, validate_dag


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
