from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
import torch
from torch import nn

from .config import ARTIFACT_DIR, NEURAL_PATH, ensure_directories
from .database import all_training_rows, create_model_version, get_active_model_version, promote_model_version, session_scope
from .db.models import ModelVersion
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


def _split_holdout(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Holds out the most recent session for any profile with >=3 sessions
    (enough left to still train on), leaving profiles with fewer sessions
    entirely in the training split — they still contribute to what the
    model learns, they just can't be part of the held-out accuracy check."""
    by_profile: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_profile[row["profile_id"]].append(row)
    train_rows, holdout_rows = [], []
    for profile_rows in by_profile.values():
        if len(profile_rows) >= 3:
            ordered = sorted(profile_rows, key=lambda row: row["collected_at"])
            holdout_rows.append(ordered[-1])
            train_rows.extend(ordered[:-1])
        else:
            train_rows.extend(profile_rows)
    return train_rows, holdout_rows


def _build_tensors(rows: list[dict], names: list[str], scaler, class_index: dict[str, int]):
    keyboards, mice, vectors, targets = [], [], [], []
    for row in rows:
        keyboard, mouse = session_sequences(row["payload"])
        keyboards.append(keyboard)
        mice.append(mouse)
        vectors.append(scaler.transform(feature_vector(row["features"], names).reshape(1, -1))[0])
        targets.append(class_index[row["profile_id"]])
    tensors = [torch.tensor(np.asarray(values), dtype=torch.float32) for values in (keyboards, mice, vectors)]
    return tensors, torch.tensor(targets, dtype=torch.long)


def _evaluate_accuracy(model: BehavioralSequenceNet, tensors, targets: torch.Tensor) -> float:
    model.eval()
    with torch.no_grad():
        _, logits = model(*tensors)
        predictions = logits.argmax(dim=1)
        return float((predictions == targets).float().mean())


def train_neural_and_promote(epochs: int = 30, seed: int = 42) -> dict:
    """The promotion-gated counterpart to `train_neural`: trains a candidate
    on a held-out split, evaluates it, and only overwrites the live
    `NEURAL_PATH` artifact (what `modeling.score_session` actually reads) if
    the candidate is at least as good as whatever is currently active — per
    the Phase 3 design, a worse retrain is recorded as a non-promoted
    'candidate' in `model_versions` rather than silently replacing a working
    model. This is what the async worker calls; `train_neural` above is kept
    for the synchronous CLI/manual-training path where a promotion gate
    would be unnecessary friction (e.g. `behaveguard train`, or evaluating
    ideas by hand).
    """
    torch.manual_seed(seed)
    np.random.seed(seed)
    rows = all_training_rows()
    counts = Counter(row["profile_id"] for row in rows)
    if len(counts) < 2 or min(counts.values(), default=0) < 2 or len(rows) < 6:
        return {"trained": False, "promoted": False, "reason": "Need at least two profiles, two independent sessions each, and six sessions total"}

    artifact = load_model()
    names = artifact["feature_names"]
    classes = sorted(counts)
    class_index = {value: index for index, value in enumerate(classes)}

    train_rows, holdout_rows = _split_holdout(rows)
    train_tensors, train_targets = _build_tensors(train_rows, names, artifact["scaler"], class_index)

    model = BehavioralSequenceNet(len(names), len(classes))
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-3)
    model.train()
    final_loss = 0.0
    for _ in range(epochs):
        optimizer.zero_grad()
        _, logits = model(*train_tensors)
        loss = nn.functional.cross_entropy(logits, train_targets)
        loss.backward()
        optimizer.step()
        final_loss = float(loss.detach())

    holdout_accuracy = None
    if holdout_rows:
        holdout_tensors, holdout_targets = _build_tensors(holdout_rows, names, artifact["scaler"], class_index)
        holdout_accuracy = _evaluate_accuracy(model, holdout_tensors, holdout_targets)

    # Compare against the currently active model, but only if its class set
    # matches exactly — evaluating a model on classes it was never trained
    # to predict isn't a fair comparison, so a class-set change (a profile
    # added/removed/merged since the last promotion) always promotes the
    # new candidate rather than penalizing it for an apples-to-oranges score.
    baseline_accuracy = None
    active_version = get_active_model_version("neural")
    if active_version and active_version.get("metrics", {}).get("classes") == classes and holdout_rows:
        try:
            baseline_state = torch.load(active_version["artifact_uri"], map_location="cpu", weights_only=False)
            baseline_model = BehavioralSequenceNet(len(names), len(classes))
            baseline_model.load_state_dict(baseline_state["state_dict"])
            baseline_accuracy = _evaluate_accuracy(baseline_model, holdout_tensors, holdout_targets)
        except (FileNotFoundError, RuntimeError, KeyError):
            baseline_accuracy = None  # baseline artifact missing/incompatible — treat as no baseline

    promote = baseline_accuracy is None or holdout_accuracy is None or holdout_accuracy >= baseline_accuracy

    ensure_directories()
    candidates_dir = ARTIFACT_DIR / "neural_candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    metrics = {
        "loss": round(final_loss, 5), "epochs": epochs, "sessions": len(rows), "train_sessions": len(train_rows),
        "holdout_sessions": len(holdout_rows), "holdout_accuracy": holdout_accuracy, "baseline_accuracy": baseline_accuracy,
        "classes": classes,
    }

    version = create_model_version(
        kind="neural", artifact_uri=None, metrics=metrics, status="candidate",
        dataset_fingerprint=f"sessions={len(rows)}:profiles={len(classes)}",
    )
    candidate_path = candidates_dir / f"{version['id']}.pt"
    torch.save({"state_dict": model.state_dict(), "classes": classes, "feature_names": names, "loss": final_loss}, candidate_path)

    with session_scope() as session:
        row = session.get(ModelVersion, version["id"])
        row.artifact_uri = str(candidate_path)

    if promote:
        torch.save({"state_dict": model.state_dict(), "classes": classes, "feature_names": names, "loss": final_loss}, NEURAL_PATH)
        promote_model_version(version["id"])

    return {
        "trained": True, "promoted": promote, "model_version_id": version["id"],
        "holdout_accuracy": holdout_accuracy, "baseline_accuracy": baseline_accuracy, "loss": round(final_loss, 5),
    }
