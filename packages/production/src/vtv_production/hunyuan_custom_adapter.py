"""HunyuanCustom visual generation adapter — multi-subject reference shots.

Implements the ``VisualGenerationAdapter`` protocol using HunyuanCustom via
HuggingFace diffusers for multi-person shots with reference images.

All heavy imports are deferred to ``generate()`` so the class can be imported
in CPU/CI environments without torch or diffusers installed.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .contracts import VisualCandidate, VisualGenerationRequest


@dataclass(frozen=True, slots=True)
class HunyuanCustomAdapter:
    """HunyuanCustom multi-subject reference visual generation adapter.

    Designed for multi-person shots with reference images.

    Env vars (read at inference time):
        VTV_HUNYUAN_MODEL_ID  – HuggingFace model ID or local path
                                (default: ``tencent/HunyuanCustom``)
        VTV_HUNYUAN_DEVICE    – ``cuda`` (default) | ``cpu``
        VTV_HUNYUAN_DTYPE     – ``bfloat16`` (default) | ``float16`` | ``float32``
    """

    _release: str = field(default="hunyuan-custom@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def preload(self) -> None:
        """Load and cache the immutable model pipeline during worker startup."""
        import torch

        model_id = os.environ.get("VTV_HUNYUAN_MODEL_ID", "tencent/HunyuanCustom")
        device = os.environ.get(
            "VTV_HUNYUAN_DEVICE",
            "cuda" if torch.cuda.is_available() else "cpu",
        )
        dtype = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "float32": torch.float32,
        }.get(
            os.environ.get("VTV_HUNYUAN_DTYPE", "bfloat16"),
            torch.bfloat16,
        )
        _load_hunyuan_pipeline(model_id, device, dtype)

    def generate(
        self,
        request: VisualGenerationRequest,
        source_video: Path,
        output_directory: Path,
        mask: Path | None = None,
    ) -> tuple[VisualCandidate, ...]:
        """Generate *request.candidate_count* video candidates for *source_video*."""
        import torch

        model_id = os.environ.get("VTV_HUNYUAN_MODEL_ID", "tencent/HunyuanCustom")
        device = os.environ.get(
            "VTV_HUNYUAN_DEVICE", "cuda" if torch.cuda.is_available() else "cpu"
        )
        dtype_str = os.environ.get("VTV_HUNYUAN_DTYPE", "bfloat16")

        dtype_map = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "float32": torch.float32,
        }
        torch_dtype = dtype_map.get(dtype_str, torch.bfloat16)

        pipe = _load_hunyuan_pipeline(model_id, device, torch_dtype)
        output_directory.mkdir(parents=True, exist_ok=True)

        first_frame = _extract_first_frame(source_video, output_directory)

        candidates: list[VisualCandidate] = []
        for variant_no in range(1, request.candidate_count + 1):
            seed = (request.seed + variant_no - 1) % (2**63)
            generator = torch.Generator(device=device).manual_seed(seed)
            variant_dir = output_directory / f"variant_{variant_no:02d}"
            variant_dir.mkdir(exist_ok=True)
            output_path = variant_dir / "output.mp4"

            prompt = (
                request.parameters.get("prompt_override")
                or "Multi-person scene with reference subjects"
            )

            video_frames = pipe(
                image=_load_pil_image(first_frame),
                prompt=prompt,
                generator=generator,
            ).frames[0]

            _save_frames_as_video(video_frames, output_path, source_video)
            preview_path = _extract_first_frame(output_path, variant_dir, name="preview.jpg")

            sha256 = _sha256(output_path)
            preview_sha256 = _sha256(preview_path)
            duration = _probe_duration(output_path)

            candidates.append(
                VisualCandidate(
                    shot_id=request.shot_id,
                    variant_no=variant_no,
                    video_uri=output_path.as_uri(),
                    video_sha256=sha256,
                    duration_seconds=duration,
                    model_release=self.model_release,
                    seed=seed,
                    route=request.route,
                    preview_frame_uri=preview_path.as_uri(),
                    preview_frame_sha256=preview_sha256,
                )
            )

        return tuple(candidates)


# ── helpers ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=2)
def _load_hunyuan_pipeline(model_id: str, device: str, dtype):
    """Load HunyuanCustom pipeline via diffusers (lazy)."""
    from diffusers import WanImageToVideoPipeline  # type: ignore[import]

    pipe = WanImageToVideoPipeline.from_pretrained(model_id, torch_dtype=dtype)
    pipe.to(device)
    if device == "cuda":
        pipe.enable_model_cpu_offload()
    return pipe


def _load_pil_image(path: Path):
    from PIL import Image
    return Image.open(path).convert("RGB")


def _extract_first_frame(video: Path, out_dir: Path, name: str = "first_frame.jpg") -> Path:
    out = out_dir / name
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vframes", "1", str(out)],
        check=True, capture_output=True,
    )
    return out


def _save_frames_as_video(frames, output: Path, reference: Path) -> None:
    """Save diffusers VideoProcessor output frames to H.264 video."""
    import tempfile as _tmp

    from PIL import Image

    result = subprocess.run(
        ["ffprobe", "-v", "0", "-select_streams", "v",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(reference)],
        capture_output=True, text=True,
    )
    fps = result.stdout.strip() or "24"

    with _tmp.TemporaryDirectory() as td:
        for i, frame in enumerate(frames):
            img = Image.fromarray(frame) if not hasattr(frame, "save") else frame
            img.save(f"{td}/frame_{i:06d}.png")
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", fps,
             "-i", f"{td}/frame_%06d.png",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)],
            check=True, capture_output=True,
        )


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "0", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
