"""CoTracker3 point-tracking utility adapter.

Standalone point-tracking utility (NOT a VisualGenerationAdapter).  Used for
drift validation, prop tracking, and screen direction verification.

All heavy imports are deferred to ``track()`` so the class can be imported in
CPU/CI environments without torch or cotracker installed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CoTracker3Adapter:
    """CoTracker3 point-tracking utility.

    Env vars (read at inference time):
        VTV_COTRACKER_DEVICE      – ``cuda`` (default) | ``cpu``
        VTV_COTRACKER_CHECKPOINT  – local checkpoint path; if unset, uses
                                    HuggingFace auto-download
    """

    _release: str = field(default="cotracker3@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def track(
        self,
        source_video: Path,
        query_points: list[tuple[float, float]],
        output_dir: Path,
    ) -> dict:
        """Track *query_points* forward through all frames of *source_video*.

        Args:
            source_video:   Path to the input video file.
            query_points:   List of (x, y) normalised coordinates (0–1 range)
                            to track from the first frame onward.
            output_dir:     Directory where per-frame tracking artefacts may be
                            written.

        Returns:
            A dict with keys:
                ``shot_id``         – stem of *source_video* used as identifier.
                ``tracks``          – list of per-point trajectories, each a list
                                      of ``{"frame": int, "x": float, "y": float}``
                                      dicts.
                ``occlusion_flags`` – list of per-point per-frame bool lists.
                ``model_release``   – e.g. ``"cotracker3@1"``.
        """
        import torch

        device = os.environ.get(
            "VTV_COTRACKER_DEVICE", "cuda" if torch.cuda.is_available() else "cpu"
        )
        checkpoint = os.environ.get("VTV_COTRACKER_CHECKPOINT")

        predictor = _load_cotracker(checkpoint, device)
        output_dir.mkdir(parents=True, exist_ok=True)

        video_tensor = _load_video_tensor(source_video, device)  # (1, T, C, H, W)
        _, T, _, H, W = video_tensor.shape

        # Convert normalised (x, y) to pixel coordinates for frame 0
        queries = torch.tensor(
            [[0.0, pt[0] * W, pt[1] * H] for pt in query_points],
            dtype=torch.float32,
            device=device,
        ).unsqueeze(0)  # (1, N, 3) — [t, x, y]

        with torch.no_grad():
            pred_tracks, pred_visibility = predictor(video_tensor, queries=queries)
        # pred_tracks:     (1, T, N, 2)
        # pred_visibility: (1, T, N)

        pred_tracks = pred_tracks.squeeze(0).cpu()        # (T, N, 2)
        pred_visibility = pred_visibility.squeeze(0).cpu()  # (T, N)

        n_points = len(query_points)
        tracks: list[list[dict]] = [[] for _ in range(n_points)]
        occlusion_flags: list[list[bool]] = [[] for _ in range(n_points)]

        for t in range(T):
            for n in range(n_points):
                x_px, y_px = float(pred_tracks[t, n, 0]), float(pred_tracks[t, n, 1])
                tracks[n].append({"frame": t, "x": x_px / W, "y": y_px / H})
                occlusion_flags[n].append(not bool(pred_visibility[t, n]))

        return {
            "shot_id": source_video.stem,
            "tracks": tracks,
            "occlusion_flags": occlusion_flags,
            "model_release": self.model_release,
        }


# ── helpers ──────────────────────────────────────────────────────────────────


def _load_cotracker(checkpoint: str | None, device: str):
    """Load CoTracker3 predictor (lazy)."""
    import torch  # noqa: F401 — already imported by caller, kept for clarity

    try:
        from cotracker.predictor import CoTrackerPredictor  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "cotracker not installed. Install from https://github.com/facebookresearch/co-tracker"
        ) from exc

    if checkpoint:
        predictor = CoTrackerPredictor(checkpoint=checkpoint)
    else:
        import torch as _torch
        predictor = _torch.hub.load("facebookresearch/co-tracker", "cotracker3_offline")
    predictor = predictor.to(device)
    predictor.eval()
    return predictor


def _load_video_tensor(video: Path, device: str):
    """Load video frames into a (1, T, C, H, W) float32 tensor on *device*."""
    import subprocess
    import tempfile
    from pathlib import Path as _Path

    import numpy as np
    import torch
    from PIL import Image

    with tempfile.TemporaryDirectory() as td:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video), f"{td}/frame_%06d.png"],
            check=True, capture_output=True,
        )
        frames = []
        for p in sorted(_Path(td).glob("frame_*.png")):
            img = np.array(Image.open(p).convert("RGB"), dtype=np.float32) / 255.0
            frames.append(img)

    arr = np.stack(frames, axis=0)                       # (T, H, W, C)
    tensor = torch.from_numpy(arr).permute(0, 3, 1, 2)  # (T, C, H, W)
    return tensor.unsqueeze(0).to(device)                # (1, T, C, H, W)
