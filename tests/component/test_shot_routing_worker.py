from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from vtv_assemble_worker import AssembleWorker
from vtv_schemas.jobs import StageJob


def _job(tmp_path: Path, params: dict) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        idempotency_key="shot-routing:test",
        stage_type="SHOT_ROUTING",
        input_assets=[],
        output_prefix=(tmp_path / "shot_routing").resolve().as_uri(),
        runtime_profile_id="cpu-assemble",
        observed_control_version=1,
        params=params,
        trace_id="test-shot-routing",
    )


def _minimal_request(episode_id: str, shots: list[dict]) -> dict:
    return {
        "shot_routing_request": {
            "episode_id": episode_id,
            "shots": shots,
            "person_observations": [],
            "ocr_observations": [],
            "utterances": [],
        }
    }


def test_shot_routing_produces_workflow_plan_artifact(tmp_path: Path) -> None:
    episode_id = str(uuid4())
    shots = [
        {"shot_id": str(uuid4()), "shot_no": 1, "start_ms": 0, "end_ms": 2000},
        {"shot_id": str(uuid4()), "shot_no": 2, "start_ms": 2000, "end_ms": 4000},
    ]
    worker = AssembleWorker()
    result = worker.execute(_job(tmp_path, _minimal_request(episode_id, shots)))

    assert result.status == "OUTPUT_READY"
    assert len(result.variants[0].output_assets) == 1
    assert result.variants[0].output_assets[0].media_type == "application/json"

    artifact_types = {a.document_type for a in result.domain_artifacts}
    assert "WORKFLOW_PLAN" in artifact_types


def test_shot_routing_writes_workflow_plan_json(tmp_path: Path) -> None:
    episode_id = str(uuid4())
    shots = [
        {"shot_id": str(uuid4()), "shot_no": 1, "start_ms": 0, "end_ms": 3000},
    ]
    worker = AssembleWorker()
    result = worker.execute(_job(tmp_path, _minimal_request(episode_id, shots)))

    plan_asset = result.variants[0].output_assets[0]
    plan_path = Path(plan_asset.uri.removeprefix("file://"))
    plan = json.loads(plan_path.read_text())

    assert plan["schema_version"] == "vtv.workflow-plan.v1"
    assert plan["episode_id"] == episode_id
    assert plan["total_shots"] == 1
    assert len(plan["decisions"]) == 1
    assert plan["decisions"][0]["shot_no"] == 1


def test_shot_routing_routes_face_shot_to_character_replace(tmp_path: Path) -> None:
    episode_id = str(uuid4())
    shot_id = str(uuid4())
    person_obs = [
        {
            "observation_id": "obs-1",
            "track_id": "person-1",
            "start_seconds": 0.0,
            "end_seconds": 2.0,
            "face_visible": True,
            "box": {"x": 0.3, "y": 0.1, "width": 0.25, "height": 0.4},
            "confidence": 0.95,
        }
    ]
    shots = [{"shot_id": shot_id, "shot_no": 1, "start_ms": 0, "end_ms": 2000}]
    worker = AssembleWorker()
    result = worker.execute(
        _job(
            tmp_path,
            {
                "shot_routing_request": {
                    "episode_id": episode_id,
                    "shots": shots,
                    "person_observations": person_obs,
                    "ocr_observations": [],
                    "utterances": [],
                }
            },
        )
    )
    plan = json.loads(
        Path(result.variants[0].output_assets[0].uri.removeprefix("file://")).read_text()
    )
    assert plan["decisions"][0]["route"] == "C"


def test_shot_routing_routes_group_shot_to_full_regen(tmp_path: Path) -> None:
    episode_id = str(uuid4())
    shot_id = str(uuid4())
    # Three distinct track_ids → person_count = 3 → FULL_REGEN
    person_obs = [
        {
            "observation_id": f"obs-{i}",
            "track_id": f"person-{i}",
            "start_seconds": 0.0,
            "end_seconds": 2.0,
            "face_visible": True,
            "box": {"x": 0.0, "y": 0.0, "width": 0.1, "height": 0.1},
            "confidence": 0.9,
        }
        for i in range(3)
    ]
    shots = [{"shot_id": shot_id, "shot_no": 1, "start_ms": 0, "end_ms": 2000}]
    worker = AssembleWorker()
    result = worker.execute(
        _job(
            tmp_path,
            {
                "shot_routing_request": {
                    "episode_id": episode_id,
                    "shots": shots,
                    "person_observations": person_obs,
                    "ocr_observations": [],
                    "utterances": [],
                }
            },
        )
    )
    plan = json.loads(
        Path(result.variants[0].output_assets[0].uri.removeprefix("file://")).read_text()
    )
    assert plan["decisions"][0]["route"] == "F"


def test_shot_routing_routes_non_latin_ocr_to_subtitle_clean(tmp_path: Path) -> None:
    episode_id = str(uuid4())
    shot_id = str(uuid4())
    ocr_obs = [
        {
            "observation_id": "ocr-1",
            "start_seconds": 0.0,
            "end_seconds": 2.0,
            "text": "안녕하세요",
            "box": {"x": 0.1, "y": 0.8, "width": 0.4, "height": 0.1},
            "confidence": 0.98,
            "script": "Hangul",
        }
    ]
    shots = [{"shot_id": shot_id, "shot_no": 1, "start_ms": 0, "end_ms": 2000}]
    worker = AssembleWorker()
    result = worker.execute(
        _job(
            tmp_path,
            {
                "shot_routing_request": {
                    "episode_id": episode_id,
                    "shots": shots,
                    "person_observations": [],
                    "ocr_observations": ocr_obs,
                    "utterances": [],
                }
            },
        )
    )
    plan = json.loads(
        Path(result.variants[0].output_assets[0].uri.removeprefix("file://")).read_text()
    )
    assert plan["decisions"][0]["route"] == "B"


def test_shot_routing_preserves_shot_with_no_features(tmp_path: Path) -> None:
    episode_id = str(uuid4())
    shots = [
        {"shot_id": str(uuid4()), "shot_no": 1, "start_ms": 0, "end_ms": 1000},
    ]
    worker = AssembleWorker()
    result = worker.execute(_job(tmp_path, _minimal_request(episode_id, shots)))
    plan = json.loads(
        Path(result.variants[0].output_assets[0].uri.removeprefix("file://")).read_text()
    )
    assert plan["decisions"][0]["route"] == "A"


def test_shot_routing_fails_without_shot_routing_request(tmp_path: Path) -> None:
    import pytest

    worker = AssembleWorker()
    with pytest.raises(ValueError, match="shot_routing_request"):
        worker.execute(_job(tmp_path, {}))


def test_shot_routing_multi_shot_route_distribution(tmp_path: Path) -> None:
    episode_id = str(uuid4())
    shots = [
        {"shot_id": str(uuid4()), "shot_no": i, "start_ms": (i - 1) * 1000, "end_ms": i * 1000}
        for i in range(1, 4)
    ]
    worker = AssembleWorker()
    result = worker.execute(_job(tmp_path, _minimal_request(episode_id, shots)))
    plan = json.loads(
        Path(result.variants[0].output_assets[0].uri.removeprefix("file://")).read_text()
    )
    assert plan["total_shots"] == 3
    assert sum(plan["route_distribution"].values()) == 3
