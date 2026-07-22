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


def _benchmark(client: TestClient, release: dict, *, score: float = 0.95) -> tuple[dict, dict]:
    response = client.post(
        f"/v1/model-releases/{release['id']}/benchmarks",
        json={
            "expected_model_state_version": release["state_version"],
            "dataset": {
                "dataset_key": "audio-golden",
                "release": "golden@1",
                "annotation_release": "annotation@1",
                "samples": [
                    {
                        "sample_id": "dialogue-1",
                        "source_sha256": "a" * 64,
                        "duration_seconds": 10,
                        "critical": True,
                    }
                ],
            },
            "policy": {
                "policy_key": "audio-production",
                "release": "policy@1",
                "minimum_sample_count": 1,
                "minimum_metric_scores": {"word_accuracy": 0.9},
                "maximum_critical_failure_rate": 0,
                "maximum_human_reject_rate": 0,
                "maximum_cost_per_passed_second": 0.01,
                "maximum_p95_latency_seconds": 20,
            },
            "evidence": {
                "technical_access_gate": "PASS",
                "rollback_test": "PASS",
                "reproducibility_test": "PASS",
                "calibration_complete": True,
                "weights_sha256": "b" * 64,
                "runtime_fingerprint": "cuda-13|torch-2.9|L4",
            },
            "results": [
                {
                    "sample_id": "dialogue-1",
                    "metric_scores": {"word_accuracy": score},
                    "latency_seconds": 8,
                    "cost_usd": 0.01,
                    "output_duration_seconds": 10,
                }
            ],
        },
    )
    assert response.status_code == 201
    model = next(
        item
        for item in client.get("/v1/model-releases?model_key=AUDIO_ANALYSIS").json()
        if item["id"] == release["id"]
    )
    return response.json(), model


def test_model_release_api_gates_license_and_traffic() -> None:
    with TestClient(create_app()) as client:
        release = _create_release(client)
        denied = client.post(
            f"/v1/model-releases/{release['id']}/automation",
            json={"target": "CANARY", "traffic_percent": 10, "expected_state_version": 1},
        )
        assert denied.status_code == 409

        approved = _approve(client, release)
        no_benchmark = client.post(
            f"/v1/model-releases/{release['id']}/automation",
            json={"target": "ACTIVE", "traffic_percent": 100, "expected_state_version": 2},
        )
        assert no_benchmark.status_code == 409
        benchmark, approved = _benchmark(client, approved)
        assert benchmark["approved"] is True
        assert approved["approved_benchmark_release_id"] == benchmark["id"]
        listed_benchmarks = client.get(
            f"/v1/model-releases/{release['id']}/benchmarks"
        ).json()
        assert [item["id"] for item in listed_benchmarks] == [benchmark["id"]]
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
        _, first = _benchmark(client, _approve(client, _create_release(client, "audio@1")))
        _, second = _benchmark(client, _approve(client, _create_release(client, "audio@2")))
        enabled = client.post(
            f"/v1/model-releases/{first['id']}/automation",
            json={"target": "ACTIVE", "traffic_percent": 100, "expected_state_version": 3},
        )
        assert enabled.status_code == 200
        canary = client.post(
            f"/v1/model-releases/{second['id']}/automation",
            json={"target": "CANARY", "traffic_percent": 5, "expected_state_version": 3},
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


def test_failed_benchmark_is_audited_but_not_adopted() -> None:
    with TestClient(create_app()) as client:
        approved = _approve(client, _create_release(client, "audio@failed"))
        benchmark, model = _benchmark(client, approved, score=0.2)

        assert benchmark["approved"] is False
        assert "METRIC_BELOW_THRESHOLD:word_accuracy" in benchmark["failed_gates"]
        assert model["approved_benchmark_release_id"] is None
        assert model["state_version"] == approved["state_version"]
        denied = client.post(
            f"/v1/model-releases/{model['id']}/automation",
            json={
                "target": "ACTIVE",
                "traffic_percent": 100,
                "expected_state_version": model["state_version"],
            },
        )
        assert denied.status_code == 409
