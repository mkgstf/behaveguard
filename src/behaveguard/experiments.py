from __future__ import annotations

import copy
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import torch
from sklearn.base import clone
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score, roc_auc_score, roc_curve
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler
from sklearn.svm import SVC

from .config import ARTIFACT_DIR, NEURAL_PATH, ensure_directories
from .database import all_training_rows
from .features import extract_features, feature_vector
from .neural import BehavioralSequenceNet, session_sequences


def _chunk(values: list[Any], index: int, count: int) -> list[Any]:
    start = round(len(values) * index / count)
    end = round(len(values) * (index + 1) / count)
    return values[start:end]


def window_session(session: dict[str, Any], index: int, count: int = 5) -> dict[str, Any]:
    """Create a time-disjoint pseudo-session without copying derived full-session statistics."""
    keyboard = session.get("keyboard") or {}
    mouse = session.get("mouse") or {}
    tracks = []
    for trial in mouse.get("track_trials") or []:
        item = copy.deepcopy(trial)
        item["samples"] = _chunk(item.get("samples") or [], index, count)
        item["derived"] = {}
        tracks.append(item)
    return {
        "collected_at": session.get("collected_at"),
        "duration_ms": float(session.get("duration_ms", 0)) / count,
        "keyboard": {
            "events": _chunk(keyboard.get("events") or [], index, count),
            "pangram_text_length": 0, "free_text_length": 0, "extras": {},
        },
        "mouse": {
            "passive_points": _chunk(mouse.get("passive_points") or [], index, count),
            "dot_trials": _chunk(mouse.get("dot_trials") or [], index, count),
            "drag_trials": _chunk(mouse.get("drag_trials") or [], index, count),
            "track_trials": tracks,
        },
        "context": {"experimental_window": index, "window_count": count},
    }


def build_window_dataset(window_count: int = 5):
    rows = all_training_rows()
    windows = []
    for row in rows:
        for index in range(window_count):
            session = window_session(row["payload"], index, window_count)
            windows.append({
                "profile_id": row["profile_id"], "label": row["label"], "fold": index,
                "session": session, "features": extract_features(session),
            })
    names = sorted({name for row in windows for name in row["features"]})
    matrix = np.vstack([feature_vector(row["features"], names) for row in windows])
    labels = np.asarray([row["profile_id"] for row in windows])
    folds = np.asarray([row["fold"] for row in windows])
    return rows, windows, names, matrix, labels, folds


def _decision_matrix(model, matrix: np.ndarray, classes: np.ndarray) -> np.ndarray:
    decision = np.asarray(model.decision_function(matrix))
    if len(classes) == 2 and decision.ndim == 1:
        decision = np.column_stack([-decision, decision])
    return decision


def evaluate_model(estimator, matrix: np.ndarray, labels: np.ndarray, folds: np.ndarray) -> dict[str, Any]:
    predictions = np.empty(labels.shape, dtype=object)
    score_rows = np.zeros((len(labels), len(np.unique(labels))), dtype=float)
    classes = np.asarray(sorted(set(labels)))
    for fold in sorted(set(folds)):
        train = folds != fold
        test = folds == fold
        model = clone(estimator).fit(matrix[train], labels[train])
        predictions[test] = model.predict(matrix[test])
        if hasattr(model, "decision_function"):
            model_classes = model.classes_
            decision = _decision_matrix(model, matrix[test], model_classes)
        else:
            model_classes = model.classes_
            decision = model.predict_proba(matrix[test])
        for local_index, class_id in enumerate(model_classes):
            score_rows[np.where(test)[0], np.where(classes == class_id)[0][0]] = decision[:, local_index]
    top3 = np.argsort(score_rows, axis=1)[:, -3:]
    targets = np.asarray([np.where(classes == label)[0][0] for label in labels])
    top3_accuracy = float(np.mean([target in choices for target, choices in zip(targets, top3)]))
    genuine, score = [], []
    for row_index, target in enumerate(targets):
        for class_index in range(len(classes)):
            genuine.append(int(class_index == target))
            score.append(float(score_rows[row_index, class_index]))
    fpr, tpr, thresholds = roc_curve(genuine, score)
    fnr = 1 - tpr
    eer_index = int(np.nanargmin(np.abs(fpr - fnr)))
    return {
        "accuracy": round(float(accuracy_score(labels, predictions)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(labels, predictions)), 4),
        "macro_f1": round(float(f1_score(labels, predictions, average="macro")), 4),
        "top3_accuracy": round(top3_accuracy, 4),
        "verification_auc": round(float(roc_auc_score(genuine, score)), 4),
        "eer": round(float((fpr[eer_index] + fnr[eer_index]) / 2), 4),
        "eer_threshold": round(float(thresholds[eer_index]), 4),
        "confusion_matrix": confusion_matrix(labels, predictions, labels=classes).tolist(),
    }


