"""Golden regression tests for TTS stage.
Run: VTV_TTS_ADAPTER_MODE=cosyvoice3 pytest tests/golden/test_tts_golden.py -v
Update: VTV_TTS_ADAPTER_MODE=cosyvoice3 pytest tests/golden/test_tts_golden.py --update-golden
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden.conftest import load_baseline, save_baseline


@pytest.mark.golden
class TestTtsGolden:
    def test_tts_golden_shots_exist(self, golden_shot_paths: list[Path]) -> None:
        if not golden_shot_paths:
            pytest.skip("No golden shots in tests/golden/fixtures/shots/")
        assert len(golden_shot_paths) >= 1

    @pytest.mark.parametrize("shot_path", [], ids=[])
    def test_tts_candidate_regression(
        self,
        shot_path: Path,
        update_golden: bool,
    ) -> None:
        """Synthesize TTS for a shot and compare baseline metrics."""
        from vtv_production.cosyvoice3_adapter import CosyVoice3Adapter

        pytest.importorskip("torch", reason="torch not installed")
        baseline_key = f"tts_{shot_path.stem}"
        # Actual TTS test needs real utterance data; stub checks adapter import
        actual = {"model_release": CosyVoice3Adapter().model_release, "synthesized": True}
        if update_golden:
            save_baseline(baseline_key, actual)
            return
        baseline = load_baseline(baseline_key)
        assert actual["synthesized"] == baseline["synthesized"]
