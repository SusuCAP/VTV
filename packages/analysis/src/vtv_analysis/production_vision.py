from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Protocol
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, ConfigDict

from .vision import (
    GeometryObservation,
    OcrObservation,
    PersonObservation,
    SceneObservation,
    ShotSpan,
)


class VisionBackendOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    people: tuple[PersonObservation, ...] = ()
    scenes: tuple[SceneObservation, ...] = ()
    ocr: tuple[OcrObservation, ...] = ()
    geometry: tuple[GeometryObservation, ...] = ()


class VisionModelBackend(Protocol):
    def analyze(self, media: Path, shots: tuple[ShotSpan, ...]) -> VisionBackendOutput: ...


class LazyQwen3VlBackend:
    def __init__(
        self,
        *,
        model_name: str = "Qwen/Qwen3-VL-8B-Instruct",
        device_map: str = "auto",
        max_new_tokens: int = 8192,
    ) -> None:
        self.model_name = model_name
        self.device_map = device_map
        self.max_new_tokens = max_new_tokens
        self._model = None
        self._processor = None

    def _load(self):
        if self._model is None or self._processor is None:
            try:
                from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
            except ImportError as exc:
                raise RuntimeError(
                    "Qwen3-VL runtime is not installed in this worker image"
                ) from exc
            self._model = Qwen3VLForConditionalGeneration.from_pretrained(
                self.model_name,
                torch_dtype="auto",
                device_map=self.device_map,
            )
            self._processor = AutoProcessor.from_pretrained(self.model_name)
        return self._model, self._processor

    def analyze(self, media: Path, shots: tuple[ShotSpan, ...]) -> VisionBackendOutput:
        try:
            from qwen_vl_utils import process_vision_info
        except ImportError as exc:
            raise RuntimeError("qwen-vl-utils is not installed in this worker image") from exc
        model, processor = self._load()
        prompt = _vision_prompt(shots)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "video", "video": media.resolve().as_uri()},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(model.device)
        generated = model.generate(**inputs, max_new_tokens=self.max_new_tokens)
        trimmed = [
            output[len(source) :]
            for source, output in zip(inputs.input_ids, generated, strict=True)
        ]
        decoded = processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]
        return VisionBackendOutput.model_validate_json(_json_payload(decoded))


@dataclass(slots=True)
class CachedVisionBackend:
    backend: VisionModelBackend
    _key: tuple[str, tuple[tuple[int, float, float], ...]] | None = field(
        default=None, init=False
    )
    _value: VisionBackendOutput | None = field(default=None, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def analyze(self, media_uri: str, shots: tuple[ShotSpan, ...]) -> VisionBackendOutput:
        media = _media_path(media_uri)
        key = (
            str(media.resolve()),
            tuple((shot.shot_no, shot.start_seconds, shot.end_seconds) for shot in shots),
        )
        with self._lock:
            if self._key != key or self._value is None:
                value = self.backend.analyze(media, shots)
                _validate_observation_shots(value, shots)
                self._key = key
                self._value = value
            return self._value


@dataclass(frozen=True, slots=True)
class QwenPersonAdapter:
    backend: CachedVisionBackend
    model_release: str

    def analyze(
        self, media_uri: str, shots: tuple[ShotSpan, ...]
    ) -> tuple[PersonObservation, ...]:
        return self.backend.analyze(media_uri, shots).people


@dataclass(frozen=True, slots=True)
class QwenSceneAdapter:
    backend: CachedVisionBackend
    model_release: str

    def analyze(
        self, media_uri: str, shots: tuple[ShotSpan, ...]
    ) -> tuple[SceneObservation, ...]:
        return self.backend.analyze(media_uri, shots).scenes


@dataclass(frozen=True, slots=True)
class QwenOcrAdapter:
    backend: CachedVisionBackend
    model_release: str

    def analyze(
        self, media_uri: str, shots: tuple[ShotSpan, ...]
    ) -> tuple[OcrObservation, ...]:
        return self.backend.analyze(media_uri, shots).ocr


@dataclass(frozen=True, slots=True)
class QwenGeometryAdapter:
    backend: CachedVisionBackend
    model_release: str

    def analyze(
        self, media_uri: str, shots: tuple[ShotSpan, ...]
    ) -> tuple[GeometryObservation, ...]:
        return self.backend.analyze(media_uri, shots).geometry


def _media_path(media_uri: str) -> Path:
    parsed = urlparse(media_uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError("production vision adapter requires local media")
    path = Path(unquote(parsed.path if parsed.scheme else media_uri))
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _json_payload(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1])
            if stripped.lstrip().startswith("json"):
                stripped = stripped.lstrip()[4:].lstrip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("vision model response must be a JSON object")
    return json.dumps(parsed, ensure_ascii=False)


def _validate_observation_shots(
    output: VisionBackendOutput, shots: tuple[ShotSpan, ...]
) -> None:
    spans = (*output.people, *output.scenes, *output.ocr, *output.geometry)
    for observation in spans:
        if not any(
            shot.start_seconds <= observation.start_seconds
            and observation.end_seconds <= shot.end_seconds
            for shot in shots
        ):
            raise ValueError("vision observation is not contained in one declared shot")


def _vision_prompt(shots: tuple[ShotSpan, ...]) -> str:
    shot_payload = [shot.model_dump(mode="json") for shot in shots]
    return (
        "Analyze only the declared shot intervals and return one strict JSON object matching "
        "VisionBackendOutput: people, scenes, ocr, geometry. All boxes use normalized x/y/width/"
        "height in [0,1], all confidence values use [0,1], and every observation must be fully "
        f"inside one interval. No markdown. Shot intervals: {json.dumps(shot_payload)}"
    )
