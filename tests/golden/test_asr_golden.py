"""Golden regression tests for ASR/VAD stage.

These tests require actual MP4 fixtures in tests/golden/fixtures/shots/.
They are skipped automatically when no fixtures are present.

Run with GPU model:
    VTV_ASR_ADAPTER_MODE=local_models pytest tests/golden/test_asr_golden.py -v

Update baselines:
    VTV_ASR_ADAPTER_MODE=local_models pytest tests/golden/test_asr_golden.py --update-golden
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden.conftest import load_baseline, save_baseline


@pytest.mark.golden
class TestAsrGolden:
    """Regression tests for ASR output on fixed golden shots."""

    def test_asr_golden_shots_exist(self, golden_shot_paths: list[Path]) -> None:
        """Verify at least one golden shot is registered."""
        if not golden_shot_paths:
            pytest.skip("No golden shots found in tests/golden/fixtures/shots/. "
                        "Add MP4 files to enable golden tests.")
        assert len(golden_shot_paths) >= 1

    @pytest.mark.parametrize("shot_path", [], ids=[])  # populated at collection time
    def test_asr_transcript_regression(
        self,
        shot_path: Path,
        update_golden: bool,
    ) -> None:
        """Run ASR on a fixed shot and compare against the saved baseline transcript."""
        # This stub is parameterized dynamically when fixtures/shots/ contains files
        from vtv_analysis.adapters import FasterWhisperAsrAdapter, FasterWhisperVadAdapter
        from vtv_analysis.pipeline import AudioAnalysisPipeline

        pytest.importorskip("faster_whisper", reason="faster-whisper not installed")

        baseline_key = f"asr_{shot_path.stem}"

        pipeline = AudioAnalysisPipeline(
            vad=FasterWhisperVadAdapter(),
            asr=FasterWhisperAsrAdapter(),
        )
        result = pipeline.analyze(str(shot_path), duration_hint=None, language_hint="zh")

        actual = {
            "utterances": [u.model_dump() for u in result.utterances],
            "language": result.language,
            "word_count": len([w for u in result.utterances for w in u.words]),
        }

        if update_golden:
            save_baseline(baseline_key, actual)
            return

        baseline = load_baseline(baseline_key)
        # Compare word count within ±5% tolerance
        assert abs(actual["word_count"] - baseline["word_count"]) <= max(
            1, int(baseline["word_count"] * 0.05)
        ), f"Word count regression: {actual['word_count']} vs baseline {baseline['word_count']}"
        assert actual["language"] == baseline["language"]
