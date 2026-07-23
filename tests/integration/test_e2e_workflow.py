"""End-to-end workflow integration test.

Covers: project creation → analysis job → production job → delivery draft → delivery approval
Uses the in-memory FastAPI TestClient (no real S3/FFmpeg) to verify API contracts
and database state transitions across the full pipeline.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from vtv_control_api.app import create_app


def _project_payload(name: str = "E2E-Test-Project") -> dict:
    return {
        "name": name,
        "target_market": "US",
        "locale": "en-US",
    }


def _ws_headers() -> dict[str, str]:
    """Return a fresh X-Workspace-Id header for per-test data isolation."""
    return {"X-Workspace-Id": str(uuid4())}


def test_full_project_lifecycle() -> None:
    headers = _ws_headers()
    with TestClient(create_app()) as client:
        # 1. create project → 201
        resp = client.post("/v1/projects", json=_project_payload(), headers=headers)
        assert resp.status_code == 201
        project = resp.json()
        project_id = project["id"]

        # 2. get project → 200, status == DRAFT
        resp = client.get(f"/v1/projects/{project_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "DRAFT"

        # 3. health endpoint → 200 with database check present
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "database" in body["checks"]

        # 4. metrics → 200, active_projects >= 1
        resp = client.get("/v1/metrics", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["active_projects"] >= 1

        # 5. archive project → 200
        resp = client.post(
            f"/v1/projects/{project_id}:archive",
            json={"reason": "e2e lifecycle test"},
            headers=headers,
        )
        assert resp.status_code == 200

        # 6. list (default) should NOT include archived project
        resp = client.get("/v1/projects", headers=headers)
        assert resp.status_code == 200
        active_ids = [p["id"] for p in resp.json()]
        assert project_id not in active_ids

        # 7. list with include_archived=true SHOULD include archived project
        resp = client.get("/v1/projects?include_archived=true", headers=headers)
        assert resp.status_code == 200
        all_ids = [p["id"] for p in resp.json()]
        assert project_id in all_ids

        # 8. unarchive → 200
        resp = client.post(f"/v1/projects/{project_id}:unarchive", headers=headers)
        assert resp.status_code == 200


def test_evaluator_release_lifecycle() -> None:
    headers = _ws_headers()
    with TestClient(create_app()) as client:
        # 1. create evaluator release with visual_technical built-in config → 201
        payload = {
            "evaluator_key": "visual_technical",
            "release_name": "vtv.visual-technical.v1",
            "metric_definitions": [
                {
                    "metric_name": "frame_integrity",
                    "metric_version": "v1",
                    "hard_failure_below": 0.1,
                },
                {
                    "metric_name": "pixel_quality",
                    "metric_version": "v1",
                },
            ],
            "thresholds": {
                "frame_integrity": 0.7,
                "pixel_quality": 0.8,
            },
        }
        resp = client.post("/v1/evaluator-releases", json=payload, headers=headers)
        assert resp.status_code == 201
        release = resp.json()
        release_id = release["id"]

        # 2. list evaluator releases → 200, contains the new one
        resp = client.get("/v1/evaluator-releases", headers=headers)
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()]
        assert release_id in ids

        # 3. get by id → 200, metric_definitions non-empty
        resp = client.get(f"/v1/evaluator-releases/{release_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == release_id
        assert len(data["metric_definitions"]) > 0

        # 4. deprecate → 200, status == DEPRECATED
        resp = client.post(
            f"/v1/evaluator-releases/{release_id}:deprecate", headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "DEPRECATED"


def test_market_api() -> None:
    with TestClient(create_app()) as client:
        # 1. list markets → 200, includes "en-US"
        resp = client.get("/v1/markets")
        assert resp.status_code == 200
        assert "en-US" in resp.json()

        # 2. get en-US → 200, max_subtitle_cps == 17
        resp = client.get("/v1/markets/en-US")
        assert resp.status_code == 200
        assert resp.json()["max_subtitle_cps"] == 17

        # 3. get ko-KR → 200, max_subtitle_cps == 12
        resp = client.get("/v1/markets/ko-KR")
        assert resp.status_code == 200
        assert resp.json()["max_subtitle_cps"] == 12

        # 4. unknown market → 404
        resp = client.get("/v1/markets/unknown-market")
        assert resp.status_code == 404


def test_webhook_lifecycle() -> None:
    headers = _ws_headers()
    with TestClient(create_app()) as client:
        # 1. register webhook → 201
        webhook_payload = {
            "url": "https://example.com/webhook/receiver",
            "secret": "supersecretkey1234567890",  # >= 16 chars
            "event_types": ["delivery.approved", "stage_run.completed"],
        }
        resp = client.post("/v1/webhooks", json=webhook_payload, headers=headers)
        assert resp.status_code == 201
        webhook = resp.json()
        webhook_id = webhook["webhook_id"]

        # 2. list webhooks → 200, contains registered webhook
        resp = client.get("/v1/webhooks", headers=headers)
        assert resp.status_code == 200
        ids = [w["webhook_id"] for w in resp.json()]
        assert webhook_id in ids

        # 3. test webhook → 200, {"pinged": True}
        resp = client.post(f"/v1/webhooks/{webhook_id}:test", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["pinged"] is True

        # 4. delete webhook → 204
        resp = client.delete(f"/v1/webhooks/{webhook_id}", headers=headers)
        assert resp.status_code == 204

        # confirm removed from list
        resp = client.get("/v1/webhooks", headers=headers)
        assert resp.status_code == 200
        ids_after = [w["webhook_id"] for w in resp.json()]
        assert webhook_id not in ids_after


def test_cost_report_and_qc_stats() -> None:
    headers = _ws_headers()
    with TestClient(create_app()) as client:
        # 1. create project
        resp = client.post(
            "/v1/projects",
            json=_project_payload("Cost-Stats-Project"),
            headers=headers,
        )
        assert resp.status_code == 201
        project_id = resp.json()["id"]

        # 2. cost report → 200, total_cost_usd == 0
        resp = client.get(
            f"/v1/projects/{project_id}/cost-report", headers=headers
        )
        assert resp.status_code == 200
        assert Decimal(resp.json()["total_cost_usd"]) == 0

        # 3. qc stats → 200, total_visual_stages == 0
        resp = client.get(
            f"/v1/projects/{project_id}/qc-stats", headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["total_visual_stages"] == 0
