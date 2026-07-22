from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app


def _payload(*, supersedes: str | None = None) -> dict:
    now = datetime.now(UTC)
    return {
        "subject_type": "VOICE",
        "subject_id": "character-1",
        "allowed_operations": ["voice_clone", "lipsync"],
        "allowed_markets": ["US"],
        "allowed_languages": ["en-US"],
        "commercial_scope": "COMMERCIAL",
        "valid_from": (now - timedelta(days=1)).isoformat(),
        "expires_at": (now + timedelta(days=30)).isoformat(),
        "evidence_uri": "s3://private-rights/voice-contract.pdf",
        "evidence_sha256": "b" * 64,
        "created_by": str(uuid4()),
        "supersedes_release_id": supersedes,
    }


def test_rights_api_create_check_revoke_and_workspace_isolation() -> None:
    workspace = "00000000-0000-0000-0000-000000000021"
    other_workspace = "00000000-0000-0000-0000-000000000022"
    headers = {"X-Workspace-Id": workspace}
    with TestClient(create_app()) as client:
        project = client.post(
            "/v1/projects",
            headers=headers,
            json={"name": "Rights", "target_market": "US", "locale": "en-US"},
        ).json()
        created = client.post(
            f"/v1/projects/{project['id']}/rights-releases",
            headers=headers,
            json=_payload(),
        )
        assert created.status_code == 201
        release = created.json()
        assert release["version"] == 1
        assert release["status"] == "ACTIVE"

        allowed = client.post(
            f"/v1/rights-releases/{release['id']}/check",
            headers=headers,
            json={
                "operation": "voice_clone",
                "market": "US",
                "language": "en-US",
                "commercial_use": True,
            },
        )
        assert allowed.status_code == 200
        assert allowed.json()["allowed"] is True

        hidden = client.post(
            f"/v1/rights-releases/{release['id']}/check",
            headers={"X-Workspace-Id": other_workspace},
            json={"operation": "voice_clone", "market": "US", "language": "en-US"},
        )
        assert hidden.status_code == 404

        revoked = client.post(
            f"/v1/rights-releases/{release['id']}/revoke",
            headers=headers,
            json={
                "expected_state_version": 1,
                "actor_id": str(uuid4()),
                "reason": "actor withdrew consent",
            },
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "REVOKED"
        assert revoked.json()["state_version"] == 2

        denied = client.post(
            f"/v1/rights-releases/{release['id']}/check",
            headers=headers,
            json={"operation": "voice_clone", "market": "US", "language": "en-US"},
        )
        assert denied.json()["allowed"] is False
        assert "RIGHTS_REVOKED" in denied.json()["reason_codes"]


def test_new_rights_version_requires_explicit_current_supersession() -> None:
    with TestClient(create_app()) as client:
        project = client.post(
            "/v1/projects",
            json={"name": "Rights versions", "target_market": "US", "locale": "en-US"},
        ).json()
        first = client.post(
            f"/v1/projects/{project['id']}/rights-releases", json=_payload()
        ).json()

        conflict = client.post(
            f"/v1/projects/{project['id']}/rights-releases", json=_payload()
        )
        assert conflict.status_code == 409

        replacement = client.post(
            f"/v1/projects/{project['id']}/rights-releases",
            json=_payload(supersedes=first["id"]),
        )
        assert replacement.status_code == 201
        assert replacement.json()["version"] == 2
        listed = client.get(f"/v1/projects/{project['id']}/rights-releases").json()
        statuses = {item["id"]: item["status"] for item in listed}
        assert statuses[first["id"]] == "REVOKED"
        assert statuses[replacement.json()["id"]] == "ACTIVE"
