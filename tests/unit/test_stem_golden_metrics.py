import struct
import wave
from pathlib import Path

import pytest
from vtv_evaluation import (
    PcmSignal,
    leakage_control,
    read_pcm_wav,
    reconstruction_accuracy,
    signal_fidelity,
)


def _signal(values: tuple[float, ...]) -> PcmSignal:
    return PcmSignal(sample_rate=48000, samples=values)


def test_stem_metrics_score_fidelity_leakage_and_reconstruction() -> None:
    dialogue = _signal((0.5, -0.5, 0.25, -0.25))
    background = _signal((0.1, 0.1, -0.1, -0.1))
    source = _signal(
        tuple(
            left + right
            for left, right in zip(dialogue.samples, background.samples, strict=True)
        )
    )

    assert signal_fidelity(dialogue, dialogue) == 1
    assert leakage_control(dialogue, _signal((0, 0, 0, 0))) == 1
    assert leakage_control(dialogue, dialogue) == 0
    assert reconstruction_accuracy(source, dialogue, background) == 1


def test_stem_metrics_reject_sample_rate_or_length_mismatch() -> None:
    signal = _signal((0.1, 0.2))
    with pytest.raises(ValueError, match="sample rates"):
        signal_fidelity(signal, PcmSignal(sample_rate=16000, samples=(0.1, 0.2)))
    with pytest.raises(ValueError, match="lengths"):
        signal_fidelity(signal, _signal((0.1,)))


def test_pcm_reader_decodes_stereo_int16_to_mono(tmp_path: Path) -> None:
    path = tmp_path / "stereo.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(struct.pack("<4h", 16384, 0, -16384, 0))

    signal = read_pcm_wav(path)

    assert signal.sample_rate == 48000
    assert signal.samples == pytest.approx((0.25, -0.25))
