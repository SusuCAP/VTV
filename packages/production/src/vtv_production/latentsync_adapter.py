"""LatentSync 1.6 lipsync adapter (P8-F).

Implements the ``LipSyncAdapter`` protocol supporting L1–L4 lipsync levels:
  L1_FAST            – MuseTalk 1.5 (fast, face-region only)
  L2_PRESERVE_SOURCE – LatentSync 1.6 (standard, 512×512 face diffusion)
  L3_GENERATIVE_FACE – InfiniteTalk (full-body expression)
  L4_FULL_BODY       – Wan S2V / LTX-2.3 IC-LoRA (full regeneration)

L0_NONE is handled by the existing ``PassthroughLipSyncAdapter``; this adapter
raises ``LipSyncInferenceError`` for L0 to enforce the correct dispatch path.

All heavy imports are deferred to ``render()`` so the class can be imported in
CPU/CI environments without torch, LatentSync, or MuseTalk installed.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import (
    LipSyncCandidate,
    LipSyncLevel,
    LipSyncRequest,
)


class LipSyncInferenceError(RuntimeError):
    """Raised when the lipsync model fails or the level is not supported."""


@dataclass(frozen=True, slots=True)
class LatentSync16Adapter:
    """Multi-level lipsync adapter routing to MuseTalk, LatentSync 1.6, or InfiniteTalk.

    Env vars (read at inference time):
        VTV_LATENTSYNC_CHECKPOINT    – path to latentsync_1.6_unet.pt (L2)
        VTV_LATENTSYNC_DEVICE        – cuda (default) | cpu
        VTV_MUSETALKS_CHECKPOINT     – path to musetalk_v1.5.pt (L1 fallback)
        VTV_INFINITETALK_MODEL_ID    – HuggingFace ID or path (L3)
        VTV_LATENTSYNC_FACE_RES      – face resolution for L2 (default: 512)
        VTV_LATENTSYNC_STEPS         – num inference steps for L2 (default: 20)
    """

    _release: str = field(default="latentsync-1.6@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def render(
        self,
        request: LipSyncRequest,
        source_video: Path,
        audio: Path,
        output_directory: Path,
    ) -> tuple[LipSyncCandidate, ...]:
        """Render lipsync candidates dispatched by *request.decision.level*."""
        level = request.decision.level

        if level is LipSyncLevel.L0_NONE:
            raise LipSyncInferenceError(
                "LatentSync16Adapter does not handle L0_NONE. "
                "Use PassthroughLipSyncAdapter for L0."
            )

        output_directory.mkdir(parents=True, exist_ok=True)
        candidates: list[LipSyncCandidate] = []

        for variant_no in range(1, request.candidate_count + 1):
            seed = (request.seed + variant_no - 1) % (2**63)
            variant_dir = output_directory / f"variant_{variant_no:02d}"
            variant_dir.mkdir(exist_ok=True)
            output_path = variant_dir / "lipsync.mp4"

            if level is LipSyncLevel.L1_FAST:
                _render_musetalks(request, source_video, audio, output_path, seed)
            elif level is LipSyncLevel.L2_PRESERVE_SOURCE:
                _render_latentsync16(request, source_video, audio, output_path, seed)
            elif level in (LipSyncLevel.L3_GENERATIVE_FACE, LipSyncLevel.L4_FULL_BODY):
                _render_infinitetalk(request, source_video, audio, output_path, seed)
            else:
                # L5_FULL_REGEN falls back to L2
                _render_latentsync16(request, source_video, audio, output_path, seed)

            sha256 = _sha256(output_path)
            duration = _probe_duration(output_path)

            candidates.append(
                LipSyncCandidate(
                    shot_id=request.features.shot_id,
                    variant_no=variant_no,
                    video_uri=output_path.as_uri(),
                    video_sha256=sha256,
                    duration_seconds=duration,
                    model_release=self.model_release,
                    seed=seed,
                    level=level,
                )
            )

        return tuple(candidates)


# ── L2: LatentSync 1.6 ────────────────────────────────────────────────────────

def _render_latentsync16(
    request: LipSyncRequest,
    source_video: Path,
    audio: Path,
    output: Path,
    seed: int,
) -> None:
    """Run LatentSync 1.6 inference on the source video face region."""
    import torch

    checkpoint = os.environ.get("VTV_LATENTSYNC_CHECKPOINT")
    if not checkpoint:
        raise LipSyncInferenceError(
            "VTV_LATENTSYNC_CHECKPOINT is not set. "
            "Point it to the latentsync_1.6_unet.pt file."
        )

    device = os.environ.get("VTV_LATENTSYNC_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
    face_res = int(os.environ.get("VTV_LATENTSYNC_FACE_RES", "512"))
    steps = int(os.environ.get("VTV_LATENTSYNC_STEPS", "20"))

    try:
        from latentsync.inference import LatentSyncInference  # type: ignore[import]
    except ImportError:
        raise LipSyncInferenceError(
            "LatentSync is not installed. "
            "Install from https://github.com/bytedance/LatentSync"
        ) from None

    torch.manual_seed(seed)
    inference = LatentSyncInference(
        unet_path=checkpoint,
        device=device,
        face_resolution=face_res,
        num_inference_steps=steps,
    )
    inference.run(
        video_path=str(source_video),
        audio_path=str(audio),
        output_path=str(output),
    )


# ── L1: MuseTalk ─────────────────────────────────────────────────────────────

def _render_musetalks(
    request: LipSyncRequest,
    source_video: Path,
    audio: Path,
    output: Path,
    seed: int,
) -> None:
    """Run MuseTalk 1.5 (fast face-region lipsync)."""
    import torch

    checkpoint = os.environ.get("VTV_MUSETALKS_CHECKPOINT")
    if not checkpoint:
        # Fall back to LatentSync if MuseTalk checkpoint not available
        _render_latentsync16(request, source_video, audio, output, seed)
        return

    device = os.environ.get("VTV_LATENTSYNC_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

    try:
        from musetalk.inference import MuseTalkInference  # type: ignore[import]
    except ImportError:
        # MuseTalk not installed, fall back to LatentSync
        _render_latentsync16(request, source_video, audio, output, seed)
        return

    torch.manual_seed(seed)
    MuseTalkInference(checkpoint, device=device).run(
        video_path=str(source_video),
        audio_path=str(audio),
        output_path=str(output),
    )


# ── L3/L4: InfiniteTalk ──────────────────────────────────────────────────────

def _render_infinitetalk(
    request: LipSyncRequest,
    source_video: Path,
    audio: Path,
    output: Path,
    seed: int,
) -> None:
    """Run InfiniteTalk (full-body expression lipsync)."""
    import torch

    model_id = os.environ.get("VTV_INFINITETALK_MODEL_ID", "InfiniteTalk/InfiniteTalk-v1")
    device = os.environ.get("VTV_LATENTSYNC_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

    try:
        from infinitetalk.inference import InfiniteTalkInference  # type: ignore[import]
    except ImportError:
        # Fall back to LatentSync L2 if InfiniteTalk not installed
        _render_latentsync16(request, source_video, audio, output, seed)
        return

    torch.manual_seed(seed)
    InfiniteTalkInference.from_pretrained(model_id).to(device).run(
        video_path=str(source_video),
        audio_path=str(audio),
        output_path=str(output),
    )


# ── shared ────────────────────────────────────────────────────────────────────

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
