from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .database import (
    add_session, create_profile, create_review_sample, delete_profile, get_profile,
    get_review_sample_material, init_db, list_profiles, list_review_samples, log_verification, profile_sessions,
    mark_approved_samples_trained, promote_review_sample, reject_review_sample, review_sample_counts, set_blacklist,
    submit_review_feedback, verification_count,
)
from .features import extract_features
from .modeling import compare_detail, model_status, retrain_model, score_session
from .training import train_neural
from .config import ARTIFACT_DIR, PERSONAL_NEURAL_REPORT_PATH
from .profile_analytics import build_character_cards, compare_probe_to_profile


class ProfileCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)


class ProfileUpdate(BaseModel):
    blacklisted: bool


class SessionRequest(BaseModel):
    session: dict[str, Any]


class IdentifyRequest(SessionRequest):
    profile_ids: list[str] = Field(min_length=1, max_length=50)


class FeedbackRequest(BaseModel):
    prediction_correct: bool
    true_profile_id: str | None = None


class ReviewAction(BaseModel):
    action: Literal["approve", "reject"]
    profile_id: str | None = None


app = FastAPI(title="BehaveGuard API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()
    retrain_model()


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok", "model": model_status()}


@app.get("/api/v1/profiles")
def profiles(include_blacklisted: bool = Query(True)) -> list[dict]:
    return list_profiles(include_blacklisted)


@app.post("/api/v1/profiles", status_code=201)
def new_profile(request: ProfileCreate) -> dict:
    try:
        return create_profile(request.label)
    except sqlite3.IntegrityError as error:
        raise HTTPException(409, "A profile with this label already exists") from error


@app.patch("/api/v1/profiles/{profile_id}")
def update_profile(profile_id: str, request: ProfileUpdate) -> dict:
    try:
        profile = set_blacklist(profile_id, request.blacklisted)
        retrain_model()
        return profile
    except KeyError as error:
        raise HTTPException(404, "Profile not found") from error


@app.delete("/api/v1/profiles/{profile_id}", status_code=204)
def remove_profile(profile_id: str) -> None:
    try:
        delete_profile(profile_id)
        retrain_model()
    except KeyError as error:
        raise HTTPException(404, "Profile not found") from error


@app.post("/api/v1/profiles/{profile_id}/enroll")
def enroll(profile_id: str, request: SessionRequest) -> dict:
    try:
        profile = get_profile(profile_id)
    except KeyError as error:
        raise HTTPException(404, "Profile not found") from error
    if profile["blacklisted"]:
        raise HTTPException(403, "Blacklisted profiles cannot be enrolled")
    features = extract_features(request.session)
    session_id = add_session(profile_id, request.session, features)
    training = retrain_model()
    neural = train_neural(epochs=20)
    return {"session_id": session_id, "profile": get_profile(profile_id), "training": training, "neural": neural}


@app.post("/api/v1/verify/{profile_id}")
def verify(profile_id: str, request: SessionRequest) -> dict:
    try:
        profile = get_profile(profile_id)
        if profile["blacklisted"]:
            raise HTTPException(403, "Profile is blacklisted")
        result = score_session(request.session, [profile_id])
        result["best"]["label"] = profile["label"]
        features = result.pop("features")
        result["detail"] = compare_detail(profile_id, features)
        event_id = log_verification("1to1", profile_id, [profile_id], result)
        result["review_sample_id"] = create_review_sample(
            event_id, "1to1", profile_id, profile_id, [profile_id], request.session, features, result,
        )
        result["feedback_status"] = "awaiting_feedback"
        return result
    except KeyError as error:
        raise HTTPException(404, "Profile not found") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/v1/identify")
def identify(request: IdentifyRequest) -> dict:
    valid = []
    labels = {}
    for profile_id in request.profile_ids:
        try:
            profile = get_profile(profile_id)
            if not profile["blacklisted"]:
                valid.append(profile_id)
                labels[profile_id] = profile["label"]
        except KeyError:
            pass
    if not valid:
        raise HTTPException(422, "No active candidate profiles selected")
    try:
        result = score_session(request.session, valid)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    features = result.pop("features")
    for candidate in result["candidates"]:
        candidate["label"] = labels[candidate["profile_id"]]
    result["best"] = result["candidates"][0]
    event_id = log_verification("1toN", None, valid, result)
    result["review_sample_id"] = create_review_sample(
        event_id, "1toN", None, result["best"]["profile_id"], valid, request.session, features, result,
    )
    result["feedback_status"] = "awaiting_feedback"
    return result


@app.post("/api/v1/review-samples/{review_id}/feedback")
def review_feedback(review_id: str, request: FeedbackRequest) -> dict:
    try:
        return submit_review_feedback(review_id, request.prediction_correct, request.true_profile_id)
    except KeyError as error:
        raise HTTPException(404, "Review sample or profile not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.get("/api/v1/admin/analytics")
def admin_analytics() -> dict:
    profiles = list_profiles()
    active = [profile for profile in profiles if not profile["blacklisted"]]
    similarity = []
    status = model_status()
    from .modeling import load_model, _cosine
    artifact = load_model()
    for left in active:
        row = []
        for right in active:
            a, b = artifact["profiles"].get(left["id"]), artifact["profiles"].get(right["id"])
            row.append(round((_cosine(a["centroid"], b["centroid"]) + 1) * 50, 1) if a and b else None)
        similarity.append(row)
    experiment_path = ARTIFACT_DIR / "experiment_report.json"
    experiment = None
    if experiment_path.exists():
        report = json.loads(experiment_path.read_text())
        experiment = {
            "validity": report["validity"], "warning": report["warning"],
            "best_model": report["best_model"], "best_metrics": report["best_metrics"],
            "best_svm": report["best_svm"], "tuned_svm": report["tuned_svm"],
            "ablations": report["ablations"], "neural": report["neural"],
        }
    personal_neural = json.loads(PERSONAL_NEURAL_REPORT_PATH.read_text()) if PERSONAL_NEURAL_REPORT_PATH.exists() else None
    review_counts = review_sample_counts()
    review_queue = list_review_samples()
    for sample in review_queue:
        target = sample["true_profile_id"] or sample["predicted_profile_id"]
        sample["comparison"] = build_review_comparison(sample["id"], target) if target else None
    return {
        "summary": {"profiles": len(profiles), "active_profiles": len(active), "sessions": sum(p["enrollment_count"] for p in profiles), "verifications": verification_count(), "review_samples_available": review_counts["available"]},
        "profiles": profiles, "similarity_labels": [p["label"] for p in active], "similarity_matrix": similarity,
        "model": status, "experiment": experiment, "personal_neural": personal_neural,
        "profile_cards": build_character_cards(profiles),
        "review_counts": review_counts, "review_queue": review_queue,
    }


def build_review_comparison(review_id: str, profile_id: str) -> dict:
    profile = get_profile(profile_id)
    material = get_review_sample_material(review_id)
    comparison = compare_probe_to_profile(profile_id, material["payload"], material["features"])
    comparison["profile_label"] = profile["label"]
    return comparison


@app.get("/api/v1/admin/review-samples/{review_id}/comparison")
def review_comparison(review_id: str, profile_id: str = Query(...)) -> dict:
    try:
        return build_review_comparison(review_id, profile_id)
    except KeyError as error:
        raise HTTPException(404, "Review sample or profile not found") from error


@app.patch("/api/v1/admin/review-samples/{review_id}")
def review_sample(review_id: str, request: ReviewAction) -> dict:
    try:
        if request.action == "approve":
            return promote_review_sample(review_id, request.profile_id)
        return reject_review_sample(review_id)
    except KeyError as error:
        raise HTTPException(404, "Review sample or profile not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.post("/api/v1/admin/retrain")
def retrain() -> dict:
    classical = retrain_model()
    neural = train_neural(epochs=20)
    included_review_samples = mark_approved_samples_trained()
    return {"classical": classical, "neural": neural, "included_review_samples": included_review_samples}


@app.get("/api/v1/admin/profiles/{profile_id}/stats")
def profile_stats(profile_id: str) -> dict:
    try:
        profile = get_profile(profile_id)
    except KeyError as error:
        raise HTTPException(404, "Profile not found") from error
    sessions = profile_sessions(profile_id)
    categories = {"keyboard": "key_", "passive mouse": "passive_", "click": "dot_", "drag": "drag_", "tracking": "track_"}
    category_values = []
    for label, prefix in categories.items():
        values = [abs(value) for session in sessions for name, value in session["features"].items() if name.startswith(prefix)]
        category_values.append({"category": label, "value": round(sum(values) / max(len(values), 1), 2)})
    return {"profile": profile, "sessions": [{"id": row["id"], "collected_at": row["collected_at"]} for row in sessions], "category_values": category_values}