def _profile_similarity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    names = sorted({name for row in rows for name in row["features"]})
    matrix = np.vstack([feature_vector(row["features"], names) for row in rows])
    matrix = RobustScaler(quantile_range=(10, 90)).fit_transform(matrix)
    profile_ids = sorted({row["profile_id"] for row in rows})
    labels = []
    centroids = []
    for profile_id in profile_ids:
        indexes = [index for index, row in enumerate(rows) if row["profile_id"] == profile_id]
        labels.append(rows[indexes[0]]["label"])
        centroids.append(matrix[indexes].mean(axis=0))
    matrix = np.vstack(centroids)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normalized = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms != 0)
    similarity = ((normalized @ normalized.T) + 1) * 50
    return {
        "labels": labels,
        "matrix": np.round(similarity, 2).tolist(),
        "closest_impostors": [
            {
                "profile": labels[index],
                "closest": labels[int(np.argmax(np.where(np.arange(len(labels)) == index, -np.inf, similarity[index])))],
                "similarity": round(float(np.max(np.where(np.arange(len(labels)) == index, -np.inf, similarity[index]))), 2),
            }
            for index in range(len(labels))
        ],
    }


def train_neural_windows(windows, names, matrix, labels, folds, epochs: int = 25, seed: int = 42) -> dict[str, Any]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    classes = np.asarray(sorted(set(labels)))
    class_index = {value: index for index, value in enumerate(classes)}
    scaler = RobustScaler(quantile_range=(10, 90)).fit(matrix[folds != folds.max()])
    scaled = scaler.transform(matrix).astype(np.float32)
    keyboards, mice = [], []
    for row in windows:
        keyboard, mouse = session_sequences(row["session"], key_length=160, mouse_length=256)
        keyboards.append(keyboard)
        mice.append(mouse)
    keyboard_tensor = torch.tensor(np.asarray(keyboards), dtype=torch.float32)
    mouse_tensor = torch.tensor(np.asarray(mice), dtype=torch.float32)
    feature_tensor = torch.tensor(scaled, dtype=torch.float32)
    targets = torch.tensor([class_index[value] for value in labels], dtype=torch.long)
    train_mask = torch.tensor(folds != folds.max())
    validation_mask = ~train_mask
    model = BehavioralSequenceNet(len(names), len(classes))
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=2e-3)
    best_accuracy = -1.0
    best_state = None
    history = []
    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        _, logits = model(keyboard_tensor[train_mask], mouse_tensor[train_mask], feature_tensor[train_mask])
        loss = torch.nn.functional.cross_entropy(logits, targets[train_mask], label_smoothing=0.05)
        loss.backward()
        optimizer.step()
        model.eval()
        with torch.no_grad():
            _, validation_logits = model(keyboard_tensor[validation_mask], mouse_tensor[validation_mask], feature_tensor[validation_mask])
            accuracy = float((validation_logits.argmax(dim=1) == targets[validation_mask]).float().mean())
        history.append({"epoch": epoch + 1, "loss": round(float(loss.detach()), 5), "validation_accuracy": round(accuracy, 4)})
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
    ensure_directories()
    torch.save({
        "state_dict": best_state, "classes": classes.tolist(), "feature_names": names,
        "scaler": {"center": scaler.center_.tolist(), "scale": scaler.scale_.tolist()},
        "experimental": True, "window_count": len(set(folds)), "validation_fold": int(folds.max()),
        "validation_accuracy": best_accuracy, "history": history,
    }, NEURAL_PATH)
    return {"trained": True, "experimental": True, "epochs": epochs, "best_validation_accuracy": round(best_accuracy, 4), "final_loss": history[-1]["loss"]}


