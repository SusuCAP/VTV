from datetime import UTC, datetime, timedelta
from uuid import uuid4

from vtv_db.rights import evaluate_rights_release
from vtv_schemas.rights import RightsExecutionCheck, RightsReleaseRead


def _release(**updates: object) -> RightsReleaseRead:
    now = datetime(2026, 7, 22, tzinfo=UTC)
    values = {
        "id": uuid4(),
        "project_id": uuid4(),
        "subject_type": "VOICE",
        "subject_id": "character-1",
        "version": 1,
        "status": "ACTIVE",
        "state_version": 1,
        "allowed_operations": frozenset({"voice_clone", "lipsync"}),
        "allowed_markets": frozenset({"US"}),
        "allowed_languages": frozenset({"en-US"}),
        "commercial_scope": "COMMERCIAL",
        "valid_from": now - timedelta(days=1),
        "expires_at": now + timedelta(days=1),
        "minor_guardian_consent": False,
        "source_asset_ids": (),
        "evidence_uri": "s3://private-rights/evidence.pdf",
        "evidence_sha256": "a" * 64,
        "created_by": uuid4(),
        "created_at": now,
        "updated_at": now,
    }
    values.update(updates)
    return RightsReleaseRead(**values)


def test_rights_gate_allows_exact_active_scope() -> None:
    now = datetime(2026, 7, 22, tzinfo=UTC)
    decision = evaluate_rights_release(
        _release(),
        RightsExecutionCheck(
            operation="voice_clone",
            market="US",
            language="en-US",
            commercial_use=True,
        ),
        now=now,
    )

    assert decision.allowed is True
    assert decision.reason_codes == ()


def test_rights_gate_returns_all_failed_scope_reasons() -> None:
    now = datetime(2026, 7, 22, tzinfo=UTC)
    decision = evaluate_rights_release(
        _release(
            status="REVOKED",
            revoked_at=now - timedelta(hours=1),
            commercial_scope="RESEARCH_ONLY",
            expires_at=now,
        ),
        RightsExecutionCheck(
            operation="character_replace",
            market="GB",
            language="en-GB",
            commercial_use=True,
        ),
        now=now,
    )

    assert decision.allowed is False
    assert set(decision.reason_codes) == {
        "RIGHTS_REVOKED",
        "RIGHTS_EXPIRED",
        "OPERATION_NOT_ALLOWED",
        "MARKET_NOT_ALLOWED",
        "LANGUAGE_NOT_ALLOWED",
        "COMMERCIAL_USE_NOT_ALLOWED",
    }
