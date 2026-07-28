import numpy as np
import torch

from behaveguard.neural import BehavioralSequenceNet, session_sequences
from behaveguard.personal_verifier import personal_folds
from behaveguard.training import (
    _eligible_rows,
    _fit_scaler,
    _should_promote,
    _split_holdout,
)


def test_neural_model_shapes():
    model = BehavioralSequenceNet(feature_dim=12, class_count=3)
    embedding, logits = model(torch.zeros(2, 32, 6), torch.zeros(2, 64, 6), torch.zeros(2, 12))
    assert embedding.shape == (2, 128)
    assert logits.shape == (2, 3)


def test_mouse_sequence_derives_deltas_from_absolute_coordinates():
    _, mouse = session_sequences(
        {
            "mouse": {
                "passive_points": [
                    {"x": 10, "y": 20, "ts": 100},
                    {"x": 40, "y": 60, "ts": 200},
                ]
            }
        },
        key_length=4,
        mouse_length=4,
    )

    assert np.allclose(mouse[1, :2], [0.3, 0.4])
    assert mouse[1, 3] == 0.5


def test_neural_embeddings_ignore_trailing_padding():
    torch.manual_seed(7)
    model = BehavioralSequenceNet(feature_dim=3, class_count=2).eval()
    short_keyboard = torch.zeros(1, 8, 6)
    short_mouse = torch.zeros(1, 8, 6)
    short_keyboard[:, :2, -1] = 1
    short_mouse[:, :2, -1] = 1
    long_keyboard = torch.zeros(1, 64, 6)
    long_mouse = torch.zeros(1, 64, 6)
    long_keyboard[:, :2] = short_keyboard[:, :2]
    long_mouse[:, :2] = short_mouse[:, :2]
    features = torch.zeros(1, 3)

    short_embedding, _ = model(short_keyboard, short_mouse, features)
    long_embedding, _ = model(long_keyboard, long_mouse, features)

    assert torch.allclose(short_embedding, long_embedding, atol=1e-6)


def test_personal_folds_never_mix_held_parent_sessions():
    rows = [
        {"id": f"g{index}", "profile_id": "target", "label": "target"} for index in range(4)
    ] + [
        {"id": f"i{index}", "profile_id": f"impostor-{index}", "label": f"impostor-{index}"} for index in range(8)
    ]
    folds = personal_folds(rows, "target")
    held_impostors = []
    for fold in folds:
        train_ids = {row["id"] for row in fold["train"]}
        assert fold["test_genuine"]["id"] not in train_ids
        assert all(row["id"] not in train_ids for row in fold["test_impostors"])
        held_impostors.extend(row["id"] for row in fold["test_impostors"])
    assert sorted(held_impostors) == [f"i{index}" for index in range(8)]


def _training_row(profile_id: str, session_id: str, collected_at: str, value: float) -> dict:
    return {
        "id": session_id,
        "profile_id": profile_id,
        "collected_at": collected_at,
        "features": {"signal": value},
        "payload": {"keyboard": {"events": []}, "mouse": {}},
    }


def test_neural_training_excludes_single_session_profiles():
    rows = [
        _training_row("repeated", "r1", "2026-01-01", 1),
        _training_row("repeated", "r2", "2026-01-02", 2),
        _training_row("single", "s1", "2026-01-03", 3),
    ]

    assert {row["profile_id"] for row in _eligible_rows(rows)} == {"repeated"}


def test_holdout_is_latest_complete_session_and_scaler_is_train_only():
    rows = [
        _training_row("a", "a1", "2026-01-01", 0),
        _training_row("a", "a2", "2026-01-02", 2),
        _training_row("a", "a3", "2026-01-03", 1000),
        _training_row("b", "b1", "2026-01-01", 10),
        _training_row("b", "b2", "2026-01-02", 12),
        _training_row("b", "b3", "2026-01-03", 2000),
    ]

    train, holdout = _split_holdout(rows)
    assert {row["id"] for row in holdout} == {"a3", "b3"}
    scaler = _fit_scaler(train, ["signal"])
    assert float(scaler.center_[0]) < 100


def test_neural_promotion_prioritizes_balanced_accuracy_then_calibration():
    baseline = {
        "balanced_accuracy": 0.8,
        "macro_f1": 0.8,
        "nll": 0.7,
    }

    assert _should_promote(
        {"balanced_accuracy": 0.8, "macro_f1": 0.8, "nll": 0.6},
        baseline,
    )
    assert not _should_promote(
        {"balanced_accuracy": 0.75, "macro_f1": 0.9, "nll": 0.2},
        baseline,
    )
