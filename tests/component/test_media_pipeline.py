import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from vtv_media import detect_shots, extract_audio, generate_proxy, probe_media
from vtv_media_worker import execute
from vtv_schemas.jobs import AssetRef, StageJob

FFMPEG_AVAILABLE = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
pytestmark = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe are not installed")


@pytest.fixture
def synthetic_video(tmp_path: Path) -> Path:
    output = tmp_path / "two-scenes.mp4"
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x240:d=0.6:r=24",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:d=0.6:r=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.2",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            output,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.skip(f"local ffmpeg cannot create fixture: {result.stderr[-500:]}")
    return output


def test_probe_proxy_audio_and_shot_detection(synthetic_video: Path, tmp_path: Path) -> None:
    probe = probe_media(synthetic_video)
    assert probe.duration_seconds == pytest.approx(1.2, abs=0.15)
    assert probe.video_streams[0].width == 320
    assert probe.audio_streams[0].sample_rate

    proxy = generate_proxy(synthetic_video, tmp_path / "proxy.mp4", max_width=240)
    proxy_probe = probe_media(proxy)
    assert proxy_probe.video_streams[0].width == 240

    audio = extract_audio(synthetic_video, tmp_path / "dialogue.wav")
    assert audio.stat().st_size > 1_000

    shots = detect_shots(synthetic_video, threshold=0.20)
    assert len(shots) >= 2
    assert any(0.4 <= shot.end_seconds <= 0.8 for shot in shots)


def _job(stage_type: str, source: Path, output: Path) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        idempotency_key=f"test:{stage_type}",
        stage_type=stage_type,
        input_assets=[
            AssetRef(
                uri=source.resolve().as_uri(),
                sha256="a" * 64,
                media_type="video/mp4",
                size_bytes=source.stat().st_size,
            )
        ],
        output_prefix=output.resolve().as_uri(),
        runtime_profile_id="cpu-media",
        observed_control_version=1,
        trace_id="media-component-test",
    )


@pytest.mark.parametrize(
    ("stage_type", "expected_name"),
    [
        ("INGEST_VALIDATE", "probe.json"),
        ("PROXY_GENERATE", "proxy.mp4"),
        ("SHOT_DETECT", "shots.json"),
    ],
)
def test_media_worker_stages(
    synthetic_video: Path,
    tmp_path: Path,
    stage_type: str,
    expected_name: str,
) -> None:
    output = tmp_path / stage_type.lower()
    result = execute(_job(stage_type, synthetic_video, output))
    assert result.status == "OUTPUT_READY"
    asset = result.variants[0].output_assets[0]
    assert asset.uri.endswith(expected_name)
    assert asset.size_bytes > 0
    if stage_type == "INGEST_VALIDATE":
        assert result.domain_artifacts[0].document_type == "MEDIA_PROBE"
    elif stage_type == "SHOT_DETECT":
        assert result.domain_artifacts[0].document_type == "SHOT_LIST"
    else:
        assert result.domain_artifacts == []
