from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_schemas.webhook import WebhookConfig, WebhookCreate, WebhookDeliveryLog


def _now() -> datetime:
    return datetime.now(UTC)


def _valid_create(**kwargs) -> WebhookCreate:
    defaults = {
        "url": "https://example.com/hook",
        "secret": "supersecretkey1234",
        "event_types": ("delivery.approved",),
    }
    defaults.update(kwargs)
    return WebhookCreate(**defaults)


def _valid_config(**kwargs) -> WebhookConfig:
    defaults = {
        "webhook_id": uuid4(),
        "workspace_id": uuid4(),
        "url": "https://example.com/hook",
        "secret": "supersecretkey1234",
        "event_types": ("delivery.approved",),
        "created_at": _now(),
        "failure_count": 0,
    }
    defaults.update(kwargs)
    return WebhookConfig(**defaults)


# --- WebhookCreate validation ---

def test_webhook_create_url_min_length():
    # exactly 8 chars satisfies min_length=8
    wc = _valid_create(url="http://x")
    assert wc.url == "http://x"


def test_webhook_create_url_too_short():
    with pytest.raises(ValidationError):
        _valid_create(url="http:/x")  # 7 chars — too short


def test_webhook_create_secret_too_short():
    with pytest.raises(ValidationError):
        _valid_create(secret="tooshort")  # 8 chars < 16


def test_webhook_create_secret_too_long():
    with pytest.raises(ValidationError):
        _valid_create(secret="x" * 257)  # 257 chars > 256


def test_webhook_create_event_types_empty():
    with pytest.raises(ValidationError):
        _valid_create(event_types=())


# --- WebhookConfig is_healthy ---

def test_webhook_config_is_healthy_true():
    cfg = _valid_config(failure_count=4)
    assert cfg.is_healthy is True


def test_webhook_config_is_healthy_false():
    cfg = _valid_config(failure_count=5)
    assert cfg.is_healthy is False


def test_webhook_config_is_healthy_false_above_threshold():
    cfg = _valid_config(failure_count=10)
    assert cfg.is_healthy is False


# --- WebhookDeliveryLog ---

def test_webhook_delivery_log_success():
    log = WebhookDeliveryLog(
        webhook_id=uuid4(),
        event_type="delivery.approved",
        payload_sha256="abc123",
        response_status=200,
        delivered_at=_now(),
        success=True,
    )
    assert log.success is True
    assert log.error_message is None


def test_webhook_delivery_log_failure():
    log = WebhookDeliveryLog(
        webhook_id=uuid4(),
        event_type="delivery.approved",
        payload_sha256="abc123",
        response_status=500,
        delivered_at=_now(),
        success=False,
        error_message="Internal Server Error",
    )
    assert log.success is False
    assert log.error_message == "Internal Server Error"


# --- url min_length constraint ---

def test_webhook_config_url_min_length():
    with pytest.raises(ValidationError):
        _valid_config(url="short")  # 5 chars < 8
