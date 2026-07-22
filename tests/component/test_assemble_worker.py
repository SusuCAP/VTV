import subprocess
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from PIL import Image
from vtv_assemble_worker import AssembleWorker
from vtv_media import probe_media
from vtv_schemas.jobs import AssetRef, StageJob


def _run(arguments: list[str]) -> None:
    subprocess.run(arguments, check=True, capture_output=True)


def _audio(path: Path, frequency: int, duration: float) -> None:
    _run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:duration={duration}:sample_rate=48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(path),
        ]
    )


def _video(path: Path, duration: float, color: str = "blue") -> None:
    _run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=160x90:r=24:d={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ]
    )


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _asset(path: Path, media_type: str) -> AssetRef:
    return AssetRef(
        uri=path.resolve().as_uri(),
        sha256=_sha(path),
        media_type=media_type,
        size_bytes=path.stat().st_size,
    )


def _job(tmp_path: Path, stage_type: str, *, inputs=(), params=None) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        idempotency_key=f"assembly:{stage_type.lower()}",
        stage_type=stage_type,
        input_assets=list(inputs),
        output_prefix=(tmp_path / stage_type.lower()).resolve().as_uri(),
        runtime_profile_id="cpu-assemble",
        observed_control_version=1,
        params=params or {},
        trace_id=f"test-{stage_type.lower()}",
    )


def test_subtitle_mix_and_burned_episode_master_pipeline(tmp_path: Path) -> None:
    worker = AssembleWorker()
    subtitle = worker.execute(
        _job(
            tmp_path,
            "SUBTITLE_RENDER",
            params={
                "formats": ["srt", "vtt"],
                "subtitle_document": {
                    "locale": "en-US",
                    "cues": [
                        {
                            "index": 1,
                            "start_seconds": 0.25,
                            "end_seconds": 1.5,
                            "text": "Hello, world.",
                        }
                    ],
                },
            },
        )
    )
    assert len(subtitle.variants[0].output_assets) == 2
    srt = next(
        item
        for item in subtitle.variants[0].output_assets
        if item.media_type == "application/x-subrip"
    )

    dialogue_path = tmp_path / "dialogue.wav"
    background_path = tmp_path / "background.wav"
    _audio(dialogue_path, 440, 1)
    _audio(background_path, 220, 2)
    dialogue = _asset(dialogue_path, "audio/wav")
    background = _asset(background_path, "audio/wav")
    mixed = worker.execute(
        _job(
            tmp_path,
            "AUDIO_MIX",
            inputs=(dialogue, background),
            params={
                "audio_mix_request": {
                    "duration_seconds": 2,
                    "preset": {
                        "name": "web-dialogue",
                        "integrated_lufs": -16,
                        "true_peak_dbfs": -1.5,
                        "loudness_range_lu": 11,
                    },
                    "tracks": [
                        {
                            "asset_sha256": dialogue.sha256,
                            "role": "DIALOGUE",
                            "start_seconds": 0.5,
                            "gain_db": -1,
                            "room_reverb": 0.2,
                        },
                        {
                            "asset_sha256": background.sha256,
                            "role": "BACKGROUND",
                            "gain_db": -12,
                        },
                    ],
                }
            },
        )
    )
    mixed_asset = mixed.variants[0].output_assets[0]
    mixed_probe = probe_media(
        Path(mixed_asset.uri.removeprefix("file://")), require_video=False
    )
    assert abs(mixed_probe.duration_seconds - 2) <= 0.05
    assert mixed_asset.metadata["integrated_lufs"] == -16
    assert abs(mixed_asset.metadata["measured_integrated_lufs"] + 16) <= 1
    assert mixed_asset.metadata["measured_true_peak_dbfs"] <= -1.3

    source_path = tmp_path / "source.mp4"
    _video(source_path, 2)
    source = _asset(source_path, "video/mp4")
    master = worker.execute(
        _job(
            tmp_path,
            "ASSEMBLE_EPISODE",
            inputs=(source, mixed_asset, srt),
            params={
                "episode_assembly_request": {
                    "duration_seconds": 2,
                    "width": 320,
                    "height": 568,
                    "fps": 24,
                    "video_codec": "h264",
                    "audio_codec": "aac",
                    "burn_subtitles": True,
                    "source_video_sha256": source.sha256,
                    "mixed_audio_sha256": mixed_asset.sha256,
                    "subtitle_sha256": srt.sha256,
                    "subtitle_document": {
                        "locale": "en-US",
                        "cues": [
                            {
                                "index": 1,
                                "start_seconds": 0.25,
                                "end_seconds": 1.5,
                                "text": "Hello, world.",
                            }
                        ],
                    },
                }
            },
        )
    )
    master_asset = master.variants[0].output_assets[0]
    probe = probe_media(Path(master_asset.uri.removeprefix("file://")))
    assert probe.video_streams[0].width == 320
    assert probe.video_streams[0].height == 568
    assert probe.audio_streams
    assert abs(probe.duration_seconds - 2) <= 0.05
    assert master_asset.metadata["burned_subtitles"] is True


def test_picture_conform_replaces_only_adopted_shot_interval(tmp_path: Path) -> None:
    source_path = tmp_path / "source-red.mp4"
    replacement_path = tmp_path / "replacement-blue.mp4"
    _video(source_path, 2, "red")
    _video(replacement_path, 1, "blue")
    source = _asset(source_path, "video/mp4")
    replacement = _asset(replacement_path, "video/mp4")
    worker = AssembleWorker()

    result = worker.execute(
        _job(
            tmp_path,
            "PICTURE_CONFORM",
            inputs=(source, replacement),
            params={
                "picture_conform_request": {
                    "source_video_sha256": source.sha256,
                    "duration_seconds": 2,
                    "edits": [
                        {
                            "shot_id": "shot-1",
                            "replacement_sha256": replacement.sha256,
                            "start_seconds": 0.5,
                            "end_seconds": 1.5,
                        }
                    ],
                }
            },
        )
    )

    output = Path(result.variants[0].output_assets[0].uri.removeprefix("file://"))
    probe = probe_media(output)
    assert abs(probe.duration_seconds - 2) <= 0.05
    assert result.variants[0].output_assets[0].metadata["adopted_shot_ids"] == [
        "shot-1"
    ]
    before = tmp_path / "before.png"
    during = tmp_path / "during.png"
    for timestamp, destination in ((0.25, before), (1.0, during)):
        _run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-ss",
                str(timestamp),
                "-i",
                str(output),
                "-frames:v",
                "1",
                "-y",
                str(destination),
            ]
        )
    red_pixel = Image.open(before).convert("RGB").getpixel((80, 45))
    blue_pixel = Image.open(during).convert("RGB").getpixel((80, 45))
    assert red_pixel[0] > red_pixel[2]
    assert blue_pixel[2] > blue_pixel[0]
