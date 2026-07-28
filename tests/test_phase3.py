from unittest.mock import patch

import torch
from fastapi.testclient import TestClient

from behaveguard import database as d
from behaveguard.api import app
from behaveguard.features import extract_features
from behaveguard.jobs import get_job_status, trigger_retrain_job
from behaveguard.modeling import retrain_model
from behaveguard.training import train_neural_and_promote
from behaveguard.worker import run_retrain_job

client = TestClient(app)


def _sample_payload(seed: int, shift: int = 0) -> dict:
    return {
        "collected_at": f"2026-01-{seed:02d}T00:00:00Z",
        "keyboard": {
            "events": [
                {"key": "a", "press_ts": 0 + shift, "release_ts": 90 + shift},
                {"key": "s", "press_ts": 180 + shift, "release_ts": 260 + shift},
                {"key": "d", "press_ts": 340 + shift, "release_ts": 430 + shift},
            ]
        },
        "mouse": {},
    }


def _seed_two_profiles():
    a = d.create_profile("neural-job-a")
    b = d.create_profile("neural-job-b")
    for i in range(1, 5):
        payload = _sample_payload(i)
        d.add_session(a["id"], payload, extract_features(payload))
    for i in range(1, 5):
        payload = _sample_payload(i, shift=500)
        d.add_session(b["id"], payload, extract_features(payload))
    retrain_model()
    return a, b


def test_run_retrain_job_processes_successfully():
    _seed_two_profiles()
    job_id = "test-job-direct"
    result = run_retrain_job(job_id, "retrain_neural", "test:direct")

    assert result["trained"] is True
    final = get_job_status(job_id)
    assert final["status"] == "done"
    assert final["result"]["trained"] is True


def test_trigger_retrain_job_starts_processing():
    _seed_two_profiles()
    job_id = trigger_retrain_job("test:trigger")
    # Local-dev fallback runs this in a background thread immediately, so by
    # the time we check, it may already be past "queued" — assert it was at
    # least started, rather than asserting an exact status that depends on
    # thread timing.
    status = get_job_status(job_id)
    assert status is not None
    assert status["status"] in ("queued", "running", "done")


def test_enroll_route_enqueues_job_instead_of_blocking():
    tokens = client.post(
        "/api/v1/auth/register", json={"email": "phase3-enroll@example.com", "password": "supersecret1"}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    profile = client.post("/api/v1/profiles", json={"label": "phase3-enroll-profile"}, headers=headers).json()

    response = client.post(
        f"/api/v1/profiles/{profile['id']}/enroll", json={"session": _sample_payload(1)}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert "neural_retrain_job_id" in body
    assert "training" in body  # classical retrain still happens inline
    assert get_job_status(body["neural_retrain_job_id"])["status"] in ("queued", "running", "done")


def test_admin_retrain_enqueues_job():
    admin_tokens = client.post(
        "/api/v1/auth/register", json={"email": "phase3-admin@example.com", "password": "adminpass1"}
    ).json()
    d.promote_user_role("phase3-admin@example.com", "platform_admin")
    admin_login = client.post("/api/v1/auth/login", json={"email": "phase3-admin@example.com", "password": "adminpass1"})
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    response = client.post("/api/v1/admin/retrain", headers=admin_headers)
    assert response.status_code == 200
    assert "neural_retrain_job_id" in response.json()


def test_admin_jobs_endpoint_lists_recent_jobs():
    admin_tokens = client.post(
        "/api/v1/auth/register", json={"email": "phase3-jobs-admin@example.com", "password": "adminpass1"}
    ).json()
    d.promote_user_role("phase3-jobs-admin@example.com", "platform_admin")
    admin_login = client.post(
        "/api/v1/auth/login", json={"email": "phase3-jobs-admin@example.com", "password": "adminpass1"}
    )
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    trigger_retrain_job("test:jobs-list")
    response = client.get("/api/v1/admin/jobs", headers=admin_headers)
    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_jobs_endpoint_requires_platform_admin():
    tokens = client.post(
        "/api/v1/auth/register", json={"email": "phase3-nonadmin@example.com", "password": "supersecret1"}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    response = client.get("/api/v1/admin/jobs", headers=headers)
    assert response.status_code == 403


def test_promotion_gate_keeps_active_model_when_candidate_is_worse():
    _seed_two_profiles()
    first = train_neural_and_promote(epochs=10)
    assert first["promoted"] is True
    active_before = d.get_active_model_version("neural")

    call_count = {"n": 0}
    from behaveguard.training import _evaluate_accuracy as real_evaluate

    def fake_evaluate(model, tensors, targets):
        call_count["n"] += 1
        return 0.0 if call_count["n"] == 1 else real_evaluate(model, tensors, targets)

    with patch("behaveguard.training._evaluate_accuracy", side_effect=fake_evaluate):
        second = train_neural_and_promote(epochs=10, seed=99)

    assert second["promoted"] is False
    active_after = d.get_active_model_version("neural")
    assert active_after["id"] == active_before["id"]

    versions = d.list_model_versions("neural")
    statuses = {version["id"]: version["status"] for version in versions}
    assert statuses[second["model_version_id"]] == "candidate"


def test_promotion_gate_promotes_first_model_with_no_baseline():
    _seed_two_profiles()
    assert d.get_active_model_version("neural") is None
    result = train_neural_and_promote(epochs=10)
    assert result["promoted"] is True
    assert result["baseline_accuracy"] is None
    active = d.get_active_model_version("neural")
    assert active is not None
    checkpoint = torch.load(active["artifact_uri"], map_location="cpu", weights_only=False)
    assert checkpoint["format_version"] == 2
    assert len(checkpoint["scaler"]["center"]) == len(checkpoint["feature_names"])
    assert len(checkpoint["trained_session_ids"]) == 8
