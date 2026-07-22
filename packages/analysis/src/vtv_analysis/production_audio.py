from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

from .contracts import SpeakerTurn, SpeechSegment, TranscriptSegment, TranscriptWord


def _audio_path(audio_uri: str) -> Path:
    parsed = urlparse(audio_uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError(f"production audio adapter requires local media, got {parsed.scheme}")
    path = Path(unquote(parsed.path if parsed.scheme else audio_uri))
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


@dataclass(frozen=True, slots=True)
class RawSpeech:
    start_seconds: float
    end_seconds: float
    confidence: float


@dataclass(frozen=True, slots=True)
class RawWord:
    start_seconds: float
    end_seconds: float
    text: str
    confidence: float


@dataclass(frozen=True, slots=True)
class RawTranscript:
    start_seconds: float
    end_seconds: float
    text: str
    language: str
    words: tuple[RawWord, ...]


@dataclass(frozen=True, slots=True)
class RawSpeakerTurn:
    start_seconds: float
    end_seconds: float
    speaker_id: str
    confidence: float


class FasterWhisperBackend(Protocol):
    def detect(self, audio_path: Path) -> tuple[RawSpeech, ...]: ...

    def transcribe(
        self, audio_path: Path, language_hint: str | None
    ) -> tuple[RawTranscript, ...]: ...


class DiarizationBackend(Protocol):
    def identify(self, audio_path: Path) -> tuple[RawSpeakerTurn, ...]: ...


class LazyFasterWhisperBackend:
    def __init__(
        self,
        *,
        model_name: str = "large-v3",
        device: str = "cuda",
        compute_type: str = "float16",
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper is not installed in this worker image"
                ) from exc
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def detect(self, audio_path: Path) -> tuple[RawSpeech, ...]:
        try:
            from faster_whisper.audio import decode_audio
            from faster_whisper.vad import VadOptions, get_speech_timestamps
        except ImportError as exc:
            raise RuntimeError("faster-whisper VAD runtime is unavailable") from exc
        sampling_rate = 16000
        waveform = decode_audio(str(audio_path), sampling_rate=sampling_rate)
        timestamps = get_speech_timestamps(waveform, VadOptions())
        return tuple(
            RawSpeech(
                start_seconds=float(item["start"]) / sampling_rate,
                end_seconds=float(item["end"]) / sampling_rate,
                confidence=1.0,
            )
            for item in timestamps
        )

    def transcribe(
        self, audio_path: Path, language_hint: str | None
    ) -> tuple[RawTranscript, ...]:
        language = language_hint.split("-", 1)[0] if language_hint else None
        segments, info = self._load_model().transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True,
            vad_filter=False,
        )
        detected_language = language_hint or str(info.language)
        output: list[RawTranscript] = []
        for segment in segments:
            words = tuple(
                RawWord(
                    start_seconds=float(word.start),
                    end_seconds=float(word.end),
                    text=str(word.word).strip(),
                    confidence=float(word.probability),
                )
                for word in (segment.words or ())
                if str(word.word).strip() and float(word.end) > float(word.start)
            )
            text = str(segment.text).strip()
            if text and float(segment.end) > float(segment.start):
                output.append(
                    RawTranscript(
                        start_seconds=float(segment.start),
                        end_seconds=float(segment.end),
                        text=text,
                        language=detected_language,
                        words=words,
                    )
                )
        return tuple(output)


class LazyPyannoteBackend:
    def __init__(
        self,
        *,
        model_name: str = "pyannote/speaker-diarization-community-1",
        token_env: str = "HF_TOKEN",
        device: str = "cuda",
    ) -> None:
        self.model_name = model_name
        self.token_env = token_env
        self.device = device
        self._pipeline = None

    def _load_pipeline(self):
        if self._pipeline is None:
            token = os.getenv(self.token_env)
            if not token:
                raise RuntimeError(f"{self.token_env} is required for gated diarization weights")
            try:
                from pyannote.audio import Pipeline
            except ImportError as exc:
                raise RuntimeError("pyannote.audio is not installed in this worker image") from exc
            self._pipeline = Pipeline.from_pretrained(self.model_name, token=token)
            if self.device:
                try:
                    import torch
                except ImportError as exc:
                    raise RuntimeError("torch is required for pyannote device placement") from exc
                self._pipeline.to(torch.device(self.device))
        return self._pipeline

    def identify(self, audio_path: Path) -> tuple[RawSpeakerTurn, ...]:
        output = self._load_pipeline()(str(audio_path))
        annotation = getattr(output, "speaker_diarization", output)
        return tuple(
            RawSpeakerTurn(
                start_seconds=float(turn.start),
                end_seconds=float(turn.end),
                speaker_id=f"cluster:{speaker}",
                # community-1 does not expose calibrated turn confidence.
                confidence=0.5,
            )
            for turn, _, speaker in annotation.itertracks(yield_label=True)
            if float(turn.end) > float(turn.start)
        )


@dataclass(frozen=True, slots=True)
class FasterWhisperVadAdapter:
    backend: FasterWhisperBackend
    model_release: str

    def detect(self, audio_uri: str, duration_seconds: float) -> tuple[SpeechSegment, ...]:
        spans = tuple(
            SpeechSegment(
                start_seconds=item.start_seconds,
                end_seconds=item.end_seconds,
                confidence=item.confidence,
            )
            for item in self.backend.detect(_audio_path(audio_uri))
        )
        if any(item.end_seconds > duration_seconds for item in spans):
            raise ValueError("VAD output exceeds audio duration")
        return spans


@dataclass(frozen=True, slots=True)
class FasterWhisperAsrAdapter:
    backend: FasterWhisperBackend
    model_release: str

    def transcribe(
        self,
        audio_uri: str,
        speech: tuple[SpeechSegment, ...],
        language_hint: str | None,
    ) -> tuple[TranscriptSegment, ...]:
        del speech
        return tuple(
            TranscriptSegment(
                start_seconds=item.start_seconds,
                end_seconds=item.end_seconds,
                text=item.text,
                language=item.language,
                words=tuple(
                    TranscriptWord(
                        start_seconds=word.start_seconds,
                        end_seconds=word.end_seconds,
                        text=word.text,
                        confidence=word.confidence,
                    )
                    for word in item.words
                ),
            )
            for item in self.backend.transcribe(_audio_path(audio_uri), language_hint)
        )


@dataclass(frozen=True, slots=True)
class PyannoteDiarizationAdapter:
    backend: DiarizationBackend
    model_release: str

    def identify(
        self, audio_uri: str, speech: tuple[SpeechSegment, ...]
    ) -> tuple[SpeakerTurn, ...]:
        del speech
        return tuple(
            SpeakerTurn(
                start_seconds=item.start_seconds,
                end_seconds=item.end_seconds,
                speaker_id=item.speaker_id,
                confidence=item.confidence,
            )
            for item in self.backend.identify(_audio_path(audio_uri))
        )
