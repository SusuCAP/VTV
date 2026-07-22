import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
from vtv_analysis import (
    AudioAnalysis,
    AudioAnalysisPipeline,
    VisionAnalysis,
    VisionAnalysisPipeline,
)


class ModelAccessDeniedError(PermissionError):
    pass


class RemoteInferenceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelEndpoint:
    endpoint: str
    release: str
    license_id: str
    approved_for_automation: bool
    bearer_token: str | None = None
    timeout_seconds: float = 600

    def assert_allowed(self) -> None:
        if not self.approved_for_automation:
            raise ModelAccessDeniedError(
                f"model release {self.release} is not approved for automated execution"
            )
        if not self.license_id.strip():
            raise ModelAccessDeniedError(f"model release {self.release} has no license record")
        if not self.endpoint.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ModelAccessDeniedError("remote inference endpoint must use HTTPS or localhost")


class InferenceTransport(Protocol):
    def post_media(
        self,
        config: ModelEndpoint,
        media: Path,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


class HttpxInferenceTransport:
    def post_media(
        self,
        config: ModelEndpoint,
        media: Path,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        headers = (
            {"Authorization": f"Bearer {config.bearer_token}"}
            if config.bearer_token
            else {}
        )
        try:
            with media.open("rb") as handle:
                response = httpx.post(
                    config.endpoint,
                    headers=headers,
                    data={"request": json.dumps(payload, ensure_ascii=False)},
                    files={"media": (media.name, handle, "application/octet-stream")},
                    timeout=config.timeout_seconds,
                )
            response.raise_for_status()
            body = response.json()
        except (OSError, httpx.HTTPError, ValueError) as exc:
            raise RemoteInferenceError(f"remote inference failed: {type(exc).__name__}") from exc
        if not isinstance(body, dict):
            raise RemoteInferenceError("remote inference response must be a JSON object")
        return body


@dataclass(frozen=True, slots=True)
class ReleaseHandle:
    model_release: str


class RemoteAudioAnalysisPipeline:
    def __init__(self, config: ModelEndpoint, transport: InferenceTransport) -> None:
        self._config = config
        self._transport = transport
        self.vad = ReleaseHandle(f"{config.release}:vad")
        self.asr = ReleaseHandle(f"{config.release}:asr-align")
        self.diarization = ReleaseHandle(f"{config.release}:diarization")

    def analyze(
        self, audio_uri: str, duration_seconds: float, language_hint: str | None = None
    ) -> AudioAnalysis:
        self._config.assert_allowed()
        media = _file_path(audio_uri)
        response = self._transport.post_media(
            self._config,
            media,
            {"duration_seconds": duration_seconds, "language_hint": language_hint},
        )
        try:
            analysis = AudioAnalysis.model_validate(response["analysis"])
        except (KeyError, ValueError) as exc:
            raise RemoteInferenceError("invalid remote audio analysis response") from exc
        if abs(analysis.duration_seconds - duration_seconds) > 0.05:
            raise RemoteInferenceError("remote audio analysis duration does not match input")
        return analysis


class RemoteVisionAnalysisPipeline:
    def __init__(self, config: ModelEndpoint, transport: InferenceTransport) -> None:
        self._config = config
        self._transport = transport
        self.people = ReleaseHandle(f"{config.release}:people")
        self.scenes = ReleaseHandle(f"{config.release}:scenes")
        self.ocr = ReleaseHandle(f"{config.release}:ocr")
        self.geometry = ReleaseHandle(f"{config.release}:geometry")

    def analyze(self, media_uri: str, duration_seconds: float, shots: tuple) -> VisionAnalysis:
        self._config.assert_allowed()
        response = self._transport.post_media(
            self._config,
            _file_path(media_uri),
            {
                "duration_seconds": duration_seconds,
                "shots": [shot.model_dump(mode="json") for shot in shots],
            },
        )
        try:
            analysis = VisionAnalysis.model_validate(response["analysis"])
        except (KeyError, ValueError) as exc:
            raise RemoteInferenceError("invalid remote vision analysis response") from exc
        if abs(analysis.duration_seconds - duration_seconds) > 0.05:
            raise RemoteInferenceError("remote vision analysis duration does not match input")
        return analysis


class FallbackAudioAnalysisPipeline:
    def __init__(
        self,
        primary: RemoteAudioAnalysisPipeline,
        fallback: AudioAnalysisPipeline,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self.vad = primary.vad
        self.asr = primary.asr
        self.diarization = primary.diarization

    def analyze(
        self, audio_uri: str, duration_seconds: float, language_hint: str | None = None
    ) -> AudioAnalysis:
        try:
            return self._primary.analyze(audio_uri, duration_seconds, language_hint)
        except RemoteInferenceError:
            self.vad = self._fallback.vad
            self.asr = self._fallback.asr
            self.diarization = self._fallback.diarization
            return self._fallback.analyze(audio_uri, duration_seconds, language_hint)


class FallbackVisionAnalysisPipeline:
    def __init__(
        self,
        primary: RemoteVisionAnalysisPipeline,
        fallback: VisionAnalysisPipeline,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self.people = primary.people
        self.scenes = primary.scenes
        self.ocr = primary.ocr
        self.geometry = primary.geometry

    def analyze(self, media_uri: str, duration_seconds: float, shots: tuple) -> VisionAnalysis:
        try:
            return self._primary.analyze(media_uri, duration_seconds, shots)
        except RemoteInferenceError:
            self.people = self._fallback.people
            self.scenes = self._fallback.scenes
            self.ocr = self._fallback.ocr
            self.geometry = self._fallback.geometry
            return self._fallback.analyze(media_uri, duration_seconds, shots)


def _file_path(uri: str) -> Path:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError("remote model transport requires a materialized file URI")
    path = Path(unquote(parsed.path))
    if not path.is_file():
        raise ValueError(f"model input does not exist: {path}")
    return path
