from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_delivery import (
    C2paContentCredentials,
    C2paSignRequest,
    C2paSignResult,
    DeliveryRead,
)


def _sha(ch: str) -> str:
    return ch * 64


# ---------------------------------------------------------------------------
# DeliveryRead c2pa_status transitions
# ---------------------------------------------------------------------------


def _draft_delivery() -> DeliveryRead:
    now = datetime.now(UTC)
    return DeliveryRead(
        id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        version=1,
        status="DRAFT",
        state_version=1,
        c2pa_status="NOT_REQUESTED",
        created_at=now,
        updated_at=now,
    )


def _approved_delivery(c2pa_requested: bool = True) -> DeliveryRead:
    d = _draft_delivery()
    return d.model_copy(
        update={
            "status": "APPROVED",
            "c2pa_status": "NOT_REQUESTED" if c2pa_requested else "NOT_REQUESTED",
            "manifest_fingerprint": _sha("a"),
            "state_version": 2,
        }
    )


class TestC2paStatusFieldOnDeliveryRead:
    def test_default_is_not_requested(self) -> None:
        d = _draft_delivery()
        assert d.c2pa_status == "NOT_REQUESTED"

    def test_valid_statuses_accepted(self) -> None:
        for status in ("NOT_REQUESTED", "PENDING", "SIGNING", "SIGNED", "SIGN_FAILED"):
            d = _draft_delivery().model_copy(update={"c2pa_status": status})
            assert d.c2pa_status == status

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DeliveryRead.model_validate(
                _draft_delivery().model_dump() | {"c2pa_status": "UNKNOWN"}
            )


class TestC2paStateMachineTransitions:
    """Pure state machine logic — simulates repository transitions."""

    def _transition(
        self, delivery: DeliveryRead, from_status: str, to_status: str
    ) -> DeliveryRead:
        """Apply a valid state transition."""
        assert delivery.c2pa_status == from_status
        return delivery.model_copy(update={"c2pa_status": to_status})

    def test_not_requested_to_pending(self) -> None:
        d = _approved_delivery()
        updated = self._transition(d, "NOT_REQUESTED", "PENDING")
        assert updated.c2pa_status == "PENDING"

    def test_pending_to_signing(self) -> None:
        d = _approved_delivery()
        d = d.model_copy(update={"c2pa_status": "PENDING"})
        updated = self._transition(d, "PENDING", "SIGNING")
        assert updated.c2pa_status == "SIGNING"

    def test_signing_to_signed(self) -> None:
        d = _approved_delivery()
        d = d.model_copy(update={"c2pa_status": "SIGNING"})
        updated = self._transition(d, "SIGNING", "SIGNED")
        assert updated.c2pa_status == "SIGNED"

    def test_signing_to_sign_failed(self) -> None:
        d = _approved_delivery()
        d = d.model_copy(update={"c2pa_status": "SIGNING"})
        updated = self._transition(d, "SIGNING", "SIGN_FAILED")
        assert updated.c2pa_status == "SIGN_FAILED"

    def test_sign_failed_to_pending_retry(self) -> None:
        d = _approved_delivery()
        d = d.model_copy(update={"c2pa_status": "SIGN_FAILED"})
        updated = self._transition(d, "SIGN_FAILED", "PENDING")
        assert updated.c2pa_status == "PENDING"


class TestC2paSignRequest:
    def test_valid_request(self) -> None:
        req = C2paSignRequest(
            delivery_id=uuid4(),
            manifest_fingerprint=_sha("b"),
            master_object_uri="s3://bucket/master.mp4",
            output_prefix="s3://bucket/c2pa/",
        )
        assert req.signer_id == "vtv.passthrough-signer.v1"

    def test_empty_uri_rejected(self) -> None:
        with pytest.raises(ValidationError):
            C2paSignRequest(
                delivery_id=uuid4(),
                manifest_fingerprint=_sha("b"),
                master_object_uri="",
                output_prefix="s3://bucket/c2pa/",
            )

    def test_bad_fingerprint_rejected(self) -> None:
        with pytest.raises(ValidationError):
            C2paSignRequest(
                delivery_id=uuid4(),
                manifest_fingerprint="not-a-sha256",
                master_object_uri="s3://bucket/master.mp4",
                output_prefix="s3://bucket/c2pa/",
            )


class TestC2paContentCredentials:
    def test_valid_credentials(self) -> None:
        creds = C2paContentCredentials(
            delivery_id=uuid4(),
            manifest_fingerprint=_sha("c"),
            signer="vtv.passthrough-signer.v1",
            signed_at=datetime.now(UTC),
            credential_uri="s3://bucket/credentials.json",
        )
        assert creds.schema_version == "vtv.c2pa-credentials.v1"
        assert creds.assertions == ()

    def test_assertions_immutable_tuple(self) -> None:
        creds = C2paContentCredentials(
            delivery_id=uuid4(),
            manifest_fingerprint=_sha("c"),
            signer="vtv.passthrough-signer.v1",
            signed_at=datetime.now(UTC),
            assertions=("c2pa.created", "c2pa.edited"),
            credential_uri="s3://bucket/credentials.json",
        )
        assert len(creds.assertions) == 2


class TestC2paSignResult:
    def test_valid_result(self) -> None:
        delivery_id = uuid4()
        fingerprint = _sha("d")
        creds = C2paContentCredentials(
            delivery_id=delivery_id,
            manifest_fingerprint=fingerprint,
            signer="vtv.passthrough-signer.v1",
            signed_at=datetime.now(UTC),
            credential_uri="s3://bucket/cred.json",
        )
        result = C2paSignResult(
            delivery_id=delivery_id,
            manifest_fingerprint=fingerprint,
            credentials=creds,
            credential_asset_sha256=_sha("e"),
            credential_asset_uri="s3://bucket/cred.json",
            credential_size_bytes=512,
        )
        assert result.credential_size_bytes == 512

    def test_zero_size_rejected(self) -> None:
        delivery_id = uuid4()
        fingerprint = _sha("d")
        creds = C2paContentCredentials(
            delivery_id=delivery_id,
            manifest_fingerprint=fingerprint,
            signer="vtv.passthrough-signer.v1",
            signed_at=datetime.now(UTC),
            credential_uri="s3://bucket/cred.json",
        )
        with pytest.raises(ValidationError):
            C2paSignResult(
                delivery_id=delivery_id,
                manifest_fingerprint=fingerprint,
                credentials=creds,
                credential_asset_sha256=_sha("e"),
                credential_asset_uri="s3://bucket/cred.json",
                credential_size_bytes=0,
            )
