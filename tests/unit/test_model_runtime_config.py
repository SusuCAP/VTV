"""Unit tests for orchestrator model_runtime injection into StageJob params (P8-A / P8-B)."""
from __future__ import annotations

import pytest

from vtv_orchestrator.config import ModelRuntimeSettings, Settings, model_runtime_for_stage


class TestModelRuntimeForStage:
    """Verify that model_runtime_for_stage maps stage types to the correct adapter modes."""

    def _settings(self, **overrides: str) -> Settings:
        rt = ModelRuntimeSettings(**overrides)
        return Settings(model_runtime=rt)

    # ── ASR (P8-A) ──────────────────────────────────────────────────────────

    def test_asr_default_is_deterministic(self) -> None:
        rt = model_runtime_for_stage("ASR_ALIGN")
        assert rt == {"adapter_mode": "deterministic"}

    def test_asr_local_models(self) -> None:
        s = self._settings(asr_adapter_mode="local_models")
        rt = model_runtime_for_stage("ASR_ALIGN", s)
        assert rt == {"adapter_mode": "local_models"}

    def test_asr_remote(self) -> None:
        s = self._settings(asr_adapter_mode="remote")
        assert model_runtime_for_stage("ASR_ALIGN", s) == {"adapter_mode": "remote"}

    # ── Vision (P8-B) ────────────────────────────────────────────────────────

    def test_vision_default_is_deterministic(self) -> None:
        assert model_runtime_for_stage("VISION_ANALYSIS") == {"adapter_mode": "deterministic"}

    def test_vision_qwen3_vl(self) -> None:
        s = self._settings(vision_adapter_mode="qwen3_vl")
        assert model_runtime_for_stage("VISION_ANALYSIS", s) == {"adapter_mode": "qwen3_vl"}

    # ── Visual generation ────────────────────────────────────────────────────

    def test_visual_character_replace_passthrough_default(self) -> None:
        rt = model_runtime_for_stage("VISUAL_CHARACTER_REPLACE")
        assert rt["adapter_mode"] == "passthrough"
        assert rt["segmentation_adapter_mode"] == "passthrough"

    def test_visual_character_replace_wan_animate(self) -> None:
        s = self._settings(
            visual_generation_adapter_mode="wan_animate",
            segmentation_adapter_mode="sam3",
        )
        rt = model_runtime_for_stage("VISUAL_CHARACTER_REPLACE", s)
        assert rt["adapter_mode"] == "wan_animate"
        assert rt["segmentation_adapter_mode"] == "sam3"

    def test_visual_full_regen_no_segmentation_key(self) -> None:
        rt = model_runtime_for_stage("VISUAL_FULL_REGEN")
        assert "segmentation_adapter_mode" not in rt

    def test_visual_background_replace_inherits_seg(self) -> None:
        s = self._settings(segmentation_adapter_mode="sam3")
        rt = model_runtime_for_stage("VISUAL_BACKGROUND_REPLACE", s)
        assert rt["segmentation_adapter_mode"] == "sam3"

    # ── TTS ─────────────────────────────────────────────────────────────────

    def test_tts_default_passthrough(self) -> None:
        assert model_runtime_for_stage("TTS_GENERATE") == {"adapter_mode": "passthrough"}

    def test_tts_cosyvoice3(self) -> None:
        s = self._settings(tts_adapter_mode="cosyvoice3")
        assert model_runtime_for_stage("TTS_GENERATE", s) == {"adapter_mode": "cosyvoice3"}

    # ── Lipsync ──────────────────────────────────────────────────────────────

    def test_lipsync_default_passthrough(self) -> None:
        assert model_runtime_for_stage("LIPSYNC_GENERATE") == {"adapter_mode": "passthrough"}

    def test_lipsync_latentsync(self) -> None:
        s = self._settings(lipsync_adapter_mode="latentsync")
        assert model_runtime_for_stage("LIPSYNC_GENERATE", s) == {"adapter_mode": "latentsync"}

    # ── Non-model stages return empty dict ───────────────────────────────────

    @pytest.mark.parametrize("stage_type", [
        "INGEST_VALIDATE",
        "PROXY_GENERATE",
        "SHOT_DETECTION",
        "AUDIO_MIX",
        "ASSEMBLE_EPISODE",
        "DELIVERY_EVIDENCE",
        "C2PA_SIGN",
        "SHOT_ROUTING",
    ])
    def test_non_model_stages_return_empty(self, stage_type: str) -> None:
        assert model_runtime_for_stage(stage_type) == {}


class TestModelRuntimeSettingsEnvPrefix:
    """Verify that ModelRuntimeSettings reads from VTV_* env vars."""

    def test_env_prefix_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VTV_ASR_ADAPTER_MODE", "local_models")
        monkeypatch.setenv("VTV_VISION_ADAPTER_MODE", "qwen3_vl")
        monkeypatch.setenv("VTV_TTS_ADAPTER_MODE", "cosyvoice3")
        rt = ModelRuntimeSettings()
        assert rt.asr_adapter_mode == "local_models"
        assert rt.vision_adapter_mode == "qwen3_vl"
        assert rt.tts_adapter_mode == "cosyvoice3"

    def test_defaults_unchanged_without_env(self) -> None:
        rt = ModelRuntimeSettings()
        assert rt.asr_adapter_mode == "deterministic"
        assert rt.vision_adapter_mode == "deterministic"
        assert rt.segmentation_adapter_mode == "passthrough"
        assert rt.visual_generation_adapter_mode == "passthrough"
        assert rt.tts_adapter_mode == "passthrough"
        assert rt.lipsync_adapter_mode == "passthrough"
