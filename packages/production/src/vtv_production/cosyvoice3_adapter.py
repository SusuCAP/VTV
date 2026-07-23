"""CosyVoice3 TTS adapter (P8-E).

Implements the ``TtsAdapter`` protocol using CosyVoice3 for multi-language
speaker-consistent speech synthesis.

All heavy imports are deferred to ``synthesize()`` so the class can be imported
in CPU/CI environments without the CosyVoice3 package installed.
"""
from __future__ import annotations

import hashlib
import os
import wave
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import TtsCandidate, TtsRequest


@dataclass(frozen=True, slots=True)
class CosyVoice3Adapter:
    """CosyVoice3 text-to-speech adapter.

    Env vars (read at inference time):
        VTV_COSYVOICE_MODEL_DIR  – local path or HuggingFace model ID
                                   (default: ``/models/cosyvoice3``)
        VTV_COSYVOICE_DEVICE     – ``cuda`` (default) | ``cpu``
        VTV_COSYVOICE_SAMPLE_RATE– output sample rate in Hz (default: 22050)
    """

    _release: str = field(default="cosyvoice3@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def synthesize(
        self, request: TtsRequest, output_directory: Path
    ) -> tuple[TtsCandidate, ...]:
        """Synthesize *request.candidate_count* TTS variants for the utterance."""
        import torch

        model_dir = os.environ.get("VTV_COSYVOICE_MODEL_DIR", "/models/cosyvoice3")
        device = os.environ.get(
            "VTV_COSYVOICE_DEVICE", "cuda" if torch.cuda.is_available() else "cpu"
        )
        sample_rate = int(os.environ.get("VTV_COSYVOICE_SAMPLE_RATE", "22050"))

        cosyvoice = _load_cosyvoice3(model_dir, device)
        output_directory.mkdir(parents=True, exist_ok=True)

        utterance = request.localized.utterance
        target_text = request.localized.target_text
        target_duration = utterance.duration_seconds

        candidates: list[TtsCandidate] = []
        for variant_no in range(1, request.candidate_count + 1):
            seed = (request.seed + variant_no - 1) % (2**63)
            output_path = output_directory / f"tts_{variant_no:02d}.wav"

            audio_array = _run_cosyvoice3(
                cosyvoice,
                text=target_text,
                target_language=request.localized.target_language,
                speed=request.speed,
                seed=seed,
                target_duration_seconds=target_duration,
                emotion=utterance.emotion,
            )

            _save_wav(audio_array, sample_rate, output_path)

            # Verify duration deviation
            actual_duration = _wav_duration(output_path)
            deviation = abs(actual_duration - target_duration) / max(target_duration, 0.001)
            if deviation > 0.15:
                # Re-generate with speed adjustment to fit timing
                adjusted_speed = request.speed * (actual_duration / target_duration)
                audio_array = _run_cosyvoice3(
                    cosyvoice,
                    text=target_text,
                    target_language=request.localized.target_language,
                    speed=min(max(adjusted_speed, 0.5), 2.0),
                    seed=seed,
                    target_duration_seconds=target_duration,
                    emotion=utterance.emotion,
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


def _load_cosyvoice3(model_dir: str, device: str):
    """Load CosyVoice3 model (lazy import)."""
    try:
        # Official CosyVoice3 package
        from cosyvoice.cli.cosyvoice import CosyVoice3  # type: ignore[import]
        model = CosyVoice3(model_dir)
        model.model.to(device)
        return model
    except ImportError:
        raise ImportError(
            "CosyVoice3 is not installed. "
            "Install from https://github.com/FunAudioLLM/CosyVoice "
            "and ensure VTV_COSYVOICE_MODEL_DIR points to the model weights."
        ) from None


def _run_cosyvoice3(
    model,
    *,
    text: str,
    target_language: str,
    speed: float,
    seed: int,
    target_duration_seconds: float,
    emotion: str,
):
    """Run CosyVoice3 inference and return a numpy audio array."""
    import numpy as np
    import torch

    torch.manual_seed(seed)

    # CosyVoice3 inference_instruct2 for emotional multi-language synthesis
    try:
        outputs = list(
            model.inference_instruct2(
                text,
                f"[{emotion}]",
                speed=speed,
            )
        )
    except AttributeError:
        # Fallback to basic inference
        outputs = list(model.inference_sft(text, speed=speed))

    if not outputs:
        # Return silence of the target duration
        n_samples = int(target_duration_seconds * 22050)
        return np.zeros(n_samples, dtype=np.float32)

    # Concatenate all output chunks
    audio_chunks = [o["tts_speech"].numpy().flatten() for o in outputs]
    return np.concatenate(audio_chunks)


def _save_wav(audio_array, sample_rate: int, path: Path) -> None:

    import numpy as np

    # Convert to 16-bit PCM
    pcm = (audio_array * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
