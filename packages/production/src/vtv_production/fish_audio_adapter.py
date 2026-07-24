"""Fish Audio S2 Pro TTS adapter (P11-A).

Calls the Fish Audio S2 Pro HTTP API for 80+ language high-emotion TTS.
Implements the ``TtsAdapter`` protocol; imports are lazy.

Env vars:
    VTV_FISH_AUDIO_API_KEY  – Fish Audio API key (required)
    VTV_FISH_AUDIO_MODEL    – model ID (default: fish-speech-s2-pro)
    VTV_FISH_AUDIO_TIMEOUT  – request timeout in seconds (default: 120)
    VTV_FISH_AUDIO_ENDPOINT – base URL (default: https://api.fish.audio)
"""
from __future__ import annotations

import hashlib
import os
import wave
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import TtsCandidate, TtsRequest


@dataclass(frozen=True, slots=True)
class FishAudioS2ProAdapter:
    """Fish Audio S2 Pro 80+ language, high-emotion TTS adapter."""

    _release: str = field(default="fish-audio-s2-pro@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def synthesize(
        self, request: TtsRequest, output_directory: Path
    ) -> tuple[TtsCandidate, ...]:
        """Generate *request.candidate_count* TTS variants via Fish Audio API."""
        import httpx

        api_key = os.environ.get("VTV_FISH_AUDIO_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "VTV_FISH_AUDIO_API_KEY is not set. "
                "Get an API key from https://fish.audio"
            )
        model_id = os.environ.get("VTV_FISH_AUDIO_MODEL", "fish-speech-s2-pro")
        endpoint = os.environ.get("VTV_FISH_AUDIO_ENDPOINT", "https://api.fish.audio").rstrip("/")
        timeout = float(os.environ.get("VTV_FISH_AUDIO_TIMEOUT", "120"))

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        utterance = request.localized.utterance
        output_directory.mkdir(parents=True, exist_ok=True)

        candidates: list[TtsCandidate] = []
        for variant_no in range(1, request.candidate_count + 1):
            seed = (request.seed + variant_no - 1) % (2**63)
            payload = {
                "model": model_id,
                "text": request.localized.target_text,
                "language": request.localized.target_language,
                "emotion": utterance.emotion,
                "speed": request.speed,
                "seed": seed,
                "format": "wav",
                "sample_rate": 44100,
            }

            resp = httpx.post(
                f"{endpoint}/v1/tts",
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()

            # Fish Audio returns raw WAV bytes
            audio_bytes = resp.content
            output_path = output_directory / f"tts_{variant_no:02d}.wav"
            output_path.write_bytes(audio_bytes)

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
