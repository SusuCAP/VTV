from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository
from vtv_schemas.episodes import EpisodeRead


def test_project_and_async_analysis_job_flow() -> None:
    repository = MemoryRepository()
    with TestClient(create_app(repository=repository)) as client:
        created = client.post(
            "/v1/projects",
            json={"name": "Drama-US-001", "target_market": "US", "locale": "en-US"},
        )
        assert created.status_code == 201
        project = created.json()
        assert project["status"] == "DRAFT"
        project_uuid = UUID(project["id"])
        repository._episodes[project_uuid] = [
            EpisodeRead(
                id=uuid4(),
                project_id=project_uuid,
                episode_no=1,
                title="Episode 1",
                processing_status="READY",
                source_asset_id=uuid4(),
            )
        ]

        accepted = client.post(f"/v1/projects/{project['id']}/analysis-jobs")
        assert accepted.status_code == 202
        assert accepted.headers["location"] == accepted.json()["status_url"]

        job = client.get(accepted.json()["status_url"])
        assert job.status_code == 200
        assert job.json()["status"] == "QUEUED"

        refreshed = client.get(f"/v1/projects/{project['id']}")
        assert refreshed.json()["status"] == "ANALYZING"
        assert refreshed.json()["state_version"] == 2

        projects = client.get("/v1/projects")
        assert projects.status_code == 200
        assert [item["id"] for item in projects.json()] == [project["id"]]

        jobs = client.get(f"/v1/projects/{project['id']}/jobs")
        assert jobs.status_code == 200
        assert jobs.json()[0]["id"] == accepted.json()["job_id"]

        documents = client.get(f"/v1/projects/{project['id']}/analysis-documents")
        assert documents.status_code == 200
        assert documents.json() == []


def test_analysis_rejects_project_without_uploaded_episodes() -> None:
    with TestClient(create_app()) as client:
        created = client.post(
            "/v1/projects",
            json={"name": "Empty", "target_market": "US", "locale": "en-US"},
        )
        response = client.post(f"/v1/projects/{created.json()['id']}/analysis-jobs")
        assert response.status_code == 409


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
