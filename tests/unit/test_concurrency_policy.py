from __future__ import annotations

from vtv_schemas.concurrency import DEFAULT_CONCURRENCY_POLICY, ConcurrencyPolicy


def test_default_concurrency_policy_values():
    p = DEFAULT_CONCURRENCY_POLICY
    assert p.max_concurrent_episodes == 3
    assert p.max_concurrent_visual_stages == 8
    assert p.max_concurrent_tts_stages == 10
    assert p.max_concurrent_lipsync_stages == 5
    assert p.max_concurrent_assembly_stages == 2


def test_get_stage_limit_visual():
    p = ConcurrencyPolicy()
    assert p.get_stage_limit("VISUAL_GENERATE") == p.max_concurrent_visual_stages
    assert p.get_stage_limit("VISUAL_QC") == p.max_concurrent_visual_stages


def test_get_stage_limit_tts():
    p = ConcurrencyPolicy()
    assert p.get_stage_limit("TTS_GENERATE") == p.max_concurrent_tts_stages


def test_get_stage_limit_lipsync():
    p = ConcurrencyPolicy()
    assert p.get_stage_limit("LIPSYNC_GENERATE") == p.max_concurrent_lipsync_stages


def test_get_stage_limit_unknown():
    p = ConcurrencyPolicy()
    assert p.get_stage_limit("UNKNOWN_STAGE") == 20
    assert p.get_stage_limit("") == 20
