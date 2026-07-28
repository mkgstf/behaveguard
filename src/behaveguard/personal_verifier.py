from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from functools import lru_cache
from statistics import median
from typing import Any

import numpy as np
import torch
from sklearn.metrics import balanced_accuracy_score, roc_auc_score, roc_curve
from sklearn.preprocessing import RobustScaler

from .config import (
    PERSONAL_NEURAL_DIR,
    PERSONAL_NEURAL_PATH,
    PERSONAL_NEURAL_REPORT_PATH,
    ensure_directories,
)
from .database import all_training_rows, get_profile_by_label
from .experiments import window_session
from .features import extract_features, feature_vector
from .neural import NEURAL_FORMAT_VERSION, BehavioralSequenceNet, session_sequences


def personal_folds(rows: list[dict[str, Any]], target_profile_id: str) -> list[dict[str, Any]]:
    genuine = [row for row in rows if row["profile_id"] == target_profile_id]
    impostors = [row for row in rows if row["profile_id"] != target_profile_id]
    if len(genuine) < 3:
        raise ValueError("Personal verification needs at least three independent genuine sessions")
    if len({row["profile_id"] for row in impostors}) < 4:
        raise ValueError("Personal verification needs at least four distinct impostor identities")
    impostors = sorted(impostors, key=lambda row: (row["profile_id"], row["id"]))
    folds = []
    for index, held_genuine in enumerate(genuine):
        held_impostors = impostors[index::len(genuine)]
        held_ids = {row["id"] for row in [held_genuine, *held_impostors]}
        folds.append({
            "index": index + 1,
            "train": [row for row in rows if row["id"] not in held_ids],
            "test_genuine": held_genuine,
            "test_impostors": held_impostors,
        })
    return folds


def _window_rows(rows: list[dict[str, Any]], target_profile_id: str, window_count: int) -> list[dict[str, Any]]:
    examples = []
    for row in rows:
        for window_index in range(window_count):
            payload = window_session(row["payload"], window_index, window_count)
            examples.append({
                "parent_id": row["id"],
                "target": int(row["profile_id"] == target_profile_id),
                "payload": payload,
                "features": extract_features(payload),
            })
    return examples


def _tensors(examples: list[dict[str, Any]], names: list[str], scaler: RobustScaler):
    keyboards, mice, vectors, targets = [], [], [], []
    for example in examples:
        keyboard, mouse = session_sequences(example["payload"], key_length=160, mouse_length=256)
        keyboards.append(keyboard)
        mice.append(mouse)
        vectors.append(scaler.transform(feature_vector(example["features"], names).reshape(1, -1))[0])
        targets.append(example["target"])
    return (
        torch.tensor(np.asarray(keyboards), dtype=torch.float32),
        torch.tensor(np.asarray(mice), dtype=torch.float32),
        torch.tensor(np.asarray(vectors), dtype=torch.float32),
        torch.tensor(targets, dtype=torch.long),
    )


def _train_model(examples: list[dict[str, Any]], epochs: int, seed: int):
    torch.manual_seed(seed)
    np.random.seed(seed)
    names = sorted({name for example in examples for name in example["features"]})
    matrix = np.vstack([feature_vector(example["features"], names) for example in examples])
    scaler = RobustScaler(quantile_range=(10, 90)).fit(matrix)
    keyboard, mouse, vectors, targets = _tensors(examples, names, scaler)
    model = BehavioralSequenceNet(len(names), 2)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1.5e-3, weight_decay=3e-3)
    counts = torch.bincount(targets, minlength=2).float()
    weights = targets.numel() / (2 * counts.clamp_min(1))
    history = []
    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        _, logits = model(keyboard, mouse, vectors)
        loss = torch.nn.functional.cross_entropy(logits, targets, weight=weights, label_smoothing=0.04)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 3.0)
        optimizer.step()
        history.append(round(float(loss.detach()), 5))
    return model, scaler, names, history


def _score_payload(model, scaler, names: list[str], payload: dict[str, Any], window_count: int) -> float:
    examples = []
    for window_index in range(window_count):
        window = window_session(payload, window_index, window_count)
        examples.append({"payload": window, "features": extract_features(window), "target": 0})
    keyboard, mouse, vectors, _ = _tensors(examples, names, scaler)
    model.eval()
    with torch.no_grad():
        _, logits = model(keyboard, mouse, vectors)
        probabilities = torch.softmax(logits, dim=1)[:, 1].cpu().numpy()
    return float(np.mean(probabilities))


