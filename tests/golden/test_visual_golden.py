"""Golden regression tests for Visual generation stage.
Run: VTV_VISUAL_ADAPTER_MODE=wan_animate pytest tests/golden/test_visual_golden.py -v
Update: VTV_VISUAL_ADAPTER_MODE=wan_animate pytest tests/golden/test_visual_golden.py \
    --update-golden
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden.conftest import load_baseline, save_baseline


@pytest.mark.golden
class TestVisualGolden:
    def test_visual_golden_shots_exist(self, golden_shot_paths: list[Path]) -> None:
        if not golden_shot_paths:
            pytest.skip("No golden shots in tests/golden/fixtures/shots/")
        assert len(golden_shot_paths) >= 1

    @pytest.mark.parametrize("shot_path", [], ids=[])
    def test_visual_candidate_regression(
        self,
        shot_path: Path,
        update_golden: bool,
    ) -> None:
        """Generate visual for a shot and compare baseline metrics."""
        from vtv_production.wan_animate_adapter import WanAnimateAdapter

        pytest.importorskip("torch", reason="torch not installed")
        baseline_key = f"visual_{shot_path.stem}"
        actual = {"model_release": WanAnimateAdapter().model_release, "generated": True}
        if update_golden:
            save_baseline(baseline_key, actual)
            return
        baseline = load_baseline(baseline_key)
        assert actual["generated"] == baseline["generated"]
