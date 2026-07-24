"""MoCha visual generation adapter — complex occlusion shots.

Implements the ``VisualGenerationAdapter`` protocol using MoCha for handling
shots with heavy occlusion.  Takes a source video and an optional mask, and
returns ``candidate_count`` heterogeneous VisualCandidate variants.

All heavy imports are deferred to ``generate()`` so the class can be imported
in CPU/CI environments without torch or MoCha installed.
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
class MoChaAdapter:
    """MoCha complex-occlusion visual generation adapter.

    Env vars (read at inference time):
        VTV_MOCHA_CHECKPOINT  – path to MoCha checkpoint file
        VTV_MOCHA_DEVICE      – ``cuda`` (default) | ``cpu``
        VTV_MOCHA_STEPS       – num_inference_steps (default: 25)
    """

    _release: str = field(default="mocha@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def preload(self) -> None:
        """Load and cache the immutable model during worker startup."""
        import torch

        checkpoint = os.environ.get("VTV_MOCHA_CHECKPOINT")
        device = os.environ.get(
            "VTV_MOCHA_DEVICE", "cuda" if torch.cuda.is_available() else "cpu"
        )
        _load_mocha_model(checkpoint, device)

    def generate(
        self,
        request: VisualGenerationRequest,
        source_video: Path,
        output_directory: Path,
        mask: Path | None = None,
    ) -> tuple[VisualCandidate, ...]:
        """Generate *request.candidate_count* video candidates for *source_video*."""
        import torch

        checkpoint = os.environ.get("VTV_MOCHA_CHECKPOINT")
        device = os.environ.get("VTV_MOCHA_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
        num_steps = int(os.environ.get("VTV_MOCHA_STEPS", "25"))

        model = _load_mocha_model(checkpoint, device)
        output_directory.mkdir(parents=True, exist_ok=True)

        candidates: list[VisualCandidate] = []
        for variant_no in range(1, request.candidate_count + 1):
            seed = (request.seed + variant_no - 1) % (2**63)
            variant_dir = output_directory / f"variant_{variant_no:02d}"
            variant_dir.mkdir(exist_ok=True)
            output_path = variant_dir / "output.mp4"

            model.generate(
                source_video=str(source_video),
                mask=str(mask) if mask is not None else None,
                output_path=str(output_path),
                num_steps=num_steps,
                seed=seed,
                device=device,
            )

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
def _load_mocha_model(checkpoint: str | None, device: str):
    """Load MoCha model (lazy)."""
    try:
        from mocha import MoChaModel  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "MoCha not installed. Install from https://github.com/...MoCha"
        ) from exc

    model = MoChaModel.from_pretrained(checkpoint) if checkpoint else MoChaModel()
    model.to(device)
    return model


def _extract_first_frame(video: Path, out_dir: Path, name: str = "first_frame.jpg") -> Path:
    out = out_dir / name
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vframes", "1", str(out)],
        check=True, capture_output=True,
    )
    return out


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