def _threshold(genuine: list[float], impostor: list[float]) -> float:
    values = sorted(set([*genuine, *impostor]))
    candidates = [0.5] if len(values) < 2 else [(left + right) / 2 for left, right in zip(values, values[1:])]
    labels = np.asarray([1] * len(genuine) + [0] * len(impostor))
    scores = np.asarray([*genuine, *impostor])
    return float(max(candidates, key=lambda value: balanced_accuracy_score(labels, scores >= value)))


def _metric_summary(
    genuine: list[float], impostor: list[float], genuine_thresholds: list[float], impostor_thresholds: list[float]
) -> dict[str, Any]:
    labels = np.asarray([1] * len(genuine) + [0] * len(impostor))
    scores = np.asarray([*genuine, *impostor])
    predictions = np.asarray(
        [score >= threshold for score, threshold in zip(genuine, genuine_thresholds)]
        + [score >= threshold for score, threshold in zip(impostor, impostor_thresholds)]
    )
    fpr, tpr, _ = roc_curve(labels, scores)
    fnr = 1 - tpr
    index = int(np.nanargmin(np.abs(fpr - fnr)))
    false_rejections = int(np.sum(~predictions[:len(genuine)]))
    false_acceptances = int(np.sum(predictions[len(genuine):]))
    return {
        "roc_auc": round(float(roc_auc_score(labels, scores)), 4),
        "eer": round(float((fpr[index] + fnr[index]) / 2), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(labels, predictions)), 4),
        "genuine_acceptance_rate": round(1 - false_rejections / len(genuine), 4),
        "false_rejection_rate": round(false_rejections / len(genuine), 4),
        "false_acceptance_rate": round(false_acceptances / len(impostor), 4),
        "genuine_trials": len(genuine),
        "impostor_trials": len(impostor),
        "false_rejections": false_rejections,
        "false_acceptances": false_acceptances,
    }


def train_personal_verifier(label: str, epochs: int = 25, window_count: int = 4, seed: int = 42) -> dict[str, Any]:
    ensure_directories()
    _migrate_legacy_artifact()
    profile = get_profile_by_label(label)
    rows = all_training_rows()
    folds = personal_folds(rows, profile["id"])
    fold_reports = []
    genuine_scores: list[float] = []
    impostor_scores: list[float] = []
    thresholds: list[float] = []
    impostor_thresholds: list[float] = []
    for fold in folds:
        examples = _window_rows(fold["train"], profile["id"], window_count)
        model, scaler, names, history = _train_model(examples, epochs, seed + fold["index"])
        training_genuine = [
            _score_payload(model, scaler, names, row["payload"], window_count)
            for row in fold["train"] if row["profile_id"] == profile["id"]
        ]
        training_impostor = [
            _score_payload(model, scaler, names, row["payload"], window_count)
            for row in fold["train"] if row["profile_id"] != profile["id"]
        ]
        threshold = _threshold(training_genuine, training_impostor)
        genuine_score = _score_payload(model, scaler, names, fold["test_genuine"]["payload"], window_count)
        fold_impostors = [
            {
                "profile_id": row["profile_id"], "label": row["label"],
                "score": _score_payload(model, scaler, names, row["payload"], window_count),
            }
            for row in fold["test_impostors"]
        ]
        genuine_scores.append(genuine_score)
        impostor_scores.extend(row["score"] for row in fold_impostors)
        thresholds.append(threshold)
        impostor_thresholds.extend([threshold] * len(fold_impostors))
        fold_reports.append({
            "fold": fold["index"], "held_genuine_session": fold["test_genuine"]["id"],
            "train_sessions": len(fold["train"]), "threshold": round(threshold, 4),
            "genuine_score": round(genuine_score, 4), "genuine_accepted": genuine_score >= threshold,
            "impostors": [{**row, "score": round(row["score"], 4), "accepted": row["score"] >= threshold} for row in fold_impostors],
            "final_loss": history[-1],
        })
    metrics = _metric_summary(genuine_scores, impostor_scores, thresholds, impostor_thresholds)
    final_examples = _window_rows(rows, profile["id"], window_count)
    final_model, final_scaler, final_names, final_history = _train_model(final_examples, epochs, seed + 100)
    operating_threshold = float(median(thresholds))
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "validity": "development_only_personal_leave_one_session_out",
        "warning": (
            f"Only {len(genuine_scores)} genuine and {len(impostor_scores)} impostor trials are available; "
            "rates have very wide uncertainty."
        ),
        "target_profile_id": profile["id"], "target_label": profile["label"],
        "genuine_sessions": len([row for row in rows if row["profile_id"] == profile["id"]]),
        "impostor_identities": len({row["profile_id"] for row in rows if row["profile_id"] != profile["id"]}),
        "window_count": window_count, "epochs": epochs,
        "operating_threshold": round(operating_threshold, 4),
        "metrics": metrics, "folds": fold_reports,
        "genuine_scores": [round(score, 4) for score in genuine_scores],
        "impostor_scores": [round(score, 4) for score in impostor_scores],
    }
    artifact_path = _artifact_path(profile["id"])
    report_path = _report_path(profile["id"])
    torch.save({
        "format_version": NEURAL_FORMAT_VERSION,
        "state_dict": copy.deepcopy(final_model.state_dict()), "feature_names": final_names,
        "scaler": {"center": final_scaler.center_.tolist(), "scale": final_scaler.scale_.tolist()},
        "target_profile_id": profile["id"], "target_label": profile["label"],
        "window_count": window_count, "threshold": operating_threshold,
        "epochs": epochs, "final_loss": final_history[-1], "report": report,
    }, artifact_path)
    report_path.write_text(json.dumps(report, indent=2))
    _load_personal_artifact.cache_clear()
    return report


