import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from vtv_analysis_worker import execute
from vtv_schemas.jobs import AssetRef, StageJob


def _json_asset(path: Path, payload: dict[str, object]) -> AssetRef:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return AssetRef(
        uri=path.resolve().as_uri(),
        sha256=sha256(path.read_bytes()).hexdigest(),
        media_type="application/json",
        size_bytes=path.stat().st_size,
    )


def test_project_synthesis_worker_combines_analysis_and_provenance(tmp_path: Path) -> None:
    audio = _json_asset(
        tmp_path / "audio.json",
        {
            "analysis": {
                "duration_seconds": 1,
                "language": "zh-CN",
                "speech": [],
                "transcript": [],
                "speakers": [],
            },
            "model_releases": {"asr_align": "asr@1"},
        },
    )
    vision = _json_asset(
        tmp_path / "vision.json",
        {
            "analysis": {
                "duration_seconds": 1,
                "people": [
                    {
                        "observation_id": "p1",
                        "track_id": "track-1",
                        "start_seconds": 0,
                        "end_seconds": 1,
                        "box": {"x": 0.2, "y": 0.1, "width": 0.5, "height": 0.8},
                        "face_visible": True,
                        "confidence": 1,
                    }
                ],
                "scenes": [],
                "ocr": [],
                "geometry": [
                    {
                        "start_seconds": 0,
                        "end_seconds": 1,
                        "subject_boxes": [],
                        "camera_motion": "static",
                    }
                ],
            },
            "model_releases": {"people": "people@1"},
        },
    )
    episode_one, episode_two = str(uuid4()), str(uuid4())
    inputs = [
        audio.model_copy(update={"metadata": {"episode_id": episode_one}}),
        vision.model_copy(update={"metadata": {"episode_id": episode_one}}),
        audio.model_copy(update={"metadata": {"episode_id": episode_two}}),
        vision.model_copy(update={"metadata": {"episode_id": episode_two}}),
    ]
    output = tmp_path / "output"
    job = StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        idempotency_key="test:project-synthesis",
        stage_type="PROJECT_SYNTHESIS",
        input_assets=inputs,
        output_prefix=output.resolve().as_uri(),
        runtime_profile_id="gpu-analysis",
        observed_control_version=1,
        params={"target_locale": "en-US"},
        trace_id="project-synthesis-test",
    )

    result = execute(job)

    payload = json.loads((output / "project-synthesis.json").read_text(encoding="utf-8"))
    assert result.status == "OUTPUT_READY"
    assert payload["synthesis"]["bible"]["target_locale"] == "en-US"
    assert payload["synthesis"]["bible"]["characters"][0]["character_id"] == "character-001"
    assert len(payload["synthesis"]["continuity"]) == 2
    assert {item["episode_id"] for item in payload["synthesis"]["continuity"]} == {
        episode_one,
        episode_two,
    }
    assert payload["model_releases"]["asr_align"] == "asr@1"
    assert payload["model_releases"]["project_synthesis"].endswith("@1")
