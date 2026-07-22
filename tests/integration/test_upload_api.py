from fastapi.testclient import TestClient
from vtv_control_api.app import create_app


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
                ]
            },
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "COMPLETED"


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
            },
        ).json()

        rejected = client.post(
            f"/v1/uploads/{upload['upload_id']}/multipart-complete",
            json={"parts": [{"part_number": 1, "size_bytes": 1, "etag": "bad"}]},
        )
        assert rejected.status_code == 409
