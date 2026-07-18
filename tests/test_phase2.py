from fastapi.testclient import TestClient

from behaveguard import database as d
from behaveguard.api import app
from behaveguard.features import extract_features
from behaveguard.merging import scan_and_auto_merge
from behaveguard.modeling import retrain_model

client = TestClient(app)


def _register_and_enroll(email: str, label: str, features: dict) -> tuple[dict, str]:
    tokens = client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret1"}).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    profile = client.post("/api/v1/profiles", json={"label": label}, headers=headers).json()
    for i in range(3):
        d.add_session(profile["id"], {"collected_at": f"2026-01-0{i + 1}T00:00:00Z"}, features)
    retrain_model()
    return headers, profile["id"]


def _sample_payload(seed: int) -> dict:
    return {
        "collected_at": f"2026-01-0{seed}T00:00:00Z",
        "keyboard": {
            "events": [
                {"key": "a", "press_ts": 0, "release_ts": 90},
                {"key": "s", "press_ts": 180, "release_ts": 260},
                {"key": "d", "press_ts": 340, "release_ts": 430},
            ]
        },
        "mouse": {},
    }


def test_verify_never_creates_a_review_sample():
    payload = _sample_payload(1)
    features = extract_features(payload)
    headers, profile_id = _register_and_enroll("phase2-a@example.com", "phase2-a-profile", features)

    counts_before = d.review_sample_counts()
    response = client.post(f"/api/v1/verify/{profile_id}", json={"session": payload}, headers=headers)
    assert response.status_code == 200
    assert "review_sample_id" not in response.json()
    assert "feedback_status" not in response.json()
    counts_after = d.review_sample_counts()
    assert counts_after["awaiting_feedback"] == counts_before["awaiting_feedback"]


def test_confident_self_verification_auto_enrolls(monkeypatch):
    payload = _sample_payload(1)
    features = extract_features(payload)
    headers, profile_id = _register_and_enroll("phase2-b@example.com", "phase2-b-profile", features)

    # The auto-enrollment *gate* (api.py's threshold check + add_session call)
    # is what Phase 2 actually added and what this test verifies — so the
    # score itself is mocked here rather than relying on modeling.py's real
    # RobustScaler pipeline, which has its own pre-existing numerical
    # behavior on tiny/imbalanced synthetic datasets (e.g. one profile
    # dominating the fitted median) that's orthogonal to what's under test.
    def fake_score_session(session, candidate_ids):
        return {
            "model_version": "test",
            "match": True,
            "best": {"profile_id": profile_id, "similarity": 95.0, "certainty": 99.0},
            "candidates": [{"profile_id": profile_id, "similarity": 95.0, "certainty": 99.0}],
            "margin": 0.0,
            "features": features,
        }

    monkeypatch.setattr("behaveguard.api.score_session", fake_score_session)

    before = len(d.profile_sessions(profile_id))
    response = client.post(f"/api/v1/verify/{profile_id}", json={"session": payload}, headers=headers)
    body = response.json()
    assert body["match"] is True
    assert body["auto_enrolled"] is True
    assert len(d.profile_sessions(profile_id)) == before + 1


def test_low_confidence_verification_does_not_auto_enroll(monkeypatch):
    payload = _sample_payload(1)
    features = extract_features(payload)
    headers, profile_id = _register_and_enroll("phase2-c@example.com", "phase2-c-profile", features)
    before = len(d.profile_sessions(profile_id))

    def fake_score_session(session, candidate_ids):
        return {
            "model_version": "test",
            "match": True,  # cleared the accept threshold (~62) but not the auto-enroll bar (85)
            "best": {"profile_id": profile_id, "similarity": 70.0, "certainty": 80.0},
            "candidates": [{"profile_id": profile_id, "similarity": 70.0, "certainty": 80.0}],
            "margin": 0.0,
            "features": features,
        }

    monkeypatch.setattr("behaveguard.api.score_session", fake_score_session)

    response = client.post(f"/api/v1/verify/{profile_id}", json={"session": payload}, headers=headers)
    body = response.json()
    assert body["match"] is True
    assert body["auto_enrolled"] is False
    assert len(d.profile_sessions(profile_id)) == before


