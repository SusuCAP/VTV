from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field
from vtv_media import probe_media
from vtv_production import TtsCandidate, TtsRequest


class TtsAccessDeniedError(PermissionError):
    pass


class TtsInferenceError(RuntimeError):
    pass


class RawTtsCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_no: int = Field(ge=1, le=4)
    audio_base64: str = Field(min_length=1)
    seed: int = Field(ge=0, le=2**63 - 1)


class RawTtsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: tuple[RawTtsCandidate, ...] = Field(min_length=1, max_length=4)


@dataclass(frozen=True, slots=True)
class TtsEndpoint:
    endpoint: str
    model_release: str
    license_id: str
    approved_for_automation: bool
    bearer_token: str | None = None
    timeout_seconds: float = 600

    def assert_allowed(self) -> None:
        if not self.approved_for_automation:
            raise TtsAccessDeniedError(
                f"model release {self.model_release} is not approved for automated execution"
            )
        if not self.license_id.strip():
            raise TtsAccessDeniedError(
                f"model release {self.model_release} has no license record"
            )
        if not self.endpoint.startswith(
            ("https://", "http://127.0.0.1", "http://localhost")
        ):
            raise TtsAccessDeniedError("TTS endpoint must use HTTPS or localhost")


class TtsTransport(Protocol):
    def synthesize(self, config: TtsEndpoint, payload: dict[str, Any]) -> RawTtsResponse: ...


class HttpxTtsTransport:
    def synthesize(self, config: TtsEndpoint, payload: dict[str, Any]) -> RawTtsResponse:
        headers = (
            {"Authorization": f"Bearer {config.bearer_token}"}
            if config.bearer_token
            else {}
        )
        try:
            response = httpx.post(
                config.endpoint,
                headers=headers,
                json=payload,
                timeout=config.timeout_seconds,
            )
            response.raise_for_status()
            return RawTtsResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise TtsInferenceError(f"remote TTS failed: {type(exc).__name__}") from exc


@dataclass(frozen=True, slots=True)
class RemoteTtsAdapter:
    config: TtsEndpoint
    transport: TtsTransport

    @property
    def model_release(self) -> str:
        return self.config.model_release

    def synthesize(
        self, request: TtsRequest, output_directory: Path
    ) -> tuple[TtsCandidate, ...]:
        self.config.assert_allowed()
        output_directory.mkdir(parents=True, exist_ok=True)
        response = self.transport.synthesize(self.config, _payload(request))
        if len(response.candidates) != request.candidate_count:
            raise TtsInferenceError("remote TTS candidate count does not match request")
        if {item.variant_no for item in response.candidates} != set(
            range(1, request.candidate_count + 1)
        ):
            raise TtsInferenceError("remote TTS variant numbers must be contiguous")
        results: list[TtsCandidate] = []
        for item in sorted(response.candidates, key=lambda value: value.variant_no):
            try:
                audio = base64.b64decode(item.audio_base64, validate=True)
            except ValueError as exc:
                raise TtsInferenceError("remote TTS returned invalid base64 audio") from exc
            destination = output_directory / f"variant-{item.variant_no:02d}.wav"
            partial = destination.with_suffix(".wav.part")
            partial.write_bytes(audio)
            partial.replace(destination)
            media = probe_media(destination, require_video=False)
            digest = _sha256(destination)
            results.append(
                TtsCandidate(
                    utterance_id=request.localized.utterance.utterance_id,
                    variant_no=item.variant_no,
                    audio_uri=destination.resolve().as_uri(),
                    audio_sha256=digest,
                    duration_seconds=media.duration_seconds,
                    voice_release_id=request.voice_release.voice_release_id,
                    model_release=self.model_release,
                    seed=item.seed,
                    speed=request.speed,
                    emotion=request.localized.utterance.emotion,
                )
            )
        return tuple(results)


def _payload(request: TtsRequest) -> dict[str, Any]:
    return {
        "utterance_id": request.localized.utterance.utterance_id,
        "text": request.localized.target_text,
        "language": request.localized.target_language,
        "market": request.localized.target_market,
        "emotion": request.localized.utterance.emotion,
        "target_duration_seconds": request.target_duration_seconds,
        "voice_release_id": str(request.voice_release.voice_release_id),
        "reference_asset_sha256s": request.voice_release.reference_asset_sha256s,
        "candidate_count": request.candidate_count,
        "seed": request.seed,
        "speed": request.speed,
    }


def _sha256(path: Path) -> str:
    from hashlib import sha256

    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
