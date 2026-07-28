from __future__ import annotations

import copy
from collections import Counter, defaultdict
from typing import Any

import numpy as np
import torch
from sklearn.metrics import balanced_accuracy_score, f1_score
from sklearn.preprocessing import RobustScaler
from torch import nn

from .config import ARTIFACT_DIR, NEURAL_PATH, ensure_directories
from .database import (
    all_training_rows,
    create_model_version,
    get_active_model_version,
    promote_model_version,
    session_scope,
)
from .db.models import ModelVersion
from .features import feature_vector
from .neural import BehavioralSequenceNet, session_sequences


MIN_SESSIONS_PER_NEURAL_PROFILE = 2
MIN_NEURAL_PROFILES = 2
MIN_NEURAL_SESSIONS = 6


def _eligible_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep identities for which sequence learning has repeated evidence.

    A one-session identity cannot contribute an independent example of how
    that person's behaviour varies. It stays available to the classical
    centroid/SVM model, but is deliberately excluded from the neural class
    set until another session is enrolled.
    """
    counts = Counter(row["profile_id"] for row in rows)
    eligible = {
        profile_id
        for profile_id, count in counts.items()
        if count >= MIN_SESSIONS_PER_NEURAL_PROFILE
    }
    return [row for row in rows if row["profile_id"] in eligible]


def _training_requirement(rows: list[dict[str, Any]]) -> str | None:
    counts = Counter(row["profile_id"] for row in rows)
    if len(counts) < MIN_NEURAL_PROFILES or len(rows) < MIN_NEURAL_SESSIONS:
        return (
            "Need at least two profiles with two independent sessions each "
            "and six eligible sessions total"
        )
    return None


def _feature_names(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({name for row in rows for name in row["features"]})


def _fit_scaler(rows: list[dict[str, Any]], names: list[str]) -> RobustScaler:
    matrix = np.vstack([feature_vector(row["features"], names) for row in rows])
    return RobustScaler(quantile_range=(10, 90)).fit(matrix)


def _scaler_payload(scaler: RobustScaler) -> dict[str, list[float]]:
    return {
        "center": np.asarray(scaler.center_, dtype=float).tolist(),
        "scale": np.asarray(scaler.scale_, dtype=float).tolist(),
    }


def _scaler_from_payload(payload: dict[str, Any], feature_count: int) -> RobustScaler:
    scaler = RobustScaler()
    scaler.center_ = np.asarray(payload["center"], dtype=float)
    scaler.scale_ = np.asarray(payload["scale"], dtype=float)
    scaler.n_features_in_ = feature_count
    return scaler


def _build_tensors(
    rows: list[dict[str, Any]],
    names: list[str],
    scaler: RobustScaler,
    class_index: dict[str, int],
):
    keyboards, mice, vectors, targets = [], [], [], []
    for row in rows:
        keyboard, mouse = session_sequences(row["payload"])
        keyboards.append(keyboard)
        mice.append(mouse)
        vectors.append(
            scaler.transform(feature_vector(row["features"], names).reshape(1, -1))[0]
        )
        targets.append(class_index[row["profile_id"]])
    tensors = [
        torch.tensor(np.asarray(values), dtype=torch.float32)
        for values in (keyboards, mice, vectors)
    ]
    return tensors, torch.tensor(targets, dtype=torch.long)


def _fit_network(
    tensors,
    targets: torch.Tensor,
    feature_count: int,
    class_count: int,
    epochs: int,
    validation=None,
    patience: int = 6,
) -> tuple[BehavioralSequenceNet, dict[str, Any]]:
    model = BehavioralSequenceNet(feature_count, class_count)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-3)
    counts = torch.bincount(targets, minlength=class_count).float()
    class_weights = targets.numel() / (class_count * counts.clamp_min(1))
    final_loss = 0.0
    best_state = None
    best_key = None
    best_epoch = epochs
    epochs_without_improvement = 0
    history = []
    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        _, logits = model(*tensors)
        loss = nn.functional.cross_entropy(
            logits,
            targets,
            weight=class_weights,
            label_smoothing=0.03,
        )
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 3.0)
        optimizer.step()
        final_loss = float(loss.detach())
        row = {"epoch": epoch + 1, "training_loss": round(final_loss, 6)}
        if validation is not None:
            validation_tensors, validation_targets = validation
            metrics = _classification_metrics(
                model, validation_tensors, validation_targets
            )
            row.update({f"validation_{key}": value for key, value in metrics.items()})
            key = (
                metrics["balanced_accuracy"],
                metrics["macro_f1"],
                -metrics["nll"],
            )
            if best_key is None or key > best_key:
                best_key = key
                best_state = copy.deepcopy(model.state_dict())
                best_epoch = epoch + 1
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1
            if epoch >= 4 and epochs_without_improvement >= patience:
                history.append(row)
                break
        history.append(row)
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, {
        "loss": final_loss,
        "best_epoch": best_epoch,
        "epochs_ran": len(history),
        "history": history,
    }


def _checkpoint(
    model: BehavioralSequenceNet,
    classes: list[str],
    names: list[str],
    scaler: RobustScaler,
    training: dict[str, Any],
    rows: list[dict[str, Any]],
    temperature: float = 1.0,
) -> dict[str, Any]:
    return {
        "format_version": 2,
        "state_dict": copy.deepcopy(model.state_dict()),
        "classes": classes,
        "feature_names": names,
        "scaler": _scaler_payload(scaler),
        "loss": training["loss"],
        "best_epoch": training["best_epoch"],
        "epochs_ran": training["epochs_ran"],
        "temperature": temperature,
        "trained_session_ids": [row["id"] for row in rows],
    }


def _train_checkpoint(
    rows: list[dict[str, Any]],
    epochs: int,
    validation_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], BehavioralSequenceNet]:
    names = _feature_names(rows)
    classes = sorted({row["profile_id"] for row in rows})
    class_index = {value: index for index, value in enumerate(classes)}
    scaler = _fit_scaler(rows, names)
    tensors, targets = _build_tensors(rows, names, scaler, class_index)
    validation = None
    if validation_rows:
        validation = _build_tensors(
            validation_rows, names, scaler, class_index
        )
    model, training = _fit_network(
        tensors,
        targets,
        len(names),
        len(classes),
        epochs,
        validation=validation,
    )
    temperature = 1.0
    if validation is not None:
        temperature = _fit_temperature(model, *validation)
    return (
        _checkpoint(
            model, classes, names, scaler, training, rows,
            temperature=temperature,
        ),
        model,
    )


def train_neural(epochs: int = 30, seed: int = 42) -> dict:
    torch.manual_seed(seed)
    np.random.seed(seed)
    rows = _eligible_rows(all_training_rows())
    requirement = _training_requirement(rows)
    if requirement:
        return {"trained": False, "reason": requirement}

    checkpoint, _ = _train_checkpoint(rows, epochs)
    ensure_directories()
    torch.save(checkpoint, NEURAL_PATH)
    return {
        "trained": True,
        "epochs": epochs,
        "loss": round(float(checkpoint["loss"]), 5),
        "profiles": len(checkpoint["classes"]),
        "sessions": len(rows),
        "excluded_single_session_profiles": len(
            {row["profile_id"] for row in all_training_rows()}
            - set(checkpoint["classes"])
        ),
    }


def _split_holdout(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Hold out the newest complete session for every identity with 3+."""
    by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_profile[row["profile_id"]].append(row)
    train_rows, holdout_rows = [], []
    for profile_rows in by_profile.values():
        ordered = sorted(
            profile_rows,
            key=lambda row: (str(row["collected_at"]), str(row["id"])),
        )
        if len(ordered) >= 3:
            holdout_rows.append(ordered[-1])
            train_rows.extend(ordered[:-1])
        else:
            train_rows.extend(ordered)
    return train_rows, holdout_rows


