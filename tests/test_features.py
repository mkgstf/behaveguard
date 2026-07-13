from behaveguard.features import extract_features


def test_extract_features_handles_missing_modalities():
    features = extract_features({"keyboard": {"events": []}, "mouse": {}})
    assert features
    assert all(value == value for value in features.values())


def test_keyboard_rhythm_is_extracted():
    session = {
        "keyboard": {"events": [
            {"key_id": "a", "key_category": "alphanum", "press_ts": 100, "release_ts": 180},
            {"key_id": "b", "key_category": "alphanum", "press_ts": 250, "release_ts": 310},
        ]},
        "mouse": {},
    }
    features = extract_features(session)
    assert features["key_dwell_mean"] == 70
    assert features["key_iki_mean"] == 150
