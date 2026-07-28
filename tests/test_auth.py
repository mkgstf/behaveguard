from fastapi.testclient import TestClient

from behaveguard import database as d
from behaveguard.api import app

client = TestClient(app)


def _register(email: str, password: str = "supersecret1") -> dict:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response.json()


def _auth_headers(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_register_login_and_me():
    tokens = _register("regular@example.com")
    assert tokens["user"]["role"] == "user"

    response = client.get("/api/v1/auth/me", headers=_auth_headers(tokens))
    assert response.status_code == 200
    assert response.json()["email"] == "regular@example.com"

    login = client.post("/api/v1/auth/login", json={"email": "regular@example.com", "password": "supersecret1"})
    assert login.status_code == 200

    wrong = client.post("/api/v1/auth/login", json={"email": "regular@example.com", "password": "nope"})
    assert wrong.status_code == 401


def test_duplicate_email_is_rejected():
    _register("dupe@example.com")
    response = client.post("/api/v1/auth/register", json={"email": "DUPE@example.com", "password": "supersecret1"})
    assert response.status_code == 409


def test_self_service_profile_is_one_per_user():
    tokens = _register("enroller@example.com")
    headers = _auth_headers(tokens)

    created = client.post("/api/v1/profiles", json={"label": "enroller-profile"}, headers=headers)
    assert created.status_code == 201
    assert created.json()["user_id"] is not None

    second = client.post("/api/v1/profiles", json={"label": "another-profile"}, headers=headers)
    assert second.status_code == 409


def test_regular_user_cannot_access_admin_routes_or_others_profiles():
    owner_tokens = _register("owner@example.com")
    owner_headers = _auth_headers(owner_tokens)
    owned = client.post("/api/v1/profiles", json={"label": "owner-profile"}, headers=owner_headers).json()

    outsider_tokens = _register("outsider@example.com")
    outsider_headers = _auth_headers(outsider_tokens)

    blacklist_attempt = client.patch(
        f"/api/v1/profiles/{owned['id']}", json={"blacklisted": True}, headers=outsider_headers
    )
    assert blacklist_attempt.status_code == 403

    verify_attempt = client.post(
        f"/api/v1/verify/{owned['id']}", json={"session": {}}, headers=outsider_headers
    )
    assert verify_attempt.status_code == 403

    admin_attempt = client.get("/api/v1/admin/analytics", headers=outsider_headers)
    assert admin_attempt.status_code == 403

    unauthenticated = client.get("/api/v1/profiles")
    assert unauthenticated.status_code == 401


def test_platform_admin_can_manage_any_profile():
    admin_tokens = _register("admin-user@example.com")
    d.promote_user_role("admin-user@example.com", "platform_admin")
    admin_login = client.post(
        "/api/v1/auth/login", json={"email": "admin-user@example.com", "password": "supersecret1"}
    )
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    other_tokens = _register("someone-else@example.com")
    other_headers = _auth_headers(other_tokens)
    profile = client.post("/api/v1/profiles", json={"label": "someone-elses-profile"}, headers=other_headers).json()

    response = client.get("/api/v1/admin/analytics", headers=admin_headers)
    assert response.status_code == 200

    response = client.patch(f"/api/v1/profiles/{profile['id']}", json={"blacklisted": True}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["blacklisted"] == 1


def test_refresh_token_rotation_and_reuse_is_blocked():
    tokens = _register("refresher@example.com")
    refresh_response = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh_response.status_code == 200

    reuse_response = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reuse_response.status_code == 401


def test_logout_revokes_refresh_token():
    tokens = _register("logout-user@example.com")
    logout_response = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout_response.status_code == 204

    refresh_response = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh_response.status_code == 401


def test_claim_token_links_legacy_profile_to_new_account():
    legacy = d.create_profile("legacy-for-claim-test")
    token = d.create_claim_token(legacy["id"])

    claimant_tokens = _register("claimant-test@example.com")
    claimant_headers = _auth_headers(claimant_tokens)

    response = client.post("/api/v1/profiles/claim", json={"token": token}, headers=claimant_headers)
    assert response.status_code == 200
    assert response.json()["user_id"] is not None

    reuse = client.post("/api/v1/profiles/claim", json={"token": token}, headers=claimant_headers)
    assert reuse.status_code == 409


def test_claim_blocked_if_account_already_owns_a_profile():
    tokens = _register("already-owns@example.com")
    headers = _auth_headers(tokens)
    client.post("/api/v1/profiles", json={"label": "already-owns-profile"}, headers=headers)

    legacy = d.create_profile("legacy-blocked-claim")
    token = d.create_claim_token(legacy["id"])

    response = client.post("/api/v1/profiles/claim", json={"token": token}, headers=headers)
    assert response.status_code == 409
