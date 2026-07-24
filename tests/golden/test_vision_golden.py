"""Golden regression tests for Vision Analysis stage.

Run with GPU:
    VTV_VISION_ADAPTER_MODE=qwen3_vl pytest tests/golden/test_vision_golden.py -v

Update baselines:
    VTV_VISION_ADAPTER_MODE=qwen3_vl pytest tests/golden/test_vision_golden.py --update-golden
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden.conftest import load_baseline, save_baseline


@pytest.mark.golden
class TestVisionGolden:
    """Regression tests for vision analysis output on fixed golden shots."""

    def test_vision_golden_shots_exist(self, golden_shot_paths: list[Path]) -> None:
        if not golden_shot_paths:
            pytest.skip("No golden shots in tests/golden/fixtures/shots/")
        assert len(golden_shot_paths) >= 1

    @pytest.mark.parametrize("shot_path", [], ids=[])
    def test_vision_analysis_regression(
        self,
        shot_path: Path,
        update_golden: bool,
    ) -> None:
        """Run vision analysis and compare against saved baseline."""
        from vtv_analysis.adapters import (
            QwenGeometryAdapter,
            QwenOcrAdapter,
            QwenPersonAdapter,
            QwenSceneAdapter,
        )
        from vtv_analysis.pipeline import VisionAnalysisPipeline

        pytest.importorskip("transformers", reason="transformers not installed")

        baseline_key = f"vision_{shot_path.stem}"

        pipeline = VisionAnalysisPipeline(
            people=QwenPersonAdapter(),
            scenes=QwenSceneAdapter(),
            ocr=QwenOcrAdapter(),
            geometry=QwenGeometryAdapter(),
        )
        result = pipeline.analyze(str(shot_path), duration_hint=None, shots=None)

        actual = {
            "person_count": len(result.person_observations),
            "scene_count": len(result.scene_observations),
            "ocr_count": len(result.ocr_observations),
            "has_geometry": result.geometry is not None,
        }

        if update_golden:
            save_baseline(baseline_key, actual)
            return

        baseline = load_baseline(baseline_key)
        # Person count within ±1
        assert abs(actual["person_count"] - baseline["person_count"]) <= 1, \
            f"Person count regression: {actual['person_count']} vs {baseline['person_count']}"
        assert actual["has_geometry"] == baseline["has_geometry"]
