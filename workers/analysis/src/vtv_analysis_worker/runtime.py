import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
from vtv_analysis import (
    AudioAnalysis,
    AudioAnalysisPipeline,
    ProjectSynthesis,
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

    def post_json(
        self,
        config: ModelEndpoint,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


class HttpxInferenceTransport:
    @staticmethod
    def _headers(config: ModelEndpoint) -> dict[str, str]:
        return (
            {"Authorization": f"Bearer {config.bearer_token}"}
            if config.bearer_token
            else {}
        )

    def post_media(
        self,
        config: ModelEndpoint,
        media: Path,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        headers = self._headers(config)
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

    def post_json(
        self,
        config: ModelEndpoint,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = httpx.post(
                config.endpoint,
                headers=self._headers(config),
                json=payload,
                timeout=config.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RemoteInferenceError(
                f"remote synthesis failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(body, dict):
            raise RemoteInferenceError("remote synthesis response must be a JSON object")
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


class RemoteProjectSynthesizer:
    def __init__(self, config: ModelEndpoint, transport: InferenceTransport) -> None:
        self._config = config
        self._transport = transport

    @property
    def model_release(self) -> str:
        return self._config.release

    def synthesize_series(
        self,
        project_id: str,
        source_locale: str,
        target_locale: str,
        episodes: tuple[tuple[str, AudioAnalysis, VisionAnalysis], ...],
        bible_version: int = 1,
        anchor_pack_version: int = 1,
    ) -> ProjectSynthesis:
        self._config.assert_allowed()
        if not episodes:
            raise ValueError("project synthesis requires at least one episode")
        response = self._transport.post_json(
            self._config,
            {
                "project_id": project_id,
                "source_locale": source_locale,
                "target_locale": target_locale,
                "bible_version": bible_version,
                "anchor_pack_version": anchor_pack_version,
                "episodes": [
                    {
                        "episode_id": episode_id,
                        "audio_analysis": audio.model_dump(mode="json"),
                        "vision_analysis": vision.model_dump(mode="json"),
                    }
                    for episode_id, audio, vision in episodes
                ],
                "requirements": {
                    "evidence_required": True,
                    "allowed_evidence_types": [
                        "TRANSCRIPT",
                        "PERSON_TRACK",
                        "SCENE",
                        "OCR",
                        "GEOMETRY",
                    ],
                },
            },
        )
        try:
            synthesis = ProjectSynthesis.model_validate(response["synthesis"])
        except (KeyError, ValueError) as exc:
            raise RemoteInferenceError("invalid remote project synthesis response") from exc
        missing = [
            f"character:{item.character_id}"
            for item in synthesis.bible.characters
            if not item.evidence
        ]
        missing.extend(
            f"location:{item.location_id}"
            for item in synthesis.bible.locations
            if not item.evidence
        )
        missing.extend(
            f"glossary:{item.source}"
            for item in synthesis.bible.glossary
            if not item.evidence
        )
        missing.extend(
            f"continuity:{item.snapshot_id}"
            for item in synthesis.continuity
            if not item.evidence
        )
        if missing:
            raise RemoteInferenceError(
                "project synthesis contains facts without source evidence: "
                + ", ".join(missing[:20])
            )
        return synthesis


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
