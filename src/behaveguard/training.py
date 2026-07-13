from __future__ import annotations

from collections import Counter

import numpy as np
import torch
from torch import nn

from .config import NEURAL_PATH, ensure_directories
from .database import all_training_rows
from .features import feature_vector
from .modeling import load_model
from .neural import BehavioralSequenceNet, session_sequences


def train_neural(epochs: int = 30, seed: int = 42) -> dict:
    torch.manual_seed(seed)
    np.random.seed(seed)
    rows = all_training_rows()
    counts = Counter(row["profile_id"] for row in rows)
    if len(counts) < 2 or min(counts.values(), default=0) < 2 or len(rows) < 6:
        return {"trained": False, "reason": "Need at least two profiles, two independent sessions each, and six sessions total"}
    artifact = load_model()
    names = artifact["feature_names"]
    classes = sorted(counts)
    class_index = {value: index for index, value in enumerate(classes)}
    keyboards, mice, vectors, targets = [], [], [], []
    for row in rows:
        keyboard, mouse = session_sequences(row["payload"])
        keyboards.append(keyboard)
        mice.append(mouse)
        vectors.append(artifact["scaler"].transform(feature_vector(row["features"], names).reshape(1, -1))[0])
        targets.append(class_index[row["profile_id"]])
    tensors = [torch.tensor(np.asarray(values), dtype=torch.float32) for values in (keyboards, mice, vectors)]
    target_tensor = torch.tensor(targets, dtype=torch.long)
    model = BehavioralSequenceNet(len(names), len(classes))
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-3)
    model.train()
    final_loss = 0.0
    for _ in range(epochs):
        optimizer.zero_grad()
        _, logits = model(*tensors)
        loss = nn.functional.cross_entropy(logits, target_tensor)
        loss.backward()
        optimizer.step()
        final_loss = float(loss.detach())
    ensure_directories()
    torch.save({"state_dict": model.state_dict(), "classes": classes, "feature_names": names, "loss": final_loss}, NEURAL_PATH)
    return {"trained": True, "epochs": epochs, "loss": round(final_loss, 5), "profiles": len(classes), "sessions": len(rows)}
