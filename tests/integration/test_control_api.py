from fastapi.testclient import TestClient
from vtv_control_api.app import create_app


def test_project_and_async_analysis_job_flow() -> None:
    with TestClient(create_app()) as client:
        created = client.post(
            "/v1/projects",
            json={"name": "Drama-US-001", "target_market": "US", "locale": "en-US"},
        )
        assert created.status_code == 201
        project = created.json()
        assert project["status"] == "DRAFT"

        accepted = client.post(f"/v1/projects/{project['id']}/analysis-jobs")
        assert accepted.status_code == 202
        assert accepted.headers["location"] == accepted.json()["status_url"]

        job = client.get(accepted.json()["status_url"])
        assert job.status_code == 200
        assert job.json()["status"] == "QUEUED"

        refreshed = client.get(f"/v1/projects/{project['id']}")
        assert refreshed.json()["status"] == "ANALYZING"
        assert refreshed.json()["state_version"] == 2


def test_workspace_header_enforces_isolation() -> None:
    with TestClient(create_app()) as client:
        created = client.post(
            "/v1/projects",
            headers={"X-Workspace-Id": "00000000-0000-0000-0000-000000000010"},
            json={"name": "Isolated", "target_market": "US", "locale": "en-US"},
        )
        project_id = created.json()["id"]

        hidden = client.get(
            f"/v1/projects/{project_id}",
            headers={"X-Workspace-Id": "00000000-0000-0000-0000-000000000011"},
        )
        assert hidden.status_code == 404
