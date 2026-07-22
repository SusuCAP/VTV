"""Unit tests for visual generation quality metrics."""

from __future__ import annotations

import pytest
from vtv_evaluation.visual_generation_metrics import (
    background_preservation_score,
    character_identity_score,
    lipsync_alignment_score,
    temporal_smoothness,
)


def test_character_identity_identical():
    v = [1.0, 0.0, 0.0]
    assert character_identity_score(v, v) == pytest.approx(1.0)


def test_character_identity_orthogonal():
    assert character_identity_score([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_character_identity_passthrough_range():
    a = [0.95, 0.1, 0.0]
    b = [1.0, 0.0, 0.0]
    score = character_identity_score(a, b)
    assert 0.0 <= score <= 1.0


def test_character_identity_empty():
    assert character_identity_score([], [1.0]) == 0.0
    assert character_identity_score([1.0], []) == 0.0


def test_temporal_smoothness_zero_deltas():
    assert temporal_smoothness([0.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_temporal_smoothness_high_deltas():
    score = temporal_smoothness([200.0, 210.0, 195.0])
    assert 0.0 <= score < 0.2


def test_temporal_smoothness_empty():
    assert temporal_smoothness([]) == 0.0


def test_background_preservation_identical():
    v = [0.5, 0.5, 0.5]
    assert background_preservation_score(v, v) == pytest.approx(1.0)


def test_lipsync_perfect_alignment():
    times = [0.0, 0.5, 1.0]
    score = lipsync_alignment_score(times, times)
    assert score == pytest.approx(1.0)


def test_lipsync_large_offset():
    audio = [0.0, 0.5]
    video = [0.5, 1.0]  # 500ms offset >> 100ms tolerance
    score = lipsync_alignment_score(audio, video)
    assert score == 0.0


def test_lipsync_empty():
    assert lipsync_alignment_score([], [0.1]) == 0.0
    assert lipsync_alignment_score([0.1], []) == 0.0