def _classification_metrics(
    model: BehavioralSequenceNet,
    tensors,
    targets: torch.Tensor,
    temperature: float = 1.0,
) -> dict[str, float]:
    model.eval()
    with torch.no_grad():
        _, logits = model(*tensors)
        logits = logits / max(float(temperature), 1e-3)
        predictions = logits.argmax(dim=1)
        nll = float(nn.functional.cross_entropy(logits, targets))
    true = targets.cpu().numpy()
    predicted = predictions.cpu().numpy()
    return {
        "accuracy": round(float(np.mean(true == predicted)), 6),
        "balanced_accuracy": round(
            float(balanced_accuracy_score(true, predicted)), 6
        ),
        "macro_f1": round(
            float(f1_score(true, predicted, average="macro", zero_division=0)),
            6,
        ),
        "nll": round(nll, 6),
    }


def _fit_temperature(
    model: BehavioralSequenceNet,
    tensors,
    targets: torch.Tensor,
) -> float:
    model.eval()
    with torch.no_grad():
        _, logits = model(*tensors)
        candidates = np.geomspace(0.5, 5.0, 41)
        losses = [
            float(nn.functional.cross_entropy(logits / float(value), targets))
            for value in candidates
        ]
    return round(float(candidates[int(np.argmin(losses))]), 6)


def _evaluate_checkpoint(
    checkpoint: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, float]:
    names = list(checkpoint["feature_names"])
    classes = [str(value) for value in checkpoint["classes"]]
    class_index = {value: index for index, value in enumerate(classes)}
    if not rows or any(row["profile_id"] not in class_index for row in rows):
        raise ValueError("Evaluation rows contain a class absent from the checkpoint")
    scaler = _scaler_from_payload(checkpoint["scaler"], len(names))
    tensors, targets = _build_tensors(rows, names, scaler, class_index)
    model = BehavioralSequenceNet(len(names), len(classes))
    model.load_state_dict(checkpoint["state_dict"])
    return _classification_metrics(
        model,
        tensors,
        targets,
        temperature=float(checkpoint.get("temperature", 1.0)),
    )


