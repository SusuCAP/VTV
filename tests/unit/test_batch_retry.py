from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_db.repository import BatchRetryRequest, BatchRetryResult


def test_batch_retry_request_defaults() -> None:
    req = BatchRetryRequest()
    assert req.stage_types == []
    assert req.reason == "batch-retry"


def test_batch_retry_request_stage_types_filter() -> None:
    req = BatchRetryRequest(stage_types=["TTS_GENERATE", "LIPSYNC_GENERATE"])
    assert req.stage_types == ["TTS_GENERATE", "LIPSYNC_GENERATE"]
    assert req.reason == "batch-retry"


def test_batch_retry_result_fields() -> None:
    job_id = uuid4()
    ids = [uuid4(), uuid4()]
    result = BatchRetryResult(job_id=job_id, retried_count=2, stage_run_ids=ids)
    assert result.job_id == job_id
    assert result.retried_count == 2
    assert result.stage_run_ids == ids


def test_batch_retry_request_reason_length_validation() -> None:
    with pytest.raises(ValidationError):
        BatchRetryRequest(reason="")
    with pytest.raises(ValidationError):
        BatchRetryRequest(reason="x" * 201)
    req = BatchRetryRequest(reason="x" * 200)
    assert len(req.reason) == 200


def test_batch_retry_result_retried_count_non_negative() -> None:
    result = BatchRetryResult(job_id=uuid4(), retried_count=0, stage_run_ids=[])
    assert result.retried_count >= 0
    result2 = BatchRetryResult(job_id=uuid4(), retried_count=10, stage_run_ids=[uuid4()] * 10)
    assert result2.retried_count >= 0


def test_batch_retry_result_stage_run_ids_is_list() -> None:
    ids = [uuid4(), uuid4(), uuid4()]
    result = BatchRetryResult(job_id=uuid4(), retried_count=3, stage_run_ids=ids)
    assert isinstance(result.stage_run_ids, list)
    assert len(result.stage_run_ids) == 3
