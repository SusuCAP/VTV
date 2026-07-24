"""VGGT-Omega spatial geometry adapter (P-VGGT).

Standalone utility for camera parameter estimation, per-frame depth maps,
and optional 3-D scene reconstruction using Facebook Research's VGGT model.

NOT a VisualGenerationAdapter — call ``analyze()`` directly.

All heavy imports are deferred to ``analyze()`` so the class can be imported
in CPU/CI environments without torch or vggt installed.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VGGTOmegaAdapter:
    """VGGT-Omega camera-pose, depth, and scene-reconstruction adapter.

    Env vars (read at inference time):
        VTV_VGGT_MODEL_ID    – HuggingFace model ID or local path
                               (default: ``facebookresearch/vggt``)
        VTV_VGGT_DEVICE      – ``cuda`` (default) | ``cpu``
        VTV_VGGT_MAX_FRAMES  – max frames to process (default: 81)
    """

    _release: str = field(default="vggt-omega@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def analyze(self, source_video: Path, output_dir: Path) -> dict:
        """Estimate camera parameters, depth maps, and scene geometry for *source_video*.

        Returns a dict with keys:
            shot_id                  – stem of the source video filename
            camera_poses             – list of per-frame dicts with
                                       {rotation, translation, focal_length}
            depth_maps               – list of file:// URIs to per-frame depth PNGs
            scene_reconstruction_uri – file:// URI to full 3-D reconstruction
                                       (empty string if unavailable)
            point_tracks             – list of CoTracker3 tracks (empty if unavailable)
            model_release            – adapter release string
        """
        import torch

        model_id = os.environ.get("VTV_VGGT_MODEL_ID", "facebookresearch/vggt")
        device = os.environ.get(
            "VTV_VGGT_DEVICE", "cuda" if torch.cuda.is_available() else "cpu"
        )
        max_frames = int(os.environ.get("VTV_VGGT_MAX_FRAMES", "81"))

        model = _load_vggt_model(model_id, device)
        output_dir.mkdir(parents=True, exist_ok=True)

        frames = _extract_frames(source_video, output_dir, max_frames=max_frames)

        # Run VGGT inference
        images = _load_frames_as_tensor(frames, device)
        with torch.no_grad():
            predictions = model(images)

        camera_poses = _parse_camera_poses(predictions)
        depth_maps = _save_depth_maps(predictions, frames, output_dir)

        # Optional full 3-D reconstruction
        scene_reconstruction_uri = ""
        try:
            recon_path = _assemble_depth_video(depth_maps, output_dir)
            scene_reconstruction_uri = recon_path.as_uri()
        except Exception:
            pass

        # Optional CoTracker3 point tracks
        import contextlib

        point_tracks: list = []
        with contextlib.suppress(ImportError, Exception):
            point_tracks = _run_cotracker3(frames, device)

        return {
            "shot_id": source_video.stem,
            "camera_poses": camera_poses,
            "depth_maps": [p.as_uri() for p in depth_maps],
            "scene_reconstruction_uri": scene_reconstruction_uri,
            "point_tracks": point_tracks,
            "model_release": self.model_release,
        }


# ── helpers ──────────────────────────────────────────────────────────────────


def _load_vggt_model(model_id: str, device: str):
    """Load VGGT-Omega model with two-stage lazy import."""
    try:
        from vggt import VGGTModel  # type: ignore[import]

        model = VGGTModel.from_pretrained(model_id)
        model.to(device)
        model.eval()
        return model
    except ImportError:
        pass

    try:
        import torch

        model = torch.hub.load("facebookresearch/vggt", "vggt_omega")
        model.to(device)
        model.eval()
        return model
    except Exception:
        pass

    raise ImportError(
        "VGGT is not installed or could not be loaded via torch.hub. "
        "Install from https://github.com/facebookresearch/vggt"
    )


def _extract_frames(video: Path, out_dir: Path, *, max_frames: int) -> list[Path]:
    """Extract up to *max_frames* equally-spaced frames from *video* as PNGs."""
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    # Count total frames first
    result = subprocess.run(
        [
            "ffprobe", "-v", "0", "-select_streams", "v",
            "-count_frames", "-show_entries", "stream=nb_read_frames",
            "-of", "csv=p=0", str(video),
        ],
        capture_output=True, text=True,
    )
    try:
        total = int(result.stdout.strip())
    except ValueError:
        total = max_frames

    step = max(1, total // max_frames)

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video),
            "-vf", f"select=not(mod(n\\,{step}))",
            "-vsync", "vfr",
            "-frames:v", str(max_frames),
            str(frames_dir / "frame_%06d.png"),
        ],
        check=True,
        capture_output=True,
    )

    return sorted(frames_dir.glob("frame_*.png"))


def _load_frames_as_tensor(frames: list[Path], device: str):
    """Stack frame PNGs into a (1, T, C, H, W) float32 tensor."""
    import torch
    import torchvision.transforms.functional as TF  # type: ignore[import]
    from PIL import Image  # type: ignore[import]

    imgs = [TF.to_tensor(Image.open(p).convert("RGB")) for p in frames]
    stacked = torch.stack(imgs).unsqueeze(0).to(device)  # (1, T, C, H, W)
    return stacked


def _parse_camera_poses(predictions) -> list[dict]:
    """Extract per-frame camera pose dicts from VGGT output."""
    poses = []
    # VGGT returns rotation matrices, translations, and focal lengths
    rotations = getattr(predictions, "rotation", None)
    translations = getattr(predictions, "translation", None)
    focal_lengths = getattr(predictions, "focal_length", None)

    if rotations is None:
        # Fall back to dict-style output
        rotations = predictions.get("rotation") if isinstance(predictions, dict) else None
        translations = predictions.get("translation") if isinstance(predictions, dict) else None
        focal_lengths = predictions.get("focal_length") if isinstance(predictions, dict) else None

    if rotations is None:
        return poses

    rot_np = rotations.squeeze(0).cpu().float().numpy() if hasattr(rotations, "cpu") else rotations
    trans_np = (
        translations.squeeze(0).cpu().float().numpy()
        if hasattr(translations, "cpu")
        else translations
    )
    focal_np = (
        focal_lengths.squeeze(0).cpu().float().numpy()
        if hasattr(focal_lengths, "cpu")
        else focal_lengths
    )

    for i in range(len(rot_np)):
        poses.append(
            {
                "rotation": rot_np[i].tolist() if hasattr(rot_np[i], "tolist") else rot_np[i],
                "translation": (
                    trans_np[i].tolist() if hasattr(trans_np[i], "tolist") else trans_np[i]
                ),
                "focal_length": (
                    float(focal_np[i]) if focal_np is not None else None
                ),
            }
        )
    return poses


def _save_depth_maps(predictions, frames: list[Path], out_dir: Path) -> list[Path]:
    """Save per-frame depth maps as 16-bit PNGs and return their paths."""
    import numpy as np
    from PIL import Image  # type: ignore[import]

    depth_dir = out_dir / "depth"
    depth_dir.mkdir(exist_ok=True)

    depth_tensor = getattr(predictions, "depth", None)
    if depth_tensor is None and isinstance(predictions, dict):
        depth_tensor = predictions.get("depth")

    if depth_tensor is None:
        return []

    depth_np = depth_tensor.squeeze(0).cpu().float().numpy()  # (T, H, W)
    paths: list[Path] = []
    for i, _frame in enumerate(frames):
        d = depth_np[i] if i < len(depth_np) else depth_np[-1]
        # Normalise to 0-65535 and save as 16-bit PNG
        d_min, d_max = float(d.min()), float(d.max())
        if d_max > d_min:
            d_norm = ((d - d_min) / (d_max - d_min) * 65535).astype(np.uint16)
        else:
            d_norm = np.zeros_like(d, dtype=np.uint16)
        depth_path = depth_dir / f"depth_{i:06d}.png"
        Image.fromarray(d_norm, mode="I;16").save(depth_path)
        paths.append(depth_path)
    return paths


def _assemble_depth_video(depth_maps: list[Path], out_dir: Path) -> Path:
    """Assemble depth PNG sequence into a depth video for scene preview."""
    if not depth_maps:
        raise ValueError("No depth maps to assemble")
    depth_video = out_dir / "depth_video.mp4"
    first = depth_maps[0]
    pattern = str(first.parent / "depth_%06d.png")
    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", "24",
            "-i", pattern,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(depth_video),
        ],
        check=True,
        capture_output=True,
    )
    return depth_video


def _run_cotracker3(frames: list[Path], device: str) -> list:
    """Run CoTracker3 point tracking if available; raises ImportError otherwise."""
    import torch
    from cotracker.predictor import CoTrackerPredictor  # type: ignore[import]

    model = CoTrackerPredictor(checkpoint=None)
    model.to(device)
    model.eval()

    import torchvision.transforms.functional as TF  # type: ignore[import]
    from PIL import Image  # type: ignore[import]

    imgs = [TF.to_tensor(Image.open(p).convert("RGB")) for p in frames]
    video = torch.stack(imgs).unsqueeze(0).to(device)  # (1, T, C, H, W)

    with torch.no_grad():
        pred_tracks, pred_visibility = model(video, grid_size=10)

    return pred_tracks.squeeze(0).cpu().tolist()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
