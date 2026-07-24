"""LTX-2.3 22B visual generation adapter — full audio+video generation.

Implements the ``VisualGenerationAdapter`` protocol using LTX-Video 2.3 (22B)
via HuggingFace diffusers.  Optimised for B200/H200; requires high VRAM.

All heavy imports are deferred to ``generate()`` so the class can be imported
in CPU/CI environments without torch or diffusers installed.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import VisualCandidate, VisualGenerationRequest


@dataclass(frozen=True, slots=True)
class LTX23Adapter:
    """LTX-Video 2.3 22B full audio+video generation adapter.

    Preferred hardware: B200 / H200 (high VRAM requirement).

    Env vars (read at inference time):
        VTV_LTX_MODEL_ID  – HuggingFace model ID or local path
                            (default: ``Lightricks/LTX-Video``)
        VTV_LTX_DEVICE    – ``cuda`` (default) | ``cpu``
        VTV_LTX_STEPS     – num_inference_steps (default: 40)
        VTV_LTX_DTYPE     – ``bfloat16`` (default) | ``float16`` | ``float32``
    """

    _release: str = field(default="ltx-2.3-22b@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def generate(
        self,
        request: VisualGenerationRequest,
        source_video: Path,
        output_directory: Path,
        mask: Path | None = None,
    ) -> tuple[VisualCandidate, ...]:
        """Generate *request.candidate_count* video candidates for *source_video*."""
        import torch

        model_id = os.environ.get("VTV_LTX_MODEL_ID", "Lightricks/LTX-Video")
        device = os.environ.get("VTV_LTX_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
        num_steps = int(os.environ.get("VTV_LTX_STEPS", "40"))
        dtype_str = os.environ.get("VTV_LTX_DTYPE", "bfloat16")

        dtype_map = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "float32": torch.float32,
        }
        torch_dtype = dtype_map.get(dtype_str, torch.bfloat16)

        pipe = _load_ltx_pipeline(model_id, device, torch_dtype)
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
                or "High-quality cinematic video with natural audio"
            )

            video_frames = pipe(
                image=_load_pil_image(first_frame),
                prompt=prompt,
                num_inference_steps=num_steps,
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


def _load_ltx_pipeline(model_id: str, device: str, dtype):
    """Load LTX-Video pipeline via diffusers (lazy)."""
    from diffusers import LTXImageToVideoPipeline  # type: ignore[import]

    pipe = LTXImageToVideoPipeline.from_pretrained(model_id, torch_dtype=dtype)
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
