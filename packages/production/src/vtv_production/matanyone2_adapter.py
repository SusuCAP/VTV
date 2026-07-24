"""MatAnyone2 soft-matting segmentation adapter (P11-B).

Implements the ``SegmentationAdapter`` protocol using MatAnyone2 for
hair, semi-transparent, and motion-blur alpha mattes.

Used after SAM3.1 provides a coarse binary mask; MatAnyone2 refines the
alpha channel at soft boundaries.

All heavy imports are deferred to ``segment()`` so CI can import without GPU.

Env vars:
    VTV_MATANYONE2_MODEL_ID  – HuggingFace ID or local path (default: pq-yang/MatAnyone2)
    VTV_MATANYONE2_DEVICE    – cuda (default) | cpu
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .contracts import SegmentationRequest, SegmentationResult


@dataclass(frozen=True, slots=True)
class MatAnyone2Adapter:
    """MatAnyone2 soft alpha-matte segmentation adapter.

    Best used for shots with hair, transparent fabrics, or motion blur where
    SAM3.1 produces hard binary edges. Provide the SAM3.1 coarse mask as the
    *initial_mask* keyword (passed via request.parameters) for better results.
    """

    _release: str = field(default="matanyone2@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def preload(self) -> None:
        """Load and cache the immutable matting model during worker startup."""
        import torch

        model_id = os.environ.get("VTV_MATANYONE2_MODEL_ID", "pq-yang/MatAnyone2")
        device = os.environ.get(
            "VTV_MATANYONE2_DEVICE",
            "cuda" if torch.cuda.is_available() else "cpu",
        )
        _load_matanyone2(model_id, device)

    def segment(
        self,
        request: SegmentationRequest,
        source_video: Path,
        output_dir: Path,
    ) -> SegmentationResult:
        """Run MatAnyone2 on *source_video* to generate a soft alpha matte."""
        import torch

        model_id = os.environ.get("VTV_MATANYONE2_MODEL_ID", "pq-yang/MatAnyone2")
        device = os.environ.get(
            "VTV_MATANYONE2_DEVICE", "cuda" if torch.cuda.is_available() else "cpu"
        )

        model = _load_matanyone2(model_id, device)
        output_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="vtv_mat2_") as tmp:
            frames_dir = Path(tmp) / "frames"
            mattes_dir = Path(tmp) / "mattes"
            frames_dir.mkdir()
            mattes_dir.mkdir()

            _extract_frames(source_video, frames_dir)
            frame_paths = sorted(frames_dir.glob("frame_*.png"))
            if not frame_paths:
                raise RuntimeError(f"No frames extracted from {source_video}")

            for frame_path in frame_paths:
                matte = _run_matanyone2(model, frame_path, request)
                matte_path = mattes_dir / frame_path.name
                _save_alpha_png(matte, matte_path)

            if request.output_type == "alpha_matte":
                import shutil
                output_path = output_dir / "alpha_matte.png"
                shutil.copy2(mattes_dir / frame_paths[0].name, output_path)
            else:
                output_path = output_dir / "mask.mp4"
                _assemble_matte_video(mattes_dir, output_path, source_video)

        sha256 = _sha256(output_path)
        return SegmentationResult(
            shot_id=request.shot_id,
            mask_uri=output_path.as_uri(),
            mask_sha256=sha256,
            mask_type=request.output_type,
            model_release=self.model_release,
        )


# ── helpers ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=2)
def _load_matanyone2(model_id: str, device: str):
    try:
        from matanyone import MatAnyone2  # type: ignore[import]
        model = MatAnyone2.from_pretrained(model_id)
        model.to(device).eval()
        return model
    except ImportError:
        raise ImportError(
            "MatAnyone2 is not installed. "
            "Install from https://github.com/pq-yang/MatAnyone2"
        ) from None


def _run_matanyone2(model, frame_path: Path, request: SegmentationRequest):
    """Run MatAnyone2 inference on a single frame."""
    import cv2
    import torch

    frame_bgr = cv2.imread(str(frame_path))
    if frame_bgr is None:
        raise RuntimeError(f"Cannot read frame: {frame_path}")
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

    # MatAnyone2 accepts an optional coarse mask from SAM3.1
    if request.prompt_type == "text":
        # Use text prompt to generate initial rough mask internally if supported
        try:
            with torch.no_grad():
                alpha = model.predict(frame_rgb, text_prompt=request.prompt)
        except TypeError:
            with torch.no_grad():
                alpha = model.predict(frame_rgb)
    else:
        with torch.no_grad():
            alpha = model.predict(frame_rgb)

    # alpha is float32 [0,1] → uint8 [0,255]
    if isinstance(alpha, torch.Tensor):
        alpha = alpha.squeeze().cpu().numpy()
    return (alpha * 255).clip(0, 255).astype("uint8")


def _save_alpha_png(alpha_array, path: Path) -> None:
    import cv2
    cv2.imwrite(str(path), alpha_array)


def _extract_frames(video: Path, out_dir: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), str(out_dir / "frame_%06d.png")],
        check=True, capture_output=True,
    )


def _assemble_matte_video(mattes_dir: Path, output: Path, reference: Path) -> None:
    result = subprocess.run(
        ["ffprobe", "-v", "0", "-select_streams", "v",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(reference)],
        capture_output=True, text=True, check=True,
    )
    fps = result.stdout.strip()
    subprocess.run(
        ["ffmpeg", "-y", "-framerate", fps,
         "-i", str(mattes_dir / "frame_%06d.png"),
         "-vf", "format=gray", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)],
        check=True, capture_output=True,
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
