from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import joblib
import numpy as np
import torch
from sklearn.preprocessing import RobustScaler
from sklearn.svm import SVC

from .config import ARTIFACT_DIR, MODEL_PATH, NEURAL_PATH, ensure_directories
from .database import all_training_rows, profile_sessions
from .features import detailed_comparison, extract_features, feature_vector
from .neural import BehavioralSequenceNet, session_sequences
from .personal_verifier import score_personal_verifier


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denominator) if denominator else 0.0


@lru_cache(maxsize=2)
def _load_neural_artifact(modified_at: float):
    checkpoint = torch.load(NEURAL_PATH, map_location="cpu", weights_only=False)
    model = BehavioralSequenceNet(len(checkpoint["feature_names"]), len(checkpoint["classes"]))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return checkpoint, model


def _neural_probabilities(session: dict[str, Any], features: dict[str, float]) -> dict[str, float]:
    if not NEURAL_PATH.exists():
        return {}
    try:
        checkpoint, model = _load_neural_artifact(NEURAL_PATH.stat().st_mtime)
        names = checkpoint["feature_names"]
        raw = feature_vector(features, names)
        center = np.asarray(checkpoint["scaler"]["center"], dtype=np.float64)
        scale = np.asarray(checkpoint["scaler"]["scale"], dtype=np.float64)
        scaled = np.divide(raw - center, scale, out=np.zeros_like(raw), where=scale != 0).astype(np.float32)
        keyboard, mouse = session_sequences(session, key_length=160, mouse_length=256)
        with torch.no_grad():
            _, logits = model(
                torch.tensor(keyboard[None, ...], dtype=torch.float32),
                torch.tensor(mouse[None, ...], dtype=torch.float32),
                torch.tensor(scaled[None, ...], dtype=torch.float32),
            )
            probabilities = torch.softmax(logits[0], dim=0).cpu().numpy()
        return {str(profile_id): float(value) for profile_id, value in zip(checkpoint["classes"], probabilities)}
    except (KeyError, RuntimeError, ValueError):
        return {}


def retrain_model() -> dict[str, Any]:
    ensure_directories()
    rows = all_training_rows()
    names = sorted({name for row in rows for name in row["features"]})
    if not rows or not names:
        artifact = {"version": datetime.now(UTC).isoformat(), "feature_names": names, "profiles": {}, "scaler": None, "svm": None}
        joblib.dump(artifact, MODEL_PATH)
        return {"session_count": 0, "profile_count": 0, "svm_trained": False}
    raw = np.vstack([feature_vector(row["features"], names) for row in rows])
    scaler = RobustScaler(quantile_range=(10, 90)).fit(raw)
    matrix = scaler.transform(raw)
    labels = np.asarray([row["profile_id"] for row in rows])
    profiles = {}
    for profile_id in sorted(set(labels)):
        member = matrix[labels == profile_id]
        centroid = member.mean(axis=0)
        norm = np.linalg.norm(centroid)
        profiles[profile_id] = {
            "centroid": centroid / norm if norm else centroid,
            "count": len(member),
            "dispersion": float(np.mean([1 - _cosine(value, centroid) for value in member])),
        }
    svm = None
    if len(profiles) >= 2:
        config_path = ARTIFACT_DIR / "tuned_config.json"
        parameters = json.loads(config_path.read_text()).get("svm", {}) if config_path.exists() else {}
        svm = SVC(kernel="rbf", C=float(parameters.get("C", 2.0)), gamma=parameters.get("gamma", "scale"), class_weight="balanced").fit(matrix, labels)
    artifact = {
        "version": datetime.now(UTC).isoformat(), "feature_names": names, "profiles": profiles,
        "scaler": scaler, "svm": svm, "session_count": len(rows), "profile_count": len(profiles),
        "verification_threshold": float(parameters.get("verification_threshold", 62.0)) if len(profiles) >= 2 else 62.0,
    }
    joblib.dump(artifact, MODEL_PATH)
    return {"version": artifact["version"], "session_count": len(rows), "profile_count": len(profiles), "svm_trained": svm is not None}


