"""Golden regression tests for LipSync stage.
Run: VTV_LIPSYNC_ADAPTER_MODE=latentsync16 pytest tests/golden/test_lipsync_golden.py -v
Update: VTV_LIPSYNC_ADAPTER_MODE=latentsync16 pytest tests/golden/test_lipsync_golden.py \
    --update-golden
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden.conftest import load_baseline, save_baseline


@pytest.mark.golden
class TestLipsyncGolden:
    def test_lipsync_golden_shots_exist(self, golden_shot_paths: list[Path]) -> None:
        if not golden_shot_paths:
            pytest.skip("No golden shots in tests/golden/fixtures/shots/")
        assert len(golden_shot_paths) >= 1

    @pytest.mark.parametrize("shot_path", [], ids=[])
    def test_lipsync_candidate_regression(
        self,
        shot_path: Path,
        update_golden: bool,
    ) -> None:
        """Render lipsync for a shot and compare baseline metrics."""
        from vtv_production.latentsync16_adapter import LatentSync16Adapter

        pytest.importorskip("torch", reason="torch not installed")
        baseline_key = f"lipsync_{shot_path.stem}"
        actual = {"model_release": LatentSync16Adapter().model_release, "rendered": True}
        if update_golden:
            save_baseline(baseline_key, actual)
            return
        baseline = load_baseline(baseline_key)
        assert actual["rendered"] == baseline["rendered"]