def run_experiments(window_count: int = 5, neural_epochs: int = 25) -> dict[str, Any]:
    ensure_directories()
    rows, windows, names, matrix, labels, folds = build_window_dataset(window_count)
    if len(set(labels)) < 2:
        raise ValueError("At least two profiles are required")
    candidates: dict[str, Any] = {
        "logistic_regression": make_pipeline(RobustScaler(), LogisticRegression(C=1, max_iter=3000, class_weight="balanced")),
        "knn_3": make_pipeline(RobustScaler(), KNeighborsClassifier(n_neighbors=3, weights="distance")),
        "random_forest": RandomForestClassifier(n_estimators=350, min_samples_leaf=2, class_weight="balanced", random_state=42, n_jobs=-1),
        "extra_trees": ExtraTreesClassifier(n_estimators=350, min_samples_leaf=2, class_weight="balanced", random_state=42, n_jobs=-1),
    }
    for c_value in (0.1, 1.0, 10.0, 50.0):
        for gamma in ("scale", 0.001, 0.01, 0.1):
            candidates[f"svm_C{c_value}_g{gamma}"] = make_pipeline(
                RobustScaler(quantile_range=(10, 90)),
                SVC(kernel="rbf", C=c_value, gamma=gamma, class_weight="balanced", decision_function_shape="ovr"),
            )
    results = {}
    for name, estimator in candidates.items():
        results[name] = evaluate_model(estimator, matrix, labels, folds)
    best_name = max(results, key=lambda name: (results[name]["balanced_accuracy"], results[name]["verification_auc"]))
    best_estimator = candidates[best_name]
    best_estimator.fit(matrix, labels)
    joblib.dump({"model": best_estimator, "feature_names": names, "experimental": True}, ARTIFACT_DIR / "benchmark_model.joblib")

    svm_names = [name for name in candidates if name.startswith("svm_")]
    best_svm_name = max(svm_names, key=lambda name: (results[name]["balanced_accuracy"], results[name]["verification_auc"]))
    best_svm = candidates[best_svm_name][-1]
    tuned = {"C": best_svm.C, "gamma": best_svm.gamma, "verification_threshold": 62.0}
    (ARTIFACT_DIR / "tuned_config.json").write_text(json.dumps({"svm": tuned}, indent=2))

    ablations = {}
    for label, selected in {
        "keyboard_only": [index for index, name in enumerate(names) if name.startswith("key_")],
        "mouse_only": [index for index, name in enumerate(names) if not name.startswith("key_")],
        "full_multimodal": list(range(len(names))),
    }.items():
        ablations[label] = evaluate_model(candidates[best_svm_name], matrix[:, selected], labels, folds)

    neural = train_neural_windows(windows, names, matrix, labels, folds, epochs=neural_epochs)
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "validity": "development_only_within_session_windows",
        "warning": "All windows from a person originate from one real session; results cannot estimate cross-day production accuracy.",
        "dataset": {"real_sessions": len(rows), "profiles": len(set(labels)), "windows": len(windows), "windows_per_session": window_count, "features": len(names), "class_counts": Counter(labels)},
        "best_model": best_name, "best_metrics": results[best_name], "best_svm": best_svm_name,
        "tuned_svm": tuned, "all_models": results, "ablations": ablations,
        "profile_similarity": _profile_similarity(rows), "neural": neural,
    }
    path = ARTIFACT_DIR / "experiment_report.json"
    path.write_text(json.dumps(report, indent=2, default=lambda value: dict(value)))
    return report
