from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
from sklearn.preprocessing import RobustScaler
from sklearn.svm import SVC

from .features import feature_vector


CAPTURE_LENGTH_FEATURES = {"key_count", "passive_count"}


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    denominator = np.linalg.norm(left) * np.linalg.norm(right)
    return float(np.dot(left, right) / denominator) if denominator else 0.0


def select_feature_names(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Drop explicit task-length proxies and features with no observed variance."""
    candidates = sorted(
        {
            name
            for row in rows
            for name in row["features"]
            if name not in CAPTURE_LENGTH_FEATURES
        }
    )
    if not candidates:
        return [], []
    matrix = np.vstack([feature_vector(row["features"], candidates) for row in rows])
    keep_mask = np.ptp(matrix, axis=0) > 1e-12
    selected = [name for name, keep in zip(candidates, keep_mask) if keep]
    dropped = sorted(
        CAPTURE_LENGTH_FEATURES.intersection(
            {name for row in rows for name in row["features"]}
        )
        | {name for name, keep in zip(candidates, keep_mask) if not keep}
    )
    return selected, dropped


def _decision_probabilities(svm: SVC | None, vector: np.ndarray) -> dict[str, float]:
    if svm is None:
        return {}
    decision = np.asarray(svm.decision_function(vector.reshape(1, -1))).reshape(-1)
    if len(svm.classes_) == 2 and decision.size == 1:
        decision = np.asarray([-decision[0], decision[0]])
    decision = np.exp(np.clip(decision - decision.max(), -50, 0))
    decision /= decision.sum()
    return {
        str(label): float(value)
        for label, value in zip(svm.classes_, decision)
    }


def fit_classical_components(
    rows: list[dict[str, Any]],
    names: list[str],
    *,
    c_value: float = 2.0,
    gamma: str | float = "scale",
) -> dict[str, Any]:
    raw = np.vstack([feature_vector(row["features"], names) for row in rows])
    scaler = RobustScaler(quantile_range=(10, 90)).fit(raw)
    matrix = scaler.transform(raw)
    labels = np.asarray([row["profile_id"] for row in rows])
    centroids: dict[str, np.ndarray] = {}
    for profile_id in sorted(set(labels)):
        member = matrix[labels == profile_id]
        centroid = member.mean(axis=0)
        norm = np.linalg.norm(centroid)
        centroids[str(profile_id)] = centroid / norm if norm else centroid
    svm = None
    if len(centroids) >= 2:
        svm = SVC(
            kernel="rbf",
            C=c_value,
            gamma=gamma,
            class_weight="balanced",
            decision_function_shape="ovr",
        ).fit(matrix, labels)
    return {
        "scaler": scaler,
        "centroids": centroids,
        "svm": svm,
        "matrix": matrix,
        "labels": labels,
    }


def score_classical_components(
    features: dict[str, float],
    names: list[str],
    components: dict[str, Any],
) -> dict[str, float]:
    vector = components["scaler"].transform(
        feature_vector(features, names).reshape(1, -1)
    )[0]
    svm_probabilities = _decision_probabilities(components["svm"], vector)
    scores = {}
    for profile_id, centroid in components["centroids"].items():
        cosine = (cosine_similarity(vector, centroid) + 1) / 2
        svm_vote = svm_probabilities.get(profile_id, cosine)
        scores[profile_id] = float(cosine * 0.8 + svm_vote * 0.2)
    return scores


def choose_operating_threshold(
    genuine_scores: list[float],
    impostor_scores: list[float],
    *,
    target_far: float = 0.05,
    fallback: float = 0.62,
) -> dict[str, float]:
    """Choose a FAR-constrained threshold, preferring lower false rejection."""
    if not genuine_scores or not impostor_scores:
        return {
            "threshold": fallback,
            "false_acceptance_rate": 0.0,
            "false_rejection_rate": 0.0,
            "balanced_accuracy": 0.0,
        }
    values = sorted(set([*genuine_scores, *impostor_scores]))
    candidates = [0.0, 1.0]
    candidates.extend(
        (left + right) / 2 for left, right in zip(values, values[1:])
    )
    evaluated = []
    for threshold in sorted(set(candidates)):
        far = float(np.mean(np.asarray(impostor_scores) >= threshold))
        frr = float(np.mean(np.asarray(genuine_scores) < threshold))
        balanced = 1 - (far + frr) / 2
        evaluated.append((threshold, far, frr, balanced))
    constrained = [row for row in evaluated if row[1] <= target_far]
    if constrained:
        threshold, far, frr, balanced = min(
            constrained, key=lambda row: (row[2], row[1], row[0])
        )
    else:
        threshold, far, frr, balanced = min(
            evaluated,
            key=lambda row: (2 * row[1] + row[2], row[1], row[2], -row[0]),
        )
    return {
        "threshold": float(threshold),
        "false_acceptance_rate": far,
        "false_rejection_rate": frr,
        "balanced_accuracy": balanced,
    }


def calibrate_verification(
    rows: list[dict[str, Any]],
    names: list[str],
    *,
    c_value: float = 2.0,
    gamma: str | float = "scale",
    target_far: float = 0.05,
) -> dict[str, Any]:
    """Session-disjoint calibration for verification and open-set rejection."""
    genuine_scores: list[float] = []
    impostor_scores: list[float] = []
    genuine_by_profile: dict[str, list[float]] = defaultdict(list)
    impostor_by_profile: dict[str, list[float]] = defaultdict(list)

    by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_profile[row["profile_id"]].append(row)
    session_fold_count = min(5, max(map(len, by_profile.values()), default=0))
    session_fold_by_id = {}
    for profile_rows in by_profile.values():
        ordered = sorted(
            profile_rows,
            key=lambda row: (str(row.get("collected_at", "")), str(row["id"])),
        )
        for index, row in enumerate(ordered):
            session_fold_by_id[row["id"]] = index % max(session_fold_count, 1)

    for fold in range(session_fold_count):
        held_rows = [
            row for row in rows if session_fold_by_id[row["id"]] == fold
        ]
        train_rows = [
            row for row in rows if session_fold_by_id[row["id"]] != fold
        ]
        if len({row["profile_id"] for row in train_rows}) < 2:
            continue
        components = fit_classical_components(
            train_rows, names, c_value=c_value, gamma=gamma
        )
        for held in held_rows:
            scores = score_classical_components(held["features"], names, components)
            for profile_id, score in scores.items():
                if profile_id == held["profile_id"]:
                    genuine_scores.append(score)
                    genuine_by_profile[profile_id].append(score)
                else:
                    impostor_scores.append(score)
                    impostor_by_profile[profile_id].append(score)

    unknown_scores: list[float] = []
    profile_ids = sorted(by_profile)
    identity_fold_count = min(5, len(profile_ids))
    identity_fold = {
        profile_id: index % max(identity_fold_count, 1)
        for index, profile_id in enumerate(profile_ids)
    }
    for fold in range(identity_fold_count):
        held_profiles = {
            profile_id
            for profile_id, assigned_fold in identity_fold.items()
            if assigned_fold == fold
        }
        train_rows = [
            row for row in rows if row["profile_id"] not in held_profiles
        ]
        held_rows = [
            row for row in rows if row["profile_id"] in held_profiles
        ]
        if len({row["profile_id"] for row in train_rows}) < 2:
            continue
        components = fit_classical_components(
            train_rows, names, c_value=c_value, gamma=gamma
        )
        for held in held_rows:
            scores = score_classical_components(held["features"], names, components)
            if scores:
                unknown_scores.append(max(scores.values()))

    global_result = choose_operating_threshold(
        genuine_scores,
        [*impostor_scores, *unknown_scores],
        target_far=target_far,
    )
    profile_thresholds = {}
    profile_metrics = {}
    for profile_id, genuine in genuine_by_profile.items():
        impostor = impostor_by_profile.get(profile_id, [])
        if len(genuine) < 2 or not impostor:
            continue
        result = choose_operating_threshold(
            genuine, impostor, target_far=target_far,
            fallback=global_result["threshold"],
        )
        profile_thresholds[profile_id] = round(result["threshold"] * 100, 2)
        profile_metrics[profile_id] = {
            **{key: round(value, 4) for key, value in result.items()},
            "genuine_trials": len(genuine),
            "impostor_trials": len(impostor),
        }

    return {
        "method": "profile_stratified_session_folds_with_identity_disjoint_unknowns",
        "score": "0.8*cosine+0.2*svm_relative_vote",
        "target_far": target_far,
        "session_folds": session_fold_count,
        "identity_folds": identity_fold_count,
        "global_threshold": round(global_result["threshold"] * 100, 2),
        "global_metrics": {
            **{key: round(value, 4) for key, value in global_result.items()},
            "genuine_trials": len(genuine_scores),
            "impostor_trials": len(impostor_scores),
            "unknown_trials": len(unknown_scores),
        },
        "profile_thresholds": profile_thresholds,
        "profile_metrics": profile_metrics,
    }