def test_identify_never_creates_a_review_sample():
    payload = _sample_payload(1)
    features = extract_features(payload)
    _, profile_id = _register_and_enroll("phase2-d@example.com", "phase2-d-profile", features)

    admin_tokens = client.post(
        "/api/v1/auth/register", json={"email": "phase2-admin-d@example.com", "password": "adminpass1"}
    ).json()
    d.promote_user_role("phase2-admin-d@example.com", "platform_admin")
    admin_login = client.post(
        "/api/v1/auth/login", json={"email": "phase2-admin-d@example.com", "password": "adminpass1"}
    )
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    response = client.post(
        "/api/v1/identify", json={"session": payload, "profile_ids": [profile_id]}, headers=admin_headers
    )
    assert response.status_code == 200
    assert "review_sample_id" not in response.json()


def _fake_artifact(centroids: dict[str, list[float]]) -> dict:
    import numpy as np

    profiles = {}
    for profile_id, vector in centroids.items():
        array = np.asarray(vector, dtype=np.float64)
        norm = np.linalg.norm(array)
        profiles[profile_id] = {"centroid": array / norm if norm else array, "count": 1, "dispersion": 0.0}
    return {"version": "test", "feature_names": ["f1", "f2"], "profiles": profiles, "scaler": None, "svm": None}


def test_auto_merge_scan_merges_duplicates_and_skips_distinct_profiles(monkeypatch):
    a = d.create_profile("merge-scan-a")
    b = d.create_profile("merge-scan-b")
    c = d.create_profile("merge-scan-c")
    d.add_session(a["id"], {"collected_at": "2026-01-01T00:00:00Z"}, {"f1": 1.0, "f2": 0.0})
    d.add_session(b["id"], {"collected_at": "2026-01-02T00:00:00Z"}, {"f1": 1.0, "f2": 0.0})
    d.add_session(c["id"], {"collected_at": "2026-01-03T00:00:00Z"}, {"f1": 0.0, "f2": 1.0})

    # Isolate the merge-*decision* logic from the RobustScaler's numerical
    # edge cases on tiny synthetic datasets (a real active population is
    # large/varied enough never to hit this; a 2-3 row synthetic test can
    # coincidentally hit a zero-scale/zero-centroid degenerate case that has
    # nothing to do with what this test is actually checking).
    fake_artifact = _fake_artifact({a["id"]: [1.0, 0.0], b["id"]: [1.0, 0.0], c["id"]: [0.0, 1.0]})
    monkeypatch.setattr("behaveguard.merging.load_model", lambda: fake_artifact)
    monkeypatch.setattr("behaveguard.merging.retrain_model", lambda: None)

    result = scan_and_auto_merge(threshold=0.97)
    merged_labels = {pair["source_label"] for pair in result["merged"]}
    assert merged_labels == {"merge-scan-a"} or merged_labels == {"merge-scan-b"}

    remaining = {profile["label"] for profile in d.list_profiles()}
    assert "merge-scan-c" in remaining
    assert len(remaining & {"merge-scan-a", "merge-scan-b"}) == 1


def test_merge_event_can_be_reverted(monkeypatch):
    a = d.create_profile("revert-scan-a")
    b = d.create_profile("revert-scan-b")
    d.add_session(a["id"], {"collected_at": "2026-01-01T00:00:00Z"}, {"f1": 1.0, "f2": 0.0})
    d.add_session(b["id"], {"collected_at": "2026-01-02T00:00:00Z"}, {"f1": 1.0, "f2": 0.0})

    fake_artifact = _fake_artifact({a["id"]: [1.0, 0.0], b["id"]: [1.0, 0.0]})
    monkeypatch.setattr("behaveguard.merging.load_model", lambda: fake_artifact)
    monkeypatch.setattr("behaveguard.merging.retrain_model", lambda: None)

    result = scan_and_auto_merge(threshold=0.97)
    assert len(result["merged"]) == 1
    event_id = result["merged"][0]["merge_event_id"]

    reverted = d.revert_merge_event(event_id)
    assert reverted["status"] == "reverted"
    remaining = {profile["label"] for profile in d.list_profiles()}
    assert {"revert-scan-a", "revert-scan-b"}.issubset(remaining)


def test_merge_scan_requires_platform_admin():
    tokens = client.post(
        "/api/v1/auth/register", json={"email": "phase2-nonadmin@example.com", "password": "supersecret1"}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    response = client.post("/api/v1/admin/merge/scan", headers=headers)
    assert response.status_code == 403
