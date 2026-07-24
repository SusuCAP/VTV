"""VoxCPM2 TTS adapter (P11-A).

Calls the VoxCPM2 HTTP inference endpoint (self-hosted or official API).
Implements the ``TtsAdapter`` protocol; all heavy packages are imported lazily.

Env vars:
    VTV_VOXCPM2_ENDPOINT   – base URL of the VoxCPM2 service (required)
    VTV_VOXCPM2_API_KEY    – Bearer token (optional)
    VTV_VOXCPM2_TIMEOUT    – request timeout in seconds (default: 120)
"""
from __future__ import annotations

import hashlib
import os
import wave
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import TtsCandidate, TtsRequest


@dataclass(frozen=True, slots=True)
class VoxCPM2Adapter:
    """VoxCPM2 multi-language TTS adapter (remote HTTP).

    VoxCPM2 supports 30 languages, 48 kHz, Voice Design, and controllable
    speaker cloning. Dispatches to the configured endpoint and writes WAV
    output to *output_directory*.
    """

    _release: str = field(default="voxcpm2@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def synthesize(
        self, request: TtsRequest, output_directory: Path
    ) -> tuple[TtsCandidate, ...]:
        """Generate *request.candidate_count* TTS variants via VoxCPM2 API."""
        import httpx

        endpoint = os.environ.get("VTV_VOXCPM2_ENDPOINT", "").rstrip("/")
        if not endpoint:
            raise RuntimeError(
                "VTV_VOXCPM2_ENDPOINT is not set. "
                "Point it to the VoxCPM2 inference service base URL."
            )
        api_key = os.environ.get("VTV_VOXCPM2_API_KEY", "")
        timeout = float(os.environ.get("VTV_VOXCPM2_TIMEOUT", "120"))

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        utterance = request.localized.utterance
        output_directory.mkdir(parents=True, exist_ok=True)

        candidates: list[TtsCandidate] = []
        for variant_no in range(1, request.candidate_count + 1):
            seed = (request.seed + variant_no - 1) % (2**63)
            payload = {
                "text": request.localized.target_text,
                "language": request.localized.target_language,
                "target_duration_seconds": utterance.duration_seconds,
                "emotion": utterance.emotion,
                "speed": request.speed,
                "seed": seed,
                "sample_rate": 48000,
            }

            resp = httpx.post(
                f"{endpoint}/v1/synthesize",
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()

            # Response: {"audio_base64": "...", "sample_rate": 48000, "duration_seconds": X}
            data = resp.json()
            import base64
            audio_bytes = base64.b64decode(data["audio_base64"])
            actual_duration = float(data.get("duration_seconds", utterance.duration_seconds))
            sample_rate = int(data.get("sample_rate", 48000))

            output_path = output_directory / f"tts_{variant_no:02d}.wav"
            _write_pcm_wav(audio_bytes, sample_rate, output_path)

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


def _write_pcm_wav(pcm_bytes: bytes, sample_rate: int, path: Path) -> None:
    """Write raw 16-bit PCM bytes to a WAV file."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