def score_personal_verifier(payload: dict[str, Any], profile_id: str) -> dict[str, Any] | None:
    path = _artifact_path(profile_id)
    if not path.exists():
        _migrate_legacy_artifact()
    if not path.exists():
        return None
    try:
        artifact, model, scaler = _load_personal_artifact(
            str(path), path.stat().st_mtime
        )
    except (KeyError, RuntimeError, ValueError, OSError):
        return None
    if artifact["target_profile_id"] != profile_id:
        return None
    names = artifact["feature_names"]
    probability = _score_payload(model, scaler, names, payload, int(artifact["window_count"]))
    threshold = float(artifact["threshold"])
    return {
        "certainty": round(probability * 100, 1), "threshold": round(threshold * 100, 1),
        "match": probability >= threshold, "target_label": artifact["target_label"],
    }


def _artifact_path(profile_id: str):
    return PERSONAL_NEURAL_DIR / f"{profile_id}.pt"


def _report_path(profile_id: str):
    return PERSONAL_NEURAL_DIR / f"{profile_id}.json"


def _migrate_legacy_artifact() -> None:
    """Preserve the original single-profile artifact when upgrading storage."""
    if not PERSONAL_NEURAL_PATH.exists():
        return
    artifact = torch.load(PERSONAL_NEURAL_PATH, map_location="cpu", weights_only=False)
    profile_id = str(artifact["target_profile_id"])
    destination = _artifact_path(profile_id)
    if not destination.exists():
        destination.write_bytes(PERSONAL_NEURAL_PATH.read_bytes())
    report_destination = _report_path(profile_id)
    if PERSONAL_NEURAL_REPORT_PATH.exists() and not report_destination.exists():
        report_destination.write_bytes(PERSONAL_NEURAL_REPORT_PATH.read_bytes())


@lru_cache(maxsize=16)
def _load_personal_artifact(path_string: str, modified_at: float):
    artifact = torch.load(path_string, map_location="cpu", weights_only=False)
    if artifact.get("format_version") != NEURAL_FORMAT_VERSION:
        raise ValueError("Personal neural checkpoint representation is incompatible")
    names = artifact["feature_names"]
    scaler = RobustScaler()
    scaler.center_ = np.asarray(artifact["scaler"]["center"], dtype=float)
    scaler.scale_ = np.asarray(artifact["scaler"]["scale"], dtype=float)
    scaler.n_features_in_ = len(names)
    model = BehavioralSequenceNet(len(names), 2)
    model.load_state_dict(artifact["state_dict"])
    model.eval()
    return artifact, model, scaler
