import json
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from vtv_audio_worker import execute
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


def test_audio_worker_outputs_typed_dialogue_stem(tmp_path: Path) -> None:
    source = _audio_fixture(tmp_path / "source.wav")
    digest = sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "stems"
    job = StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        idempotency_key="audio-stems:test",
        stage_type="AUDIO_STEM_SEPARATION",
        input_assets=[
            AssetRef(
                uri=source.resolve().as_uri(),
                sha256=digest,
                media_type="audio/wav",
                size_bytes=source.stat().st_size,
            )
        ],
        output_prefix=output.resolve().as_uri(),
        runtime_profile_id="gpu-audio",
        observed_control_version=1,
        trace_id="audio-worker-test",
    )

    result = execute(job)

    assert result.status == "OUTPUT_READY"
    assert len(result.variants[0].output_assets) == 1
    dialogue = result.variants[0].output_assets[0]
    assert dialogue.metadata["stem_kind"] == "DIALOGUE"
    assert dialogue.sha256 == sha256((output / "dialogue.wav").read_bytes()).hexdigest()
    artifact = result.domain_artifacts[0]
    assert artifact.document_type == "AUDIO_STEMS"
    assert artifact.source_asset_sha256 == digest
    json.dumps(artifact.payload)