def _should_promote(
    candidate: dict[str, float],
    baseline: dict[str, float] | None,
) -> bool:
    if baseline is None:
        return True
    candidate_key = (
        candidate["balanced_accuracy"],
        candidate["macro_f1"],
        -candidate["nll"],
    )
    baseline_key = (
        baseline["balanced_accuracy"],
        baseline["macro_f1"],
        -baseline["nll"],
    )
    return candidate_key >= baseline_key


def train_neural_and_promote(epochs: int = 30, seed: int = 42) -> dict:
    """Train leakage-safe candidate, evaluate it, and gate promotion.

    Validation preprocessing is fit exclusively on the training partition.
    If the candidate is promoted, a deployment copy is refit on every
    eligible session after the promotion decision so no enrollment evidence
    is wasted in the live artifact.
    """
    torch.manual_seed(seed)
    np.random.seed(seed)
    all_rows = all_training_rows()
    rows = _eligible_rows(all_rows)
    requirement = _training_requirement(rows)
    if requirement:
        return {"trained": False, "promoted": False, "reason": requirement}

    train_rows, holdout_rows = _split_holdout(rows)
    validation_checkpoint, validation_model = _train_checkpoint(
        train_rows, epochs, validation_rows=holdout_rows
    )
    holdout_metrics = None
    if holdout_rows:
        names = validation_checkpoint["feature_names"]
        classes = validation_checkpoint["classes"]
        scaler = _scaler_from_payload(validation_checkpoint["scaler"], len(names))
        class_index = {value: index for index, value in enumerate(classes)}
        holdout_tensors, holdout_targets = _build_tensors(
            holdout_rows, names, scaler, class_index
        )
        holdout_metrics = _classification_metrics(
            validation_model,
            holdout_tensors,
            holdout_targets,
            temperature=float(validation_checkpoint.get("temperature", 1.0)),
        )

    baseline_metrics = None
    active_version = get_active_model_version("neural")
    if active_version and holdout_rows:
        try:
            baseline_checkpoint = torch.load(
                active_version["artifact_uri"], map_location="cpu", weights_only=False
            )
            if set(map(str, baseline_checkpoint["classes"])) == set(
                validation_checkpoint["classes"]
            ):
                baseline_metrics = _evaluate_checkpoint(
                    baseline_checkpoint, holdout_rows
                )
        except (FileNotFoundError, RuntimeError, KeyError, ValueError):
            baseline_metrics = None

    promote = (
        True
        if holdout_metrics is None
        else _should_promote(holdout_metrics, baseline_metrics)
    )

    ensure_directories()
    candidates_dir = ARTIFACT_DIR / "neural_candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    metrics = {
        "loss": round(float(validation_checkpoint["loss"]), 5),
        "epochs": epochs,
        "sessions": len(rows),
        "train_sessions": len(train_rows),
        "holdout_sessions": len(holdout_rows),
        "holdout_accuracy": (
            holdout_metrics["accuracy"] if holdout_metrics else None
        ),
        "holdout_metrics": holdout_metrics,
        "baseline_accuracy": (
            baseline_metrics["accuracy"] if baseline_metrics else None
        ),
        "baseline_metrics": baseline_metrics,
        "classes": validation_checkpoint["classes"],
        "best_epoch": validation_checkpoint["best_epoch"],
        "epochs_ran": validation_checkpoint["epochs_ran"],
        "temperature": validation_checkpoint["temperature"],
        "excluded_single_session_profiles": len(
            {row["profile_id"] for row in all_rows}
            - set(validation_checkpoint["classes"])
        ),
        "validation_preprocessing": "train_partition_only",
    }

    version = create_model_version(
        kind="neural",
        artifact_uri=None,
        metrics=metrics,
        status="candidate",
        dataset_fingerprint=(
            f"sessions={len(rows)}:profiles={len(validation_checkpoint['classes'])}"
        ),
    )
    candidate_path = candidates_dir / f"{version['id']}.pt"
    torch.save(validation_checkpoint, candidate_path)

    with session_scope() as session:
        row = session.get(ModelVersion, version["id"])
        row.artifact_uri = str(candidate_path)

    if promote:
        deployment_checkpoint, _ = _train_checkpoint(
            rows, int(validation_checkpoint["best_epoch"])
        )
        deployment_checkpoint["temperature"] = validation_checkpoint["temperature"]
        torch.save(deployment_checkpoint, candidate_path)
        torch.save(deployment_checkpoint, NEURAL_PATH)
        promote_model_version(version["id"])

    return {
        "trained": True,
        "promoted": promote,
        "model_version_id": version["id"],
        "holdout_accuracy": metrics["holdout_accuracy"],
        "holdout_metrics": holdout_metrics,
        "baseline_accuracy": metrics["baseline_accuracy"],
        "baseline_metrics": baseline_metrics,
        "loss": metrics["loss"],
        "best_epoch": metrics["best_epoch"],
        "epochs_ran": metrics["epochs_ran"],
        "temperature": metrics["temperature"],
        "profiles": len(validation_checkpoint["classes"]),
        "sessions": len(rows),
        "excluded_single_session_profiles": metrics[
            "excluded_single_session_profiles"
        ],
    }
