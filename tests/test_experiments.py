from behaveguard.experiments import window_session


def test_windows_are_disjoint():
    session = {
        "keyboard": {"events": [{"press_ts": index} for index in range(10)]},
        "mouse": {"passive_points": [{"ts": index} for index in range(10)], "dot_trials": [], "drag_trials": [], "track_trials": []},
    }
    left = window_session(session, 0, 2)
    right = window_session(session, 1, 2)
    assert [row["press_ts"] for row in left["keyboard"]["events"]] == list(range(5))
    assert [row["press_ts"] for row in right["keyboard"]["events"]] == list(range(5, 10))
