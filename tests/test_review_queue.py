import pytest

from behaveguard import database


def setup_database(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "review.db")
    database.init_db()


def capture(profile_id: str) -> tuple[dict, dict]:
    result = {
        "match": True,
        "best": {"profile_id": profile_id, "similarity": 88.0, "certainty": 91.0},
        "threshold": 62.0,
        "margin": 12.0,
    }
    session = {"collected_at": "2026-07-13T10:00:00+00:00", "keyboard": {"events": []}, "mouse": {}}
    return result, session


def test_reviewed_sample_is_quarantined_until_admin_approval(tmp_path, monkeypatch):
    setup_database(tmp_path, monkeypatch)
    profile = database.create_profile("tester")
    result, session = capture(profile["id"])
    event_id = database.log_verification("1toN", None, [profile["id"]], result)
    review_id = database.create_review_sample(
        event_id, "1toN", None, profile["id"], [profile["id"]], session, {"key_dwell_mean": 72.0}, result,
    )

    assert database.get_profile(profile["id"])["enrollment_count"] == 0
    assert database.review_sample_counts()["available"] == 1

    feedback = database.submit_review_feedback(review_id, True, profile["id"])
    assert feedback["status"] == "pending"
    assert database.get_profile(profile["id"])["enrollment_count"] == 0

    approved = database.promote_review_sample(review_id)
    assert approved["status"] == "approved"
    assert approved["promoted_session_id"]
    assert database.get_profile(profile["id"])["enrollment_count"] == 1
    assert database.all_training_rows()[0]["profile_id"] == profile["id"]
    assert database.review_sample_counts()["ready_for_retrain"] == 1
    assert database.mark_approved_samples_trained() == 1
    assert database.review_sample_counts()["ready_for_retrain"] == 0
    with pytest.raises(ValueError, match="already been promoted"):
        database.promote_review_sample(review_id)


def test_unlisted_identity_is_rejected(tmp_path, monkeypatch):
    setup_database(tmp_path, monkeypatch)
    profile = database.create_profile("candidate")
    result, session = capture(profile["id"])
    event_id = database.log_verification("1to1", profile["id"], [profile["id"]], result)
    review_id = database.create_review_sample(
        event_id, "1to1", profile["id"], profile["id"], [profile["id"]], session, {}, result,
    )

    rejected = database.submit_review_feedback(review_id, False, None)
    assert rejected["status"] == "rejected"
    assert database.review_sample_counts()["available"] == 0
