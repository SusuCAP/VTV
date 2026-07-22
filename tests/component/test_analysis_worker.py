import json
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from vtv_analysis_worker import execute
from vtv_schemas.jobs import AssetRef, StageJob

FFMPEG_AVAILABLE = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
pytestmark = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe are not installed")


def _audio_fixture(path: Path) -> Path:
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "48000",
            "-ac",
            "2",
            path,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.skip(f"local ffmpeg cannot create audio fixture: {result.stderr[-500:]}")
    return path


def test_asr_align_worker_writes_analysis_and_model_provenance(tmp_path: Path) -> None:
    source = _audio_fixture(tmp_path / "dialogue.wav")
    output_directory = tmp_path / "result"
    digest = sha256(source.read_bytes()).hexdigest()
    job = StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        idempotency_key="test:asr-align",
        stage_type="ASR_ALIGN",
        input_assets=[
            AssetRef(
                uri=source.resolve().as_uri(),
                sha256=digest,
                media_type="audio/wav",
                size_bytes=source.stat().st_size,
            )
        ],
        output_prefix=output_directory.resolve().as_uri(),
        runtime_profile_id="gpu-audio",
        observed_control_version=1,
        params={"language_hint": "zh-CN"},
        trace_id="analysis-component-test",
    )

    result = execute(job)

    assert result.status == "OUTPUT_READY"
    payload = json.loads((output_directory / "audio-analysis.json").read_text())
    assert payload["analysis"]["language"] == "zh-CN"
    assert payload["analysis"]["transcript"][0]["words"]
    assert payload["model_releases"] == result.variants[0].raw_metrics["model_releases"]
    assert payload["model_releases"]["asr_align"] == "mock-asr-align@1"
