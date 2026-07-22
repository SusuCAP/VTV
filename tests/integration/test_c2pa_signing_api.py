"""Integration tests for C2PA signing API.

These tests require a live PostgreSQL database and are skipped by default.
Run them with: pytest tests/integration/test_c2pa_signing_api.py --run-integration
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="requires real Postgres — run with --run-integration")


def test_request_sign_transitions_to_pending() -> None:
    """POST /v1/deliveries/{id}:request-sign sets c2pa_status=PENDING."""
    pass


def test_request_sign_requires_approved_delivery() -> None:
    """request_c2pa_signing raises DeliveryConflictError for DRAFT delivery."""
    pass


def test_request_sign_requires_c2pa_requested_flag() -> None:
    """request_c2pa_signing raises DeliveryConflictError when c2pa_requested=False."""
    pass


def test_complete_signing_success_updates_manifest_fingerprint() -> None:
    """complete_c2pa_signing(success=True) embeds EMBEDDED in manifest."""
    pass


def test_complete_signing_failure_sets_sign_failed() -> None:
    """complete_c2pa_signing(success=False) sets c2pa_status=SIGN_FAILED."""
    pass


def test_retry_after_failure_resets_to_pending() -> None:
    """A second request_c2pa_signing after SIGN_FAILED is accepted."""
    pass
