from behaveguard.profile_analytics import session_behavior_metrics


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
