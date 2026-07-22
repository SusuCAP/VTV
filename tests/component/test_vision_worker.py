import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from vtv_analysis_worker import execute
from vtv_media import probe_media
from vtv_schemas.jobs import AssetRef, StageJob

pytest_plugins = ("tests.component.test_media_pipeline",)


def _asset(path: Path, media_type: str) -> AssetRef:
    return AssetRef(
        uri=path.resolve().as_uri(),
        sha256=sha256(path.read_bytes()).hexdigest(),
        media_type=media_type,
        size_bytes=path.stat().st_size,
    )


def test_vision_worker_consumes_video_and_continuous_shots(
    synthetic_video: Path, tmp_path: Path
) -> None:
    duration = probe_media(synthetic_video).duration_seconds
    midpoint = duration / 2
    shots = tmp_path / "shots.json"
    shots.write_text(
        json.dumps(
            {
                "shots": [
                    {"shot_no": 1, "start_seconds": 0, "end_seconds": midpoint},
                    {"shot_no": 2, "start_seconds": midpoint, "end_seconds": duration},
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "vision"
    job = StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        idempotency_key="test:vision",
        stage_type="VISION_ANALYSIS",
        input_assets=[
            _asset(synthetic_video, "video/mp4"),
            _asset(shots, "application/json"),
        ],
        output_prefix=output.resolve().as_uri(),
        runtime_profile_id="gpu-analysis",
        observed_control_version=1,
        trace_id="vision-component-test",
    )

    result = execute(job)

    payload = json.loads((output / "vision-analysis.json").read_text(encoding="utf-8"))
    assert result.status == "OUTPUT_READY"
    assert len(payload["analysis"]["people"]) == 2
    assert payload["analysis"]["geometry"][1]["end_seconds"] == duration
    assert payload["model_releases"]["people"] == "mock-person@1"
