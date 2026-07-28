from behaveguard.calibration import (
    calibrate_verification,
    choose_operating_threshold,
    select_feature_names,
)
from behaveguard.modeling import retrain_model


def _row(profile_id: str, index: int, signal: float) -> dict:
    return {
        "id": f"{profile_id}-{index}",
        "profile_id": profile_id,
        "features": {
            "signal": signal,
            "secondary": signal * 0.5 + index,
            "constant": 1.0,
            "key_count": 100 + index,
            "passive_count": 500 + index,
        },
    }


def test_operating_threshold_prefers_target_far_constraint():
    result = choose_operating_threshold(
        genuine_scores=[0.82, 0.86, 0.91],
        impostor_scores=[0.20, 0.35, 0.50, 0.61],
        target_far=0.0,
    )

    assert 0.61 < result["threshold"] < 0.82
    assert result["false_acceptance_rate"] == 0
    assert result["false_rejection_rate"] == 0


def test_feature_selection_removes_constants_and_capture_length_proxies():
    rows = [_row("a", 1, 1.0), _row("b", 1, 10.0)]

    selected, dropped = select_feature_names(rows)

    assert "signal" in selected
    assert {"constant", "key_count", "passive_count"} <= set(dropped)


def test_model_cold_start_keeps_non_capture_features(monkeypatch, tmp_path):
    rows = [
        {
            "id": f"same-{index}",
            "profile_id": "only-profile",
            "features": {"constant": 12.0, "key_count": 100.0},
        }
        for index in range(3)
    ]
    monkeypatch.setattr("behaveguard.modeling.all_training_rows", lambda: rows)
    monkeypatch.setattr("behaveguard.modeling.MODEL_PATH", tmp_path / "model.joblib")

    retrain_model()
    artifact = __import__("joblib").load(tmp_path / "model.joblib")

    assert artifact["feature_names"] == ["constant"]
    assert artifact["dropped_features"] == ["key_count"]


def test_calibration_uses_session_and_identity_disjoint_trials():
    rows = [
        *[_row("a", index, 0.5 + index * 0.05) for index in range(3)],
        *[_row("b", index, 5.0 + index * 0.05) for index in range(3)],
        *[_row("c", index, 10.0 + index * 0.05) for index in range(3)],
    ]
    names, _ = select_feature_names(rows)

    report = calibrate_verification(rows, names, target_far=0.05)

    assert report["method"].startswith("profile_stratified_session_folds")
    assert report["global_metrics"]["genuine_trials"] == 9
    assert report["global_metrics"]["unknown_trials"] == 9
    assert set(report["profile_thresholds"]) == {"a", "b", "c"}
    assert 0 <= report["global_threshold"] <= 100
