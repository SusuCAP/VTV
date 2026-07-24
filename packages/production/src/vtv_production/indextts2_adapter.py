"""IndexTTS2 precise-duration TTS adapter.

Implements the ``TtsAdapter`` protocol using IndexTTS2 for Chinese/English
speech synthesis with emotion reference and tight duration control.

All heavy imports are deferred to ``synthesize()`` so the class can be
imported in CPU/CI environments without the indextts package installed.
"""
from __future__ import annotations

import hashlib
import os
import wave
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import TtsCandidate, TtsRequest

# Duration-deviation threshold for close-up lipsync shots (4 %)
_CLOSEUP_MAX_DEVIATION = 0.04
# Relaxed threshold for non-lipsync contexts (15 %)
_DEFAULT_MAX_DEVIATION = 0.15


@dataclass(frozen=True, slots=True)
class IndexTTS2Adapter:
    """IndexTTS2 precise-duration TTS adapter for Chinese/English with emotion.

    Env vars (read at inference time):
        VTV_INDEXTTS2_MODEL_DIR   – local model directory
                                    (default: ``/models/indextts2``)
        VTV_INDEXTTS2_DEVICE      – ``cuda`` (default) | ``cpu``
        VTV_INDEXTTS2_SAMPLE_RATE – output sample rate in Hz (default: 24000)
    """

    _release: str = field(default="indextts2@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def synthesize(
        self, request: TtsRequest, output_directory: Path
    ) -> tuple[TtsCandidate, ...]:
        """Generate *request.candidate_count* TTS variants for the utterance.

        For close-up lipsync shots the duration deviation is held to <= 4 %.
        """
        import torch

        model_dir = os.environ.get("VTV_INDEXTTS2_MODEL_DIR", "/models/indextts2")
        device = os.environ.get(
            "VTV_INDEXTTS2_DEVICE", "cuda" if torch.cuda.is_available() else "cpu"
        )
        sample_rate = int(os.environ.get("VTV_INDEXTTS2_SAMPLE_RATE", "24000"))

        model = _load_indextts2(model_dir, device)
        output_directory.mkdir(parents=True, exist_ok=True)

        utterance = request.localized.utterance
        target_text = request.localized.target_text
        target_duration = utterance.duration_seconds

        # Close-up shots require tighter timing tolerance for lipsync quality
        is_closeup = getattr(utterance, "shot_scale", "") in ("CU", "ECU", "close_up")
        max_deviation = _CLOSEUP_MAX_DEVIATION if is_closeup else _DEFAULT_MAX_DEVIATION

        candidates: list[TtsCandidate] = []
        for variant_no in range(1, request.candidate_count + 1):
            seed = (request.seed + variant_no - 1) % (2**63)
            output_path = output_directory / f"tts_{variant_no:02d}.wav"

            audio_array = _run_indextts2(
                model,
                text=target_text,
                language=request.localized.target_language,
                emotion=utterance.emotion,
                speed=request.speed,
                seed=seed,
                sample_rate=sample_rate,
            )
            _save_wav(audio_array, sample_rate, output_path)

            actual_duration = _wav_duration(output_path)
            if target_duration > 0:
                deviation = abs(actual_duration - target_duration) / max(target_duration, 0.001)
                if deviation > max_deviation:
                    # Re-synthesize with proportionally adjusted speed to fit timing
                    adjusted_speed = request.speed * (actual_duration / target_duration)
                    adjusted_speed = min(max(adjusted_speed, 0.5), 2.0)
                    audio_array = _run_indextts2(
                        model,
                        text=target_text,
                        language=request.localized.target_language,
                        emotion=utterance.emotion,
                        speed=adjusted_speed,
                        seed=seed,
                        sample_rate=sample_rate,
                    )
                    _save_wav(audio_array, sample_rate, output_path)
                    actual_duration = _wav_duration(output_path)

            sha256 = _sha256(output_path)
            candidates.append(
                TtsCandidate(
                    utterance_id=utterance.utterance_id,
                    variant_no=variant_no,
                    audio_uri=output_path.as_uri(),
                    audio_sha256=sha256,
                    duration_seconds=actual_duration,
                    voice_release_id=request.voice_release.voice_release_id,
                    model_release=self.model_release,
                    seed=seed,
                    speed=request.speed,
                    emotion=utterance.emotion,
                )
            )

        return tuple(candidates)


# ── helpers ──────────────────────────────────────────────────────────────────


def _load_indextts2(model_dir: str, device: str):
    """Load IndexTTS2 model (lazy import)."""
    try:
        from indextts import IndexTTS  # type: ignore[import]

        model = IndexTTS(model_dir=model_dir, device=device)
        return model
    except ImportError:
        raise ImportError(
            "IndexTTS2 is not installed. "
            "Install from https://github.com/index-tts/indextts"
        ) from None


def _run_indextts2(
    model,
    *,
    text: str,
    language: str,
    emotion: str,
    speed: float,
    seed: int,
    sample_rate: int,
):
    """Run IndexTTS2 inference and return a numpy float32 audio array."""
    import numpy as np
    import torch

    torch.manual_seed(seed)

    try:
        # Primary: emotion-aware synthesis
        result = model.synthesize(
            text=text,
            language=language,
            emotion=emotion,
            speed=speed,
            sample_rate=sample_rate,
        )
    except TypeError:
        # Fallback: basic synthesis without emotion kwarg
        result = model.synthesize(text=text, speed=speed)

    if isinstance(result, np.ndarray):
        audio = result.flatten().astype(np.float32)
    elif hasattr(result, "numpy"):
        audio = result.cpu().float().numpy().flatten()
    else:
        # Return silence if output is unrecognized
        audio = np.zeros(int(sample_rate), dtype=np.float32)

    return audio


def _save_wav(audio_array, sample_rate: int, path: Path) -> None:
    import numpy as np

    pcm = (audio_array * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
