from __future__ import annotations

import struct
import wave
from dataclasses import dataclass
from math import sqrt
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PcmSignal:
    sample_rate: int
    samples: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("PCM sample rate must be positive")
        if not self.samples:
            raise ValueError("PCM signal cannot be empty")
        if any(not -1.0001 <= value <= 1.0001 for value in self.samples):
            raise ValueError("PCM samples must be normalized")


def read_pcm_wav(path: Path) -> PcmSignal:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frame_count = handle.getnframes()
        compression = handle.getcomptype()
        payload = handle.readframes(frame_count)
    if compression != "NONE":
        raise ValueError("Golden metrics require uncompressed PCM WAV")
    if channels < 1:
        raise ValueError("PCM WAV has no channels")
    values = _decode_samples(payload, sample_width)
    if len(values) % channels:
        raise ValueError("PCM WAV payload is not aligned to channels")
    mono = tuple(
        sum(values[index : index + channels]) / channels
        for index in range(0, len(values), channels)
    )
    return PcmSignal(sample_rate=sample_rate, samples=mono)


def signal_fidelity(reference: PcmSignal, predicted: PcmSignal) -> float:
    expected, actual = _aligned(reference, predicted)
    if expected == actual:
        return 1.0
    denominator = sqrt(sum(value * value for value in expected))
    actual_norm = sqrt(sum(value * value for value in actual))
    if denominator == 0:
        return 1.0 if actual_norm == 0 else 0.0
    if actual_norm == 0:
        return 0.0
    cosine = sum(left * right for left, right in zip(expected, actual, strict=True))
    return max(0.0, min(1.0, cosine / (denominator * actual_norm)))


def leakage_control(reference_target: PcmSignal, predicted_other: PcmSignal) -> float:
    target, other = _aligned(reference_target, predicted_other)
    if target == other and any(target):
        return 0.0
    target_norm = sqrt(sum(value * value for value in target))
    other_norm = sqrt(sum(value * value for value in other))
    if target_norm == 0 or other_norm == 0:
        return 1.0
    correlation = sum(left * right for left, right in zip(target, other, strict=True))
    return max(0.0, 1.0 - min(1.0, abs(correlation) / (target_norm * other_norm)))


def reconstruction_accuracy(
    source: PcmSignal, dialogue: PcmSignal, background: PcmSignal
) -> float:
    expected, predicted_dialogue = _aligned(source, dialogue)
    _, predicted_background = _aligned(source, background)
    reconstructed = [
        left + right
        for left, right in zip(predicted_dialogue, predicted_background, strict=True)
    ]
    signal_rms = sqrt(sum(value * value for value in expected) / len(expected))
    error_rms = sqrt(
        sum(
            (left - right) ** 2
            for left, right in zip(expected, reconstructed, strict=True)
        )
        / len(expected)
    )
    if signal_rms == 0:
        return 1.0 if error_rms == 0 else 0.0
    return max(0.0, 1.0 - error_rms / signal_rms)


def _aligned(left: PcmSignal, right: PcmSignal) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if left.sample_rate != right.sample_rate:
        raise ValueError("PCM sample rates differ")
    if len(left.samples) != len(right.samples):
        raise ValueError("PCM signal lengths differ")
    return left.samples, right.samples


def _decode_samples(payload: bytes, sample_width: int) -> tuple[float, ...]:
    if sample_width == 1:
        return tuple((value - 128) / 128 for value in payload)
    if sample_width == 2:
        count = len(payload) // 2
        return tuple(value / 32768 for value in struct.unpack(f"<{count}h", payload))
    if sample_width == 3:
        values = []
        for index in range(0, len(payload), 3):
            raw = int.from_bytes(payload[index : index + 3], "little", signed=False)
            signed = raw - (1 << 24) if raw & (1 << 23) else raw
            values.append(signed / (1 << 23))
        return tuple(values)
    if sample_width == 4:
        count = len(payload) // 4
        return tuple(value / (1 << 31) for value in struct.unpack(f"<{count}i", payload))
    raise ValueError(f"unsupported PCM sample width: {sample_width}")