def load_model() -> dict[str, Any]:
    if not MODEL_PATH.exists():
        retrain_model()
    return joblib.load(MODEL_PATH)


def score_session(session: dict[str, Any], candidate_ids: list[str]) -> dict[str, Any]:
    artifact = load_model()
    features = extract_features(session)
    names = artifact["feature_names"]
    if not names:
        raise ValueError("No enrolled model is available")
    vector = artifact["scaler"].transform(feature_vector(features, names).reshape(1, -1))[0]
    svm_probabilities: dict[str, float] = {}
    svm = artifact.get("svm")
    if svm is not None:
        decision = np.asarray(svm.decision_function(vector.reshape(1, -1))).reshape(-1)
        if len(svm.classes_) == 2 and decision.size == 1:
            decision = np.asarray([-decision[0], decision[0]])
        decision = np.exp(decision - decision.max())
        decision /= decision.sum()
        svm_probabilities = {str(label): float(value) for label, value in zip(svm.classes_, decision)}
    neural_probabilities = _neural_probabilities(session, features)
    similarities = []
    for profile_id in candidate_ids:
        profile = artifact["profiles"].get(profile_id)
        if profile is None:
            continue
        cosine = (_cosine(vector, profile["centroid"]) + 1) / 2
        svm_probability = svm_probabilities.get(profile_id, cosine)
        neural_probability = neural_probabilities.get(profile_id)
        personal_neural = score_personal_verifier(session, profile_id)
        blended = cosine * 0.8 + svm_probability * 0.2 if neural_probability is None else cosine * 0.7 + svm_probability * 0.2 + neural_probability * 0.1
        similarities.append({
            "profile_id": profile_id, "score": blended, "svm_certainty": round(svm_probability * 100, 1),
            "neural_certainty": round(neural_probability * 100, 1) if neural_probability is not None else None,
            "personal_neural_certainty": personal_neural["certainty"] if personal_neural else None,
            "personal_neural_threshold": personal_neural["threshold"] if personal_neural else None,
            "personal_neural_match": personal_neural["match"] if personal_neural else None,
            "enrollment_count": profile["count"],
        })
    if not similarities:
        raise ValueError("None of the selected profiles has an enrollment")
    similarities.sort(key=lambda row: row["score"], reverse=True)
    raw = np.asarray([row["score"] for row in similarities])
    probabilities = np.exp((raw - raw.max()) * 7)
    probabilities /= probabilities.sum()
    for row, probability in zip(similarities, probabilities):
        row["certainty"] = round(float(probability * 100), 1)
        row["similarity"] = round(float(row.pop("score") * 100), 1)
    best = similarities[0]
    margin = best["similarity"] - similarities[1]["similarity"] if len(similarities) > 1 else 0.0
    threshold = float(artifact.get("verification_threshold", 62.0))
    accepted = best["similarity"] >= threshold and (len(similarities) == 1 or margin >= 3.0)
    return {
        "model_version": artifact["version"], "match": accepted, "best": best,
        "candidates": similarities, "threshold": threshold, "margin": round(margin, 1),
        "features": features,
    }


def compare_detail(profile_id: str, probe_features: dict[str, float]) -> list[dict[str, Any]]:
    enrolled = [row["features"] for row in profile_sessions(profile_id)]
    return detailed_comparison(probe_features, enrolled)


def model_status() -> dict[str, Any]:
    artifact = load_model()
    counts = Counter(row["profile_id"] for row in all_training_rows())
    neural_ready = NEURAL_PATH.exists()
    return {
        "version": artifact["version"], "session_count": artifact.get("session_count", 0),
        "profile_count": artifact.get("profile_count", 0), "svm_trained": artifact.get("svm") is not None,
        "neural_ready": neural_ready,
        "neural_status": "experimental window-trained artifact" if neural_ready and min(counts.values(), default=0) < 2 else "independent-session artifact" if neural_ready else "not trained",
        "strategy": "BiLSTM + TCN fusion when repeated sessions are available; robust centroid/SVM fallback otherwise",
    }
