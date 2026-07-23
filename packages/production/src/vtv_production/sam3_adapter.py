"""SAM 3.1 segmentation adapter (P8-C).

Implements the ``SegmentationAdapter`` protocol using the Segment Anything Model 3.1
(or the ``segment-anything`` package as fallback when SAM3.1 is not yet installed).

The adapter runs frame-by-frame inference guided by a text, point, or box prompt and
assembles the per-frame binary masks into either a mask-video (H.264 grayscale) or a
single alpha-matte PNG (for the first keyframe only, used by visual-generation adapters).

All heavy imports are performed lazily inside ``segment()`` so that the class can be
imported in CI without requiring torch or segment-anything to be installed.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .contracts import SegmentationRequest, SegmentationResult

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class Sam31SegmentationAdapter:
    """Segment Anything Model 3.1 segmentation adapter.

    Env vars (read at inference time):
        VTV_SAM_CHECKPOINT   – path to sam_hq.pt / sam3.1_hq.pt (required)
        VTV_SAM_MODEL_TYPE   – ``vit_h`` (default) | ``vit_l`` | ``vit_b``
        VTV_SAM_DEVICE       – ``cuda`` (default) | ``cpu``
    """

    _release: str = field(default="sam3.1@1")
    # Override checkpoint path at construction time (useful in tests)
    checkpoint_override: str | None = field(default=None)

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def segment(
        self,
        request: SegmentationRequest,
        source_video: Path,
        output_dir: Path,
    ) -> SegmentationResult:
        """Run SAM3.1 on every frame of *source_video* guided by *request.prompt*.

        Returns a ``SegmentationResult`` pointing at the generated mask asset.
        """
        import torch

        checkpoint = (
            self.checkpoint_override
            or os.environ.get("VTV_SAM_CHECKPOINT")
        )
        if not checkpoint:
            raise RuntimeError(
                "SAM3.1 checkpoint not found. "
                "Set VTV_SAM_CHECKPOINT or pass checkpoint_override."
            )

        model_type = os.environ.get("VTV_SAM_MODEL_TYPE", "vit_h")
        device = os.environ.get("VTV_SAM_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

        # Try SAM3.1 API first, fall back to segment-anything
        predictor = _load_sam_predictor(checkpoint, model_type, device)

        # Extract frames from the source video
        with tempfile.TemporaryDirectory(prefix="vtv_sam_") as tmp:
            frames_dir = Path(tmp) / "frames"
            masks_dir = Path(tmp) / "masks"
            frames_dir.mkdir()
            masks_dir.mkdir()

            _extract_frames(source_video, frames_dir)
            frame_paths = sorted(frames_dir.glob("frame_*.png"))
            if not frame_paths:
                raise RuntimeError(f"No frames extracted from {source_video}")

            # Run SAM on each frame
            for frame_path in frame_paths:
                image = _load_image_as_rgb_array(frame_path)
                predictor.set_image(image)
                mask = _predict_mask(predictor, image, request)
                mask_path = masks_dir / frame_path.name
                _save_mask_png(mask, mask_path)

            output_dir.mkdir(parents=True, exist_ok=True)

            if request.output_type == "alpha_matte":
                # Return only the first frame as PNG alpha matte
                output_path = output_dir / "alpha_matte.png"
                import shutil
                shutil.copy2(masks_dir / frame_paths[0].name, output_path)
            else:
                # Assemble mask video (grayscale H.264)
                output_path = output_dir / "mask.mp4"
                _assemble_mask_video(masks_dir, output_path, source_video)

        sha256 = _sha256(output_path)
        return SegmentationResult(
            shot_id=request.shot_id,
            mask_uri=output_path.as_uri(),
            mask_sha256=sha256,
            mask_type=request.output_type,
            model_release=self.model_release,
        )


# ── helpers ──────────────────────────────────────────────────────────────────


def _load_sam_predictor(checkpoint: str, model_type: str, device: str):
    """Load SAM3.1 or fall back to segment-anything predictor."""
    try:
        # SAM3.1 ships as ``sam3`` package from the official repo
        from sam3 import SamPredictor, sam_model_registry  # type: ignore[import]
    except ImportError:
        from segment_anything import SamPredictor, sam_model_registry  # type: ignore[import]

    sam = sam_model_registry[model_type](checkpoint=checkpoint)
    sam.to(device)
    return SamPredictor(sam)


def _load_image_as_rgb_array(path: Path):
    import cv2
    bgr = cv2.imread(str(path))
    if bgr is None:
        raise RuntimeError(f"cv2 could not read {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _predict_mask(predictor, image, request: SegmentationRequest):
    """Run SAM prediction based on the request's prompt type."""
    import numpy as np

    h, w = image.shape[:2]

    if request.prompt_type == "text":
        # For text prompts we use the centre-of-image point as a fallback
        # (SAM3.1 supports text; SAM2.1 uses point/box only)
        try:
            masks, _, _ = predictor.predict_text(request.prompt)
        except AttributeError:
            # Fallback: use centre point
            cx, cy = w // 2, h // 2
            masks, _, _ = predictor.predict(
                point_coords=np.array([[cx, cy]]),
                point_labels=np.array([1]),
                multimask_output=False,
            )
    elif request.prompt_type == "point":
        px, py = request.prompt
        masks, _, _ = predictor.predict(
            point_coords=np.array([[int(px * w), int(py * h)]]),
            point_labels=np.array([1]),
            multimask_output=False,
        )
    else:  # box
        x1, y1, x2, y2 = request.prompt
        box = np.array([x1 * w, y1 * h, x2 * w, y2 * h])
        masks, _, _ = predictor.predict(
            box=box,
            multimask_output=False,
        )

    return masks[0].astype("uint8") * 255  # binary 0/255


def _save_mask_png(mask_array, path: Path) -> None:
    import cv2
    cv2.imwrite(str(path), mask_array)


def _extract_frames(video: Path, out_dir: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video),
            str(out_dir / "frame_%06d.png"),
        ],
        check=True,
        capture_output=True,
    )


def _assemble_mask_video(masks_dir: Path, output: Path, reference_video: Path) -> None:
    """Assemble mask PNGs into a grayscale H.264 video matching reference fps."""
    result = subprocess.run(
        ["ffprobe", "-v", "0", "-select_streams", "v", "-show_entries",
         "stream=r_frame_rate", "-of", "csv=p=0", str(reference_video)],
        capture_output=True, text=True, check=True,
    )
    fps_str = result.stdout.strip()
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-framerate", fps_str,
            "-i", str(masks_dir / "frame_%06d.png"),
            "-vf", "format=gray",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(output),
        ],
        check=True,
        capture_output=True,
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
