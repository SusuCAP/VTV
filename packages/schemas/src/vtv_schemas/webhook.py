from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WebhookConfig(BaseModel):
    webhook_id: UUID
    workspace_id: UUID
    url: str = Field(min_length=8)  # HTTPS or localhost only
    secret: str = Field(min_length=16, max_length=256)  # HMAC-SHA256 signing secret
    event_types: tuple[str, ...] = Field(min_length=1)
    # e.g. ("delivery.approved", "stage_run.completed", "visual_production.circuit_breaker_tripped")
    active: bool = True
    created_at: datetime
    last_delivery_at: datetime | None = None
    failure_count: int = Field(default=0, ge=0)

    @property
    def is_healthy(self) -> bool:
        return self.failure_count < 5


class WebhookCreate(BaseModel):
    url: str = Field(min_length=8)
    secret: str = Field(min_length=16, max_length=256)
    event_types: tuple[str, ...] = Field(min_length=1)


class WebhookDeliveryLog(BaseModel):
    webhook_id: UUID
    event_type: str
    payload_sha256: str
    response_status: int | None = None
    delivered_at: datetime
    success: bool
    error_message: str | None = None
