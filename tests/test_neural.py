import torch

from behaveguard.neural import BehavioralSequenceNet
from behaveguard.personal_verifier import personal_folds


def test_neural_model_shapes():
    model = BehavioralSequenceNet(feature_dim=12, class_count=3)
    embedding, logits = model(torch.zeros(2, 32, 6), torch.zeros(2, 64, 6), torch.zeros(2, 12))
    assert embedding.shape == (2, 128)
    assert logits.shape == (2, 3)


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
