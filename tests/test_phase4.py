from fastapi.testclient import TestClient

from behaveguard import database as d
from behaveguard.api import app
from behaveguard.features import extract_features
from behaveguard.modeling import retrain_model

client = TestClient(app)


def _sample_payload(seed: int) -> dict:
    return {
        "collected_at": f"2026-02-{seed:02d}T00:00:00Z",
        "keyboard": {
            "events": [
                {"key": "a", "press_ts": 0, "release_ts": 90},
                {"key": "s", "press_ts": 180, "release_ts": 260},
            ]
        },
        "mouse": {},
    }


def _admin_headers(email: str) -> dict:
    client.post("/api/v1/auth/register", json={"email": email, "password": "adminpass1"})
    d.promote_user_role(email, "platform_admin")
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "adminpass1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_login_rate_limit_blocks_after_five_attempts():
    for _ in range(5):
        response = client.post("/api/v1/auth/login", json={"email": "rl-test@example.com", "password": "wrong"})
        assert response.status_code == 401
    blocked = client.post("/api/v1/auth/login", json={"email": "rl-test@example.com", "password": "wrong"})
    assert blocked.status_code == 429


def test_repeated_rate_limit_blocks_raise_brute_force_alert():
    # Register (and promote) the admin account *before* deliberately tripping
    # the rate limiter below — register/login share the same IP-scoped
    # bucket, so doing it afterward would have this test's own admin lookup
    # blocked by the very rate limit it's trying to observe the effects of.
    admin_headers = _admin_headers("phase4-brute-admin@example.com")
    for _ in range(9):
        client.post("/api/v1/auth/login", json={"email": "rl-brute@example.com", "password": "wrong"})
    alerts = client.get("/api/v1/admin/security-alerts", headers=admin_headers).json()
    assert any(alert["kind"] == "brute_force" for alert in alerts)


def test_verify_rate_limit_is_scoped_per_profile():
    tokens = client.post(
        "/api/v1/auth/register", json={"email": "rl-verify@example.com", "password": "supersecret1"}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    payload = _sample_payload(1)
    features = extract_features(payload)
    profile = client.post("/api/v1/profiles", json={"label": "rl-verify-profile"}, headers=headers).json()
    for i in range(3):
        d.add_session(profile["id"], {**payload, "collected_at": f"2026-02-0{i + 1}T00:00:00Z"}, features)
    retrain_model()

    statuses = []
    for _ in range(6):
        response = client.post(f"/api/v1/verify/{profile['id']}", json={"session": payload}, headers=headers)
        statuses.append(response.status_code)
    assert statuses[:5] == [200] * 5
    assert statuses[5] == 429


def test_replay_detection_raises_alert_on_exact_repeat():
    tokens = client.post(
        "/api/v1/auth/register", json={"email": "replay-unit@example.com", "password": "supersecret1"}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    payload = _sample_payload(2)
    features = extract_features(payload)
    profile = client.post("/api/v1/profiles", json={"label": "replay-unit-profile"}, headers=headers).json()
    for i in range(3):
        d.add_session(profile["id"], {**payload, "collected_at": f"2026-02-1{i}T00:00:00Z"}, features)
    retrain_model()

    client.post(f"/api/v1/verify/{profile['id']}", json={"session": payload}, headers=headers)
    client.post(f"/api/v1/verify/{profile['id']}", json={"session": payload}, headers=headers)

    admin_headers = _admin_headers("phase4-replay-admin@example.com")
    alerts = client.get("/api/v1/admin/security-alerts", headers=admin_headers).json()
    replay_alerts = [a for a in alerts if a["kind"] == "replay_suspected" and a["profile_id"] == profile["id"]]
    assert len(replay_alerts) == 1


def test_security_alert_ack_and_dismiss():
    profile = d.create_profile("alert-mgmt-profile")
    alert = d.create_security_alert("replay_suspected", "low", {"note": "test"}, profile_id=profile["id"])

    admin_headers = _admin_headers("phase4-mgmt-admin@example.com")
    response = client.patch(
        f"/api/v1/admin/security-alerts/{alert['id']}", json={"status": "ack"}, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ack"

    open_alerts = client.get("/api/v1/admin/security-alerts?status=open", headers=admin_headers).json()
    assert alert["id"] not in {a["id"] for a in open_alerts}


def test_security_alerts_endpoint_requires_platform_admin():
    tokens = client.post(
        "/api/v1/auth/register", json={"email": "phase4-nonadmin@example.com", "password": "supersecret1"}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    response = client.get("/api/v1/admin/security-alerts", headers=headers)
    assert response.status_code == 403
