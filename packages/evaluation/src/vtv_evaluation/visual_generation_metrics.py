"""Visual generation quality metrics for Phase 4 model admission gates.

All functions accept the correct type signatures for protocol verification.
Passthrough implementations return deterministic fixed values that satisfy
the default VISUAL_GENERATION_POLICY thresholds; real implementations replace
these with model-driven computations.
"""

from __future__ import annotations

import math


def character_identity_score(
    candidate_embedding: list[float],
    reference_embedding: list[float],
) -> float:
    """Cosine similarity of character identity embeddings.

    Returns a value in [0, 1] where 1 means identical embeddings.
    Passthrough: returns 0.85 when both lists are non-empty.
    """
    if not candidate_embedding or not reference_embedding:
        return 0.0
    if len(candidate_embedding) != len(reference_embedding):
        # Dimension mismatch — treat as zero similarity
        return 0.0
    dot = sum(a * b for a, b in zip(candidate_embedding, reference_embedding, strict=False))
    mag_a = math.sqrt(sum(a * a for a in candidate_embedding))
    mag_b = math.sqrt(sum(b * b for b in reference_embedding))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (mag_a * mag_b)))


def temporal_smoothness(frame_deltas: list[float]) -> float:
    """Mean temporal coherence score derived from per-frame L2 distances.

    High delta (large motion between consecutive frames) → low score.
    Passthrough: returns 0.9 when the list is non-empty.
    Score = max(0, 1 - mean_delta / 255) normalised to [0, 1].
    """
    if not frame_deltas:
        return 0.0
    mean_delta = sum(frame_deltas) / len(frame_deltas)
    return 1.0 / (1.0 + mean_delta)


def background_preservation_score(
    source_bg_embedding: list[float],
    candidate_bg_embedding: list[float],
) -> float:
    """Background retention rate via cosine similarity of scene embeddings.

    Passthrough: returns 0.92 when both lists are non-empty.
    Identical embeddings → 1.0; orthogonal → 0.0.
    """
    return character_identity_score(source_bg_embedding, candidate_bg_embedding)


def lipsync_alignment_score(
    audio_phoneme_times: list[float],
    video_mouth_motion_times: list[float],
) -> float:
    """Temporal alignment between audio phoneme onsets and mouth motion peaks.

    Both lists must be sorted ascending. Score = 1 - mean_abs_offset / tolerance,
    where tolerance = 100 ms.  Passthrough: returns 0.88 when both lists non-empty.
    """
    if not audio_phoneme_times or not video_mouth_motion_times:
        return 0.0
    # Pair nearest audio → video times
    used: set[int] = set()
    offsets: list[float] = []
    for at in audio_phoneme_times:
        best_idx = min(
            (i for i in range(len(video_mouth_motion_times)) if i not in used),
            key=lambda i: abs(video_mouth_motion_times[i] - at),
            default=None,
        )
        if best_idx is not None:
            offsets.append(abs(video_mouth_motion_times[best_idx] - at))
            used.add(best_idx)
    if not offsets:
        return 0.0
    tolerance = 0.1  # 100 ms
    return max(0.0, min(1.0, 1.0 - sum(offsets) / (len(offsets) * tolerance)))
