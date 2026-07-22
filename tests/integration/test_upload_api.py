from fastapi.testclient import TestClient
from vtv_control_api.app import create_app
from vtv_control_api.repository import MemoryRepository


class FailingCommitRepository(MemoryRepository):
    def __init__(self) -> None:
        super().__init__()
        self.orphan_uri: str | None = None

    async def complete_upload(self, *args: object, **kwargs: object):
        raise RuntimeError("database unavailable after object completion")

    async def register_orphan_asset(
        self,
        workspace_id,
        project_id,
        object_uri: str,
        reason: str,
    ) -> None:
        self.orphan_uri = object_uri


def test_multipart_upload_contract_does_not_proxy_media() -> None:
    with TestClient(create_app()) as client:
        project = client.post(
            "/v1/projects",
            json={"name": "Upload", "target_market": "US", "locale": "en-US"},
        ).json()
        size = 96 * 1024 * 1024
        initialized = client.post(
            "/v1/uploads/multipart-init",
            json={
                "project_id": project["id"],
                "filename": "episode-01.mp4",
                "content_type": "video/mp4",
                "size_bytes": size,
                "part_size_bytes": 64 * 1024 * 1024,
                "sha256": "a" * 64,
            },
        )
        assert initialized.status_code == 201
        upload = initialized.json()
        assert len(upload["parts"]) == 2
        assert all("object-store.invalid" in part["url"] for part in upload["parts"])

        completed = client.post(
            f"/v1/uploads/{upload['upload_id']}/multipart-complete",
            json={
                "parts": [
                    {"part_number": 1, "size_bytes": 64 * 1024 * 1024, "etag": "p1"},
                    {"part_number": 2, "size_bytes": 32 * 1024 * 1024, "etag": "p2"},
                ],
                "object_checksum_sha256": "a" * 64,
            },
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "COMPLETED"
        assert completed.json()["episode_id"]
        assert completed.json()["media_asset_id"]
        assert completed.json()["ingest_job_id"]

        episodes = client.get(f"/v1/projects/{project['id']}/episodes")
        assert episodes.status_code == 200
        assert episodes.json()[0]["title"] == "episode-01.mp4"
        assert episodes.json()[0]["processing_status"] == "QUEUED"


def test_multipart_complete_rejects_size_mismatch() -> None:
    with TestClient(create_app()) as client:
        project = client.post(
            "/v1/projects",
            json={"name": "Upload", "target_market": "US", "locale": "en-US"},
        ).json()
        upload = client.post(
            "/v1/uploads/multipart-init",
            json={
                "project_id": project["id"],
                "filename": "episode.mp4",
                "content_type": "video/mp4",
                "size_bytes": 64 * 1024 * 1024,
                "sha256": "b" * 64,
            },
        ).json()

        rejected = client.post(
            f"/v1/uploads/{upload['upload_id']}/multipart-complete",
            json={
                "parts": [{"part_number": 1, "size_bytes": 1, "etag": "bad"}],
                "object_checksum_sha256": "b" * 64,
            },
        )
        assert rejected.status_code == 409


def test_completed_object_is_registered_as_orphan_when_database_commit_fails() -> None:
    repository = FailingCommitRepository()
    with TestClient(create_app(repository=repository), raise_server_exceptions=False) as client:
        project = client.post(
            "/v1/projects",
            json={"name": "Upload", "target_market": "US", "locale": "en-US"},
        ).json()
        sha256 = "c" * 64
        upload = client.post(
            "/v1/uploads/multipart-init",
            json={
                "project_id": project["id"],
                "filename": "episode.mp4",
                "content_type": "video/mp4",
                "size_bytes": 32 * 1024 * 1024,
                "sha256": sha256,
            },
        ).json()
        response = client.post(
            f"/v1/uploads/{upload['upload_id']}/multipart-complete",
            json={
                "parts": [
                    {
                        "part_number": 1,
                        "size_bytes": 32 * 1024 * 1024,
                        "etag": "etag",
                    }
                ],
                "object_checksum_sha256": sha256,
            },
        )
        assert response.status_code == 500
        assert repository.orphan_uri and repository.orphan_uri.startswith("memory://")
