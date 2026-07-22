from uuid import uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app


def _create_release(client: TestClient, name: str = "audio@1") -> dict:
    response = client.post(
        "/v1/model-releases",
        json={
            "model_key": "AUDIO_ANALYSIS",
            "release_name": name,
            "provider": "internal",
            "endpoint": "https://models.example.test/audio",
            "license_id": f"license-{name}",
            "model_card_uri": f"s3://registry/{name}.json",
            "config": {"allow_fallback": False},
        },
    )
    assert response.status_code == 201
    return response.json()


def _approve(client: TestClient, release: dict) -> dict:
    response = client.post(
        f"/v1/model-releases/{release['id']}/license-review",
        json={
            "decision": "APPROVED",
            "actor_id": str(uuid4()),
            "expected_state_version": release["state_version"],
        },
    )
    assert response.status_code == 200
    return response.json()


def test_model_release_api_gates_license_and_traffic() -> None:
    with TestClient(create_app()) as client:
        release = _create_release(client)
        denied = client.post(
            f"/v1/model-releases/{release['id']}/automation",
            json={"target": "CANARY", "traffic_percent": 10, "expected_state_version": 1},
        )
        assert denied.status_code == 409

        approved = _approve(client, release)
        active = client.post(
            f"/v1/model-releases/{release['id']}/automation",
            json={
                "target": "ACTIVE",
                "traffic_percent": 100,
                "expected_state_version": approved["state_version"],
            },
        )
        assert active.status_code == 200
        assert active.json()["traffic_percent"] == 100


def test_registry_canary_promotes_and_disables_previous_active() -> None:
    with TestClient(create_app()) as client:
        first = _approve(client, _create_release(client, "audio@1"))
        second = _approve(client, _create_release(client, "audio@2"))
        enabled = client.post(
            f"/v1/model-releases/{first['id']}/automation",
            json={"target": "ACTIVE", "traffic_percent": 100, "expected_state_version": 2},
        )
        assert enabled.status_code == 200
        canary = client.post(
            f"/v1/model-releases/{second['id']}/automation",
            json={"target": "CANARY", "traffic_percent": 5, "expected_state_version": 2},
        )
        assert canary.status_code == 200
        promoted = client.post(
            f"/v1/model-releases/{second['id']}/automation",
            json={
                "target": "ACTIVE",
                "traffic_percent": 100,
                "expected_state_version": canary.json()["state_version"],
            },
        )
        assert promoted.status_code == 200
        listed = client.get("/v1/model-releases?model_key=AUDIO_ANALYSIS").json()
        statuses = {item["id"]: item["automation_status"] for item in listed}
        assert statuses[first["id"]] == "DISABLED"
        assert statuses[second["id"]] == "ACTIVE"

        hidden = client.get(
            "/v1/model-releases",
            headers={"X-Workspace-Id": "00000000-0000-0000-0000-000000000099"},
        )
        assert hidden.json() == []
