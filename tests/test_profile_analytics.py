from behaveguard import database
from behaveguard.profile_analytics import compare_probe_to_profile, session_behavior_metrics


def test_typing_and_mouse_metrics():
    events = [
        {"key_id": chr(97 + index % 20), "key_category": "alphanum", "press_ts": index * 1200, "release_ts": index * 1200 + 100}
        for index in range(11)
    ]
    session = {
        "keyboard": {"events": events},
        "mouse": {"passive_points": [{"x": 0, "y": 0, "ts": 0}, {"x": 100, "y": 0, "ts": 1000}]},
    }
    metrics = session_behavior_metrics(session)
    assert metrics["wpm"] == 11
    assert metrics["dwell_ms"] == 100
    assert metrics["mouse_speed_pxs"] == 100


def test_identification_run_comparison_matches_original_profile():
    profile = database.create_profile("original")
    session = {
        "keyboard": {"events": [
            {"key_id": "a", "key_category": "alphanum", "press_ts": 0, "release_ts": 90},
            {"key_id": "b", "key_category": "alphanum", "press_ts": 250, "release_ts": 340},
        ]},
        "mouse": {"passive_points": [{"x": 0, "y": 0, "ts": 0}, {"x": 100, "y": 0, "ts": 1000}]},
    }
    features = {"key_dwell_mean": 90.0, "key_iki_mean": 250.0, "passive_speed_mean": 100.0}
    database.add_session(profile["id"], session, features)

    comparison = compare_probe_to_profile(profile["id"], session, features)

    assert comparison["overall_coincidence"] == 100.0
    assert comparison["enrollment_sessions"] == 1
    assert all(row["delta_percent"] == 0 for row in comparison["metrics"] if row["delta_percent"] is not None)
