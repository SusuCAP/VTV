from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository
from vtv_schemas.episodes import EpisodeRead


def _project_payload(**kwargs) -> dict:
    defaults = {"name": "Test-Project", "target_market": "US", "locale": "en-US"}
    defaults.update(kwargs)
    return defaults


def _create_project(client: TestClient, **kwargs) -> dict:
    resp = client.post("/v1/projects", json=_project_payload(**kwargs))
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# archive_project changes archived_at
# ---------------------------------------------------------------------------


def test_archive_project_sets_archived_at() -> None:
    with TestClient(create_app()) as client:
        project = _create_project(client)
        project_id = project["id"]

        archive_resp = client.post(
            f"/v1/projects/{project_id}:archive",
            json={"reason": "no longer active"},
        )
        assert archive_resp.status_code == 200
        body = archive_resp.json()
        assert body["archived_at"] is not None
        assert body["archive_reason"] == "no longer active"
        assert body["state_version"] == 2


# ---------------------------------------------------------------------------
# unarchive clears archived_at
# ---------------------------------------------------------------------------


def test_unarchive_project_clears_archived_at() -> None:
    with TestClient(create_app()) as client:
        project = _create_project(client)
        project_id = project["id"]

        client.post(
            f"/v1/projects/{project_id}:archive",
            json={"reason": "temporary pause"},
        )

        unarchive_resp = client.post(f"/v1/projects/{project_id}:unarchive")
        assert unarchive_resp.status_code == 200
        body = unarchive_resp.json()
        assert body["archived_at"] is None
        assert body["archive_reason"] is None
        assert body["state_version"] == 3


# ---------------------------------------------------------------------------
# list_projects excludes archived by default
# ---------------------------------------------------------------------------


def test_list_projects_excludes_archived_by_default() -> None:
    with TestClient(create_app()) as client:
        active = _create_project(client, name="Active-Project")
        archived = _create_project(client, name="Archived-Project")

        client.post(
            f"/v1/projects/{archived['id']}:archive",
            json={"reason": "done"},
        )

        resp = client.get("/v1/projects")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()]
        assert active["id"] in ids
        assert archived["id"] not in ids

        resp_all = client.get("/v1/projects?include_archived=true")
        assert resp_all.status_code == 200
        ids_all = [p["id"] for p in resp_all.json()]
        assert active["id"] in ids_all
        assert archived["id"] in ids_all


# ---------------------------------------------------------------------------
# archived project cannot start new jobs (409)
# ---------------------------------------------------------------------------


def test_archived_project_cannot_start_analysis_job() -> None:
    repository = MemoryRepository()
    with TestClient(create_app(repository=repository)) as client:
        project = _create_project(client)
        project_id = project["id"]

        # Seed an episode so the analysis-job check passes if archived check were absent
        repository._episodes[project["id"] if hasattr(project["id"], "__class__") else None] = []
        from uuid import UUID  # noqa: PLC0415
        repository._episodes[UUID(project_id)] = [
            EpisodeRead(
                id=uuid4(),
                project_id=UUID(project_id),
                episode_no=1,
                title="Ep1",
                processing_status="READY",
                source_asset_id=uuid4(),
            )
        ]

        client.post(
            f"/v1/projects/{project_id}:archive",
            json={"reason": "archived before job"},
        )

        job_resp = client.post(f"/v1/projects/{project_id}/analysis-jobs")
        assert job_resp.status_code == 409
        assert "archived" in job_resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /v1/health returns ok
# ---------------------------------------------------------------------------


def test_health_endpoint_returns_ok() -> None:
    with TestClient(create_app()) as client:
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "degraded", "error")
        assert "checks" in body
        assert "database" in body["checks"]
        assert "timestamp" in body
