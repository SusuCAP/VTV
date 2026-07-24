"""VACE visual generation adapter — scene/object editing with mask guidance.

Implements the ``VisualGenerationAdapter`` protocol using VACE for background
replacement and object editing with mask guidance.

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
class VACEAdapter:
    """VACE scene/object editing and background replacement adapter.

    Env vars (read at inference time):
        VTV_VACE_MODEL_ID  – HuggingFace model ID or local path
                             (default: ``ali-vilab/VACE``)
        VTV_VACE_DEVICE    – ``cuda`` (default) | ``cpu``
        VTV_VACE_STEPS     – num_inference_steps (default: 25)
    """

    _release: str = field(default="vace@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def preload(self) -> None:
        """Load and cache the immutable model pipeline during worker startup."""
        import torch

        model_id = os.environ.get("VTV_VACE_MODEL_ID", "ali-vilab/VACE")
        device = os.environ.get(
            "VTV_VACE_DEVICE", "cuda" if torch.cuda.is_available() else "cpu"
        )
        _load_vace_pipeline(model_id, device)

    def generate(
        self,
        request: VisualGenerationRequest,
        source_video: Path,
        output_directory: Path,
        mask: Path | None = None,
    ) -> tuple[VisualCandidate, ...]:
        """Generate *request.candidate_count* video candidates for *source_video*."""
        import torch

        model_id = os.environ.get("VTV_VACE_MODEL_ID", "ali-vilab/VACE")
        device = os.environ.get("VTV_VACE_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
        num_steps = int(os.environ.get("VTV_VACE_STEPS", "25"))

        pipe = _load_vace_pipeline(model_id, device)
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
                or "Clean background replacement with natural lighting"
            )

            pipe_kwargs: dict = {
                "image": _load_pil_image(first_frame),
                "prompt": prompt,
                "num_inference_steps": num_steps,
                "generator": generator,
            }
            if mask is not None:
                pipe_kwargs["mask_image"] = _load_pil_image(mask)

            video_frames = pipe(**pipe_kwargs).frames[0]

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
def _load_vace_pipeline(model_id: str, device: str):
    """Load VACE pipeline via diffusers (lazy)."""
    from diffusers import AutoPipelineForVideo  # type: ignore[import]

    pipe = AutoPipelineForVideo.from_pretrained(model_id)
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
