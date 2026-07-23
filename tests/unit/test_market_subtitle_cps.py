from __future__ import annotations

from uuid import uuid4

import pytest
from vtv_assemble_worker.worker import _market_max_cps
from vtv_assembly import SubtitleCue, SubtitleDocument

# ---------------------------------------------------------------------------
# _market_max_cps unit tests
# ---------------------------------------------------------------------------


def test_en_us_returns_default_17_cps() -> None:
    assert _market_max_cps("en-US") == 17


def test_ko_kr_returns_12_cps() -> None:
    assert _market_max_cps("ko-KR") == 12


def test_ja_jp_returns_10_cps() -> None:
    assert _market_max_cps("ja-JP") == 10


def test_unknown_market_falls_back_to_17_cps() -> None:
    assert _market_max_cps("xx-XX") == 17


# ---------------------------------------------------------------------------
# CPS enforcement through AssembleWorker._subtitle
# ---------------------------------------------------------------------------


def test_cue_exceeding_market_cps_limit_is_rejected(tmp_path) -> None:
    """A cue with CPS above the ko-KR limit (12) must raise ValueError."""
    from vtv_assemble_worker import AssembleWorker
    from vtv_schemas.jobs import StageJob

    # 24 characters in 1 second = 24 CPS > 12 CPS (ko-KR limit)
    long_text = "가나다라마바사아자차카타파하가나다라마바사아자차"
    document = SubtitleDocument(
        locale="ko-KR",
        cues=(SubtitleCue(index=1, start_seconds=0.0, end_seconds=1.0, text=long_text),),
    )

    job = StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        idempotency_key="test:subtitle-cps",
        stage_type="SUBTITLE_RENDER",
        input_assets=[],
        output_prefix=(tmp_path / "subtitle_render").resolve().as_uri(),
        runtime_profile_id="cpu-assemble",
        observed_control_version=1,
        trace_id="test-cps-validation",
        params={
            "subtitle_document": document.model_dump(mode="json"),
            "formats": ["srt"],
            "market_code": "ko-KR",
        },
    )

    worker = AssembleWorker()
    with pytest.raises(ValueError, match="CPS"):
        worker.execute(job)
