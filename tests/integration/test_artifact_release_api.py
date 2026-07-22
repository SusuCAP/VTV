from uuid import uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app


def _create_project(client: TestClient) -> str:
    response = client.post(
        "/v1/projects",
        json={"name": "Release API", "target_market": "US", "locale": "en-US"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_release(
    client: TestClient, project_id: str, artifact_type: str, dependencies: list[str] | None = None
) -> dict:
    response = client.post(
        f"/v1/projects/{project_id}/artifact-releases",
        json={
            "artifact_type": artifact_type,
            "content_asset_id": str(uuid4()),
            "dependency_release_ids": dependencies or [],
        },
    )
    assert response.status_code == 201
    return response.json()


def _confirm_and_publish(client: TestClient, release: dict) -> dict:
    confirmed = client.post(
        f"/v1/artifact-releases/{release['id']}/confirm",
        json={"actor_id": str(uuid4()), "expected_state_version": release["state_version"]},
    )
    assert confirmed.status_code == 200
    published = client.post(
        f"/v1/artifact-releases/{release['id']}/publish",
        json={"expected_state_version": confirmed.json()["state_version"]},
    )
    assert published.status_code == 200
    return published.json()


def test_release_api_enforces_dependencies_and_propagates_stale() -> None:
    with TestClient(create_app()) as client:
        project_id = _create_project(client)
        bible = _confirm_and_publish(client, _create_release(client, project_id, "BIBLE"))
        anchors = _create_release(client, project_id, "ANCHOR_PACK", [bible["id"]])

        premature = client.post(
            f"/v1/artifact-releases/{anchors['id']}/publish",
            json={"expected_state_version": 1},
        )
        assert premature.status_code == 409
        anchors = _confirm_and_publish(client, anchors)

        invalidated = client.post(
            f"/v1/artifact-releases/{bible['id']}/invalidate",
            json={"expected_state_version": bible["state_version"]},
        )
        assert invalidated.status_code == 200
        assert {item["id"] for item in invalidated.json()} == {bible["id"], anchors["id"]}
        assert all(item["status"] == "STALE" for item in invalidated.json())

        releases = client.get(f"/v1/projects/{project_id}/artifact-releases")
        assert releases.status_code == 200
        assert len(releases.json()) == 2


def test_release_api_rejects_stale_state_version() -> None:
    with TestClient(create_app()) as client:
        project_id = _create_project(client)
        release = _create_release(client, project_id, "BIBLE")
        response = client.post(
            f"/v1/artifact-releases/{release['id']}/confirm",
            json={"actor_id": str(uuid4()), "expected_state_version": 99},
        )
        assert response.status_code == 409


def test_superseding_release_automatically_invalidates_downstream() -> None:
    with TestClient(create_app()) as client:
        project_id = _create_project(client)
        bible = _confirm_and_publish(client, _create_release(client, project_id, "BIBLE"))
        anchors = _confirm_and_publish(
            client, _create_release(client, project_id, "ANCHOR_PACK", [bible["id"]])
        )

        replacement = client.post(
            f"/v1/projects/{project_id}/artifact-releases",
            json={
                "artifact_type": "BIBLE",
                "content_asset_id": str(uuid4()),
                "supersedes_release_id": bible["id"],
            },
        )

        assert replacement.status_code == 201
        assert replacement.json()["version"] == 2
        listed = client.get(f"/v1/projects/{project_id}/artifact-releases").json()
        statuses = {item["id"]: item["status"] for item in listed}
        assert statuses[bible["id"]] == "STALE"
        assert statuses[anchors["id"]] == "STALE"
