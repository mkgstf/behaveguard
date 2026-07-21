from fastapi.testclient import TestClient

from behaveguard import database as d
from behaveguard.api import app
from behaveguard.features import extract_features
from behaveguard.modeling import retrain_model

client = TestClient(app)


def _sample_payload(seed: int, shift: int = 0) -> dict:
    return {
        "collected_at": f"2026-03-{seed:02d}T00:00:00Z",
        "keyboard": {
            "events": [
                {"key": "a", "press_ts": 0 + shift, "release_ts": 90 + shift},
                {"key": "s", "press_ts": 180 + shift, "release_ts": 260 + shift},
                {"key": "d", "press_ts": 340 + shift, "release_ts": 430 + shift},
            ]
        },
        "mouse": {},
    }


def _register(email: str) -> dict:
    tokens = client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret1"}).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _admin_headers(email: str) -> dict:
    client.post("/api/v1/auth/register", json={"email": email, "password": "adminpass1"})
    d.promote_user_role(email, "platform_admin")
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "adminpass1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_ping_is_unauthenticated_and_minimal():
    response = client.get("/api/v1/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_redis_field():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert "redis" in body
    assert isinstance(body["redis"], bool)


def test_admin_claim_token_route_requires_platform_admin():
    # Claim tokens are only for pre-existing/legacy profiles with no owner
    # yet (create_claim_token rejects an already-claimed profile) — mirrors
    # a profile created by `import-xlsx` rather than self-service register.
    legacy = d.create_profile("claim-token-legacy-profile")
    headers = _register("claim-token-user@example.com")

    denied = client.post(f"/api/v1/admin/profiles/{legacy['id']}/claim-token", headers=headers)
    assert denied.status_code == 403

    admin_headers = _admin_headers("claim-token-admin@example.com")
    granted = client.post(f"/api/v1/admin/profiles/{legacy['id']}/claim-token", headers=admin_headers)
    assert granted.status_code == 200
    assert granted.json()["token"]

    # The generated token actually works with the existing claim flow.
    claimer = _register("claim-token-claimer@example.com")
    claimed = client.post("/api/v1/profiles/claim", json={"token": granted.json()["token"]}, headers=claimer)
    assert claimed.status_code == 200
    assert claimed.json()["id"] == legacy["id"]


def test_admin_claim_token_route_404s_for_unknown_profile():
    admin_headers = _admin_headers("claim-token-admin-404@example.com")
    missing_id = "00000000-0000-0000-0000-000000000000"
    response = client.post(f"/api/v1/admin/profiles/{missing_id}/claim-token", headers=admin_headers)
    assert response.status_code == 404


def test_my_profile_stats_requires_a_profile():
    headers = _register("stats-no-profile@example.com")
    response = client.get("/api/v1/profiles/me/stats", headers=headers)
    assert response.status_code == 404


def test_my_profile_stats_returns_own_session_history_only():
    headers = _register("stats-user@example.com")
    profile = client.post("/api/v1/profiles", json={"label": "stats-profile"}, headers=headers).json()
    payload = _sample_payload(1)
    features = extract_features(payload)
    for i in range(2):
        d.add_session(profile["id"], {**payload, "collected_at": f"2026-03-0{i + 1}T00:00:00Z"}, features)

    response = client.get("/api/v1/profiles/me/stats", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["id"] == profile["id"]
    assert len(body["history"]) == 2
    assert body["latest"] is not None
    assert "wpm" in body["latest"]


def test_my_profile_stats_card_has_no_other_profile_identity():
    headers = _register("stats-card-user@example.com")
    profile = client.post("/api/v1/profiles", json={"label": "stats-card-profile"}, headers=headers).json()
    payload = _sample_payload(2)
    features = extract_features(payload)
    d.add_session(profile["id"], payload, features)
    retrain_model()

    response = client.get("/api/v1/profiles/me/stats", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["card"] is not None
    assert body["card"]["rank"] in ("S", "A", "B", "C", "D")
    assert 0 <= body["card"]["overall"] <= 100
    assert "population_size" in body["card"]
    # Never leaks another profile's identity — only this profile's own numbers.
    assert "label" not in body["card"]
    assert "id" not in body["card"]


def test_verify_response_includes_privacy_safe_context_block():
    headers = _register("ctx-user@example.com")
    payload = _sample_payload(1)
    features = extract_features(payload)
    profile = client.post("/api/v1/profiles", json={"label": "ctx-profile"}, headers=headers).json()
    for i in range(3):
        d.add_session(profile["id"], {**payload, "collected_at": f"2026-03-1{i}T00:00:00Z"}, features)

    other_headers = _register("ctx-other@example.com")
    other_payload = _sample_payload(9, shift=500)
    other_features = extract_features(other_payload)
    other_profile = client.post("/api/v1/profiles", json={"label": "ctx-other-profile"}, headers=other_headers).json()
    for i in range(3):
        d.add_session(other_profile["id"], {**other_payload, "collected_at": f"2026-03-2{i}T00:00:00Z"}, other_features)
    retrain_model()

    response = client.post(f"/api/v1/verify/{profile['id']}", json={"session": payload}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["context"] is not None
    assert body["context"]["candidate_pool_size"] >= 2
    assert body["context"]["total_training_sessions"] >= 6
    assert body["context"]["own_enrollment_count"] == 3
    # Never leaks another profile's identity — only aggregate counts.
    assert "candidates" not in body["context"]
    assert "profiles" not in body["context"]


def test_google_callback_handles_cancelled_consent_gracefully():
    # Google redirects back with `error=...` and no code/state when the user
    # cancels/denies consent on its own screen — this must not be treated as
    # a server error (previously a raw 422 since code/state were required).
    response = client.get("/api/v1/auth/google/callback?error=access_denied", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "oauth_error=1" in response.headers["location"]


def test_google_callback_handles_missing_code_gracefully():
    response = client.get("/api/v1/auth/google/callback", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "oauth_error=1" in response.headers["location"]


def test_google_callback_success_redirects_to_frontend_root():
    # Regression test for the 404: tokens must land on the frontend root
    # (which AuthProvider handles globally), not a dedicated /auth/callback
    # route that was never created.
    import behaveguard.oauth_google as oauth_google

    def fake_exchange(code):
        return "fake-jwt"

    def fake_verify(jwt):
        return {"email": "google-user@example.com", "sub": "google-subject-123"}

    original_exchange = oauth_google.exchange_code_for_id_token
    original_verify = oauth_google.verify_id_token
    oauth_google.exchange_code_for_id_token = fake_exchange
    oauth_google.verify_id_token = fake_verify
    try:
        state = "test-state-token"
        client.cookies.set("bg_oauth_state", state)
        response = client.get(f"/api/v1/auth/google/callback?code=abc&state={state}", follow_redirects=False)
        assert response.status_code in (302, 307)
        location = response.headers["location"]
        assert "/auth/callback" not in location
        assert "access_token=" in location
    finally:
        oauth_google.exchange_code_for_id_token = original_exchange
        oauth_google.verify_id_token = original_verify
        client.cookies.clear()
