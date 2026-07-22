from uuid import uuid4

import pytest
from vtv_db.dag import (
    EPISODE_BASELINE_DAG,
    StageDefinition,
    build_project_analysis_dag,
    validate_dag,
)


def test_project_analysis_dag_is_topologically_valid() -> None:
    episodes = (uuid4(), uuid4())
    dag = build_project_analysis_dag(episodes)

    validate_dag(dag)
    assert len(dag) == 11
    assert [stage.stage_type for stage in dag].count("INGEST_VALIDATE") == 2
    assert dag[-1].stage_type == "PROJECT_SYNTHESIS"
    assert len(dag[-1].depends_on) == 4
    assert {stage.episode_id for stage in dag[:-1]} == set(episodes)


def test_project_analysis_dag_rejects_empty_episode_set() -> None:
    with pytest.raises(ValueError, match="at least one episode"):
        build_project_analysis_dag(())


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
