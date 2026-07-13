import torch

from behaveguard.neural import BehavioralSequenceNet


def test_neural_model_shapes():
    model = BehavioralSequenceNet(feature_dim=12, class_count=3)
    embedding, logits = model(torch.zeros(2, 32, 6), torch.zeros(2, 64, 6), torch.zeros(2, 12))
    assert embedding.shape == (2, 128)
    assert logits.shape == (2, 3)
