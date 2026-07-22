from datetime import UTC, datetime

from vtv_schemas.rights import (
    RightsExecutionCheck,
    RightsExecutionDecision,
    RightsReleaseRead,
)


def evaluate_rights_release(
    release: RightsReleaseRead,
    request: RightsExecutionCheck,
    *,
    now: datetime | None = None,
) -> RightsExecutionDecision:
    evaluated_at = request.at or now or datetime.now(UTC)
    reasons: list[str] = []
    if release.status != "ACTIVE" or release.revoked_at is not None:
        reasons.append("RIGHTS_REVOKED")
    if evaluated_at < release.valid_from:
        reasons.append("RIGHTS_NOT_YET_VALID")
    if release.expires_at is not None and evaluated_at >= release.expires_at:
        reasons.append("RIGHTS_EXPIRED")
    if request.operation not in release.allowed_operations:
        reasons.append("OPERATION_NOT_ALLOWED")
    if request.market not in release.allowed_markets:
        reasons.append("MARKET_NOT_ALLOWED")
    if request.language not in release.allowed_languages:
        reasons.append("LANGUAGE_NOT_ALLOWED")
    if request.commercial_use and release.commercial_scope != "COMMERCIAL":
        reasons.append("COMMERCIAL_USE_NOT_ALLOWED")
    return RightsExecutionDecision(
        allowed=not reasons,
        reason_codes=tuple(reasons),
        rights_release_id=release.id,
        state_version=release.state_version,
        evaluated_at=evaluated_at,
    )
