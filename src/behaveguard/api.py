from __future__ import annotations

import json
import secrets
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError

from . import oauth_google
from .auth import (
    CurrentUser,
    create_access_token,
    get_current_user,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    require_admin,
    require_platform_admin,
    verify_password,
)
from .config import ARTIFACT_DIR, AUTO_ENROLLMENT_SIMILARITY_THRESHOLD, FRONTEND_URL, PERSONAL_NEURAL_DIR, PERSONAL_NEURAL_REPORT_PATH
from .database import (
    add_session, claim_profile, create_profile, delete_profile,
    get_active_refresh_token, get_profile, get_profile_by_user, get_review_sample_material,
    get_user_by_oauth, get_user_credentials_by_email, init_db, link_oauth_identity, list_merge_events,
    list_model_versions, list_profiles, list_review_samples, list_security_alerts, log_verification,
    profile_sessions, mark_approved_samples_trained, promote_review_sample, reject_review_sample,
    revert_merge_event, revoke_refresh_token, review_sample_counts, set_blacklist, store_refresh_token,
    submit_review_feedback, update_security_alert_status, verification_count,
)
from .database import create_user as db_create_user
from .features import extract_features
from .jobs import enqueue_retrain_neural, list_recent_job_statuses
from .security import check_replay, rate_limit_login, rate_limit_verify, track_verification_score
from .worker import run_worker_in_background_thread
from .merging import scan_and_auto_merge
from .modeling import compare_detail, model_status, retrain_model, score_session
from .profile_analytics import build_character_cards, compare_probe_to_profile, session_behavior_metrics
from .database import create_claim_token


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


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ClaimRequest(BaseModel):
    token: str


class SecurityAlertAction(BaseModel):
    status: Literal["ack", "dismissed"]


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
    # Local-dev convenience: runs the retrain-job worker as a background
    # thread inside this same process, so `uv run behaveguard serve` alone
    # is enough — see worker.py's docstring for why the deployment phase
    # will split this into its own service instead.
    run_worker_in_background_thread()


@app.get("/api/v1/ping")
def ping() -> dict:
    """Absolute-minimum unauthenticated round-trip, deliberately separate
    from /health: the bootloader's cold-start probe just needs to know the
    process is up and accepting requests, not that the model/DB/Redis are
    all warm too (that's what /health is for)."""
    return {"status": "ok"}


@app.get("/api/v1/health")
def health() -> dict:
    from .redis_client import get_redis

    redis_ok = False
    try:
        redis_ok = bool(get_redis().ping())
    except Exception:
        redis_ok = False
    return {"status": "ok", "model": model_status(), "redis": redis_ok}


def _issue_token_pair(user: dict[str, Any]) -> dict[str, Any]:
    access_token = create_access_token(user["id"], user["role"], user["org_id"])
    raw_refresh, refresh_hash, expires_at = new_refresh_token()
    store_refresh_token(user["id"], refresh_hash, expires_at)
    return {"access_token": access_token, "refresh_token": raw_refresh, "token_type": "bearer", "user": user}


@app.post("/api/v1/auth/register", status_code=201)
def register(request: RegisterRequest, http_request: Request) -> dict:
    """Self-service only — every account is created this way (or via Google
    login below), always as role='user'. There is no admin-creates-user
    route anywhere in this API."""
    rate_limit_login(http_request)
    try:
        user = db_create_user(request.email, password_hash=hash_password(request.password))
    except IntegrityError as error:
        raise HTTPException(409, "An account with this email already exists") from error
    return _issue_token_pair(user)


@app.post("/api/v1/auth/login")
def login(request: LoginRequest, http_request: Request) -> dict:
    rate_limit_login(http_request)
    found = get_user_credentials_by_email(request.email)
    if found is None:
        raise HTTPException(401, "Invalid email or password")
    user, password_hash = found
    if password_hash is None or not verify_password(request.password, password_hash):
        raise HTTPException(401, "Invalid email or password")
    if user["status"] != "active":
        raise HTTPException(403, "Account is not active")
    return _issue_token_pair(user)


@app.post("/api/v1/auth/refresh")
def refresh_token_route(request: RefreshRequest) -> dict:
    token_hash = hash_refresh_token(request.refresh_token)
    active = get_active_refresh_token(token_hash)
    if active is None:
        raise HTTPException(401, "Refresh token is invalid, expired, or already used")
    # Rotation: the old token is revoked as soon as it's redeemed, whether or
    # not anything below fails, so a replayed old token can never succeed twice.
    revoke_refresh_token(token_hash)
    from .database import get_user

    user = get_user(active["user_id"])
    if user["status"] != "active":
        raise HTTPException(403, "Account is not active")
    return _issue_token_pair(user)


@app.post("/api/v1/auth/logout", status_code=204)
def logout(request: RefreshRequest) -> None:
    revoke_refresh_token(hash_refresh_token(request.refresh_token))


@app.get("/api/v1/auth/me")
def me(current_user: CurrentUser = Depends(get_current_user)) -> dict:
    from .database import get_user

    return get_user(current_user.id)


@app.get("/api/v1/auth/google/login")
def google_login() -> RedirectResponse:
    state = oauth_google.new_state_token()
    url = oauth_google.build_authorization_url(state)
    response = RedirectResponse(url)
    # Short-lived, httponly cookie carries the CSRF state across the
    # redirect round-trip to Google and back; verified in the callback below.
    response.set_cookie("bg_oauth_state", state, max_age=600, httponly=True, samesite="lax")
    return response


@app.get("/api/v1/auth/google/callback")
def google_callback(code: str, state: str, request: Request) -> RedirectResponse:
    expected_state = request.cookies.get("bg_oauth_state")
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise HTTPException(401, "Invalid or expired OAuth state")

    id_token_jwt = oauth_google.exchange_code_for_id_token(code)
    claims = oauth_google.verify_id_token(id_token_jwt)
    email, subject = claims["email"], claims["sub"]

    user = get_user_by_oauth("google", subject)
    if user is None:
        existing = get_user_credentials_by_email(email)
        if existing is not None:
            # Same verified email as an existing password account — link
            # rather than create a second account for the same person.
            user = link_oauth_identity(existing[0]["id"], "google", subject)
        else:
            user = db_create_user(email, oauth_provider="google", oauth_subject=subject)

    tokens = _issue_token_pair(user)
    redirect_url = (
        f"{FRONTEND_URL}/auth/callback"
        f"#access_token={tokens['access_token']}&refresh_token={tokens['refresh_token']}"
    )
    # Tokens travel in the URL fragment, not the query string or a redirect
    # body: fragments are never sent to the server or written to access
    # logs, and the frontend can read+strip it client-side in one step.
    response = RedirectResponse(redirect_url)
    response.delete_cookie("bg_oauth_state")
    return response


@app.post("/api/v1/profiles/claim")
def claim(request: ClaimRequest, current_user: CurrentUser = Depends(get_current_user)) -> dict:
    try:
        profile = claim_profile(request.token, current_user.id)
        retrain_model()
        return profile
    except KeyError as error:
        raise HTTPException(404, str(error) or "Invalid claim token") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.get("/api/v1/profiles")
def profiles(include_blacklisted: bool = Query(True), current_user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    owner_filter = None if current_user.is_admin else current_user.id
    return list_profiles(include_blacklisted, owner_user_id=owner_filter)


@app.post("/api/v1/profiles", status_code=201)
def new_profile(request: ProfileCreate, current_user: CurrentUser = Depends(get_current_user)) -> dict:
    """Self-service enrollment only — always creates a profile owned by the
    caller. There is no way to create a profile for someone else here; that's
    what /profiles/claim is for (linking a *pre-existing* legacy profile)."""
    if get_profile_by_user(current_user.id) is not None:
        raise HTTPException(409, "Your account is already linked to a profile")
    try:
        return create_profile(request.label, user_id=current_user.id)
    except IntegrityError as error:
        raise HTTPException(409, "A profile with this label already exists") from error


@app.get("/api/v1/profiles/me/stats")
def my_profile_stats(current_user: CurrentUser = Depends(get_current_user)) -> dict:
    """Self-service version of the admin-only per-profile stats route below —
    scoped to the caller's own profile only, for the post-enrollment stats
    view and the landing-page highlights strip. Reuses
    profile_analytics.session_behavior_metrics (same function the admin
    dashboard's character cards are built from) rather than adding a second
    way to compute these numbers."""
    profile = get_profile_by_user(current_user.id)
    if profile is None:
        raise HTTPException(404, "You do not have a profile yet")
    sessions = profile_sessions(profile["id"])
    history = [
        {"session_id": row["id"], "collected_at": row["collected_at"], **session_behavior_metrics(row["payload"])}
        for row in sessions
    ]
    latest = history[-1] if history else None
    return {"profile": profile, "latest": latest, "history": history}


@app.patch("/api/v1/profiles/{profile_id}")
def update_profile(profile_id: str, request: ProfileUpdate, current_user: CurrentUser = Depends(require_admin)) -> dict:
    try:
        profile = set_blacklist(profile_id, request.blacklisted)
        retrain_model()
        return profile
    except KeyError as error:
        raise HTTPException(404, "Profile not found") from error


@app.delete("/api/v1/profiles/{profile_id}", status_code=204)
def remove_profile(profile_id: str, current_user: CurrentUser = Depends(require_admin)) -> None:
    try:
        delete_profile(profile_id)
        retrain_model()
    except KeyError as error:
        raise HTTPException(404, "Profile not found") from error


def _require_profile_access(profile_id: str, current_user: CurrentUser) -> dict:
    try:
        profile = get_profile(profile_id)
    except KeyError as error:
        raise HTTPException(404, "Profile not found") from error
    if not current_user.is_admin and profile["user_id"] != current_user.id:
        raise HTTPException(403, "You do not have access to this profile")
    return profile


@app.post("/api/v1/profiles/{profile_id}/enroll")
def enroll(profile_id: str, request: SessionRequest, current_user: CurrentUser = Depends(get_current_user)) -> dict:
    profile = _require_profile_access(profile_id, current_user)
    if profile["blacklisted"]:
        raise HTTPException(403, "Blacklisted profiles cannot be enrolled")
    features = extract_features(request.session)
    session_id = add_session(profile_id, request.session, features)
    # Classical retrain (RobustScaler + centroid + SVM) is cheap numpy work —
    # kept inline so the caller's own next verification is scored against an
    # up-to-date model immediately. The neural fusion model's retrain is the
    # slow part (real PyTorch training epochs); that's queued for the
    # background worker instead of blocking this response — see worker.py.
    training = retrain_model()
    job_id = enqueue_retrain_neural(reason=f"enroll:{profile_id}")
    return {"session_id": session_id, "profile": get_profile(profile_id), "training": training, "neural_retrain_job_id": job_id}


@app.post("/api/v1/verify/{profile_id}")
def verify(profile_id: str, request: SessionRequest, http_request: Request, current_user: CurrentUser = Depends(get_current_user)) -> dict:
    """Phase 2: no review-queue quarantine. Login already answers "who is
    this" for a 1:1 self-check, so there's nothing left for a human reviewer
    to confirm. `verification_events` still logs every attempt for audit
    purposes; what's gone is the promote-after-approval workflow.

    A confident match on the caller's *own* profile also auto-folds this
    session into training data — the quality gate (a similarity bar well
    above the accept threshold) plays the role the human reviewer used to
    play, and is what makes "the profile keeps improving on its own every
    time you verify" safe rather than an open door for drift.

    Phase 4: rate-limited per profile, checked for exact-payload replay, and
    each score is tracked for a "hovering just under the threshold"
    near-miss pattern — all three raise passive `security_alerts` rows for
    an admin to look at rather than blocking the request itself.
    """
    rate_limit_verify(http_request, profile_id)
    profile = _require_profile_access(profile_id, current_user)
    if profile["blacklisted"]:
        raise HTTPException(403, "Profile is blacklisted")
    check_replay(profile_id, request.session)
    try:
        result = score_session(request.session, [profile_id])
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    result["best"]["label"] = profile["label"]
    features = result.pop("features")
    result["detail"] = compare_detail(profile_id, features)
    log_verification("1to1", profile_id, [profile_id], result)
    track_verification_score(profile_id, result["best"]["similarity"], result["threshold"])

    auto_enrolled = False
    if (
        result.get("match")
        and profile["user_id"] == current_user.id
        and result["best"]["similarity"] >= AUTO_ENROLLMENT_SIMILARITY_THRESHOLD
    ):
        add_session(profile_id, request.session, features, purpose="auto_reenrollment")
        retrain_model()
        enqueue_retrain_neural(reason=f"auto_reenroll:{profile_id}")
        auto_enrolled = True
    result["auto_enrolled"] = auto_enrolled
    # Phase 4.5: post-verification UX context. This is a second, separate
    # scoring call purely for display — it never touches `result["match"]`,
    # `margin`, or `auto_enrolled` above, all of which were already decided
    # against just [profile_id]. Only aggregate counts are exposed, never
    # another profile's identity/label, and any failure here is swallowed so
    # a verify can never fail because of this add-on.
    try:
        active_ids = [row["id"] for row in list_profiles(include_blacklisted=False)]
        pool = score_session(request.session, active_ids) if len(active_ids) > 1 else None
        close_margin = 10.0
        close_matches = (
            sum(1 for row in pool["candidates"] if row["profile_id"] != profile_id and row["similarity"] >= result["best"]["similarity"] - close_margin)
            if pool else 0
        )
        status = model_status()
        result["context"] = {
            "candidate_pool_size": len(active_ids),
            "close_matches": close_matches,
            "total_training_sessions": status["session_count"],
            "own_enrollment_count": profile["enrollment_count"],
        }
    except Exception:
        result["context"] = None
    return result


@app.post("/api/v1/identify")
def identify(request: IdentifyRequest, current_user: CurrentUser = Depends(require_admin)) -> dict:
    """Phase 2: also no review-queue quarantine — logged purely as an
    audited `verification_events` row. Identification results stay
    admin-only (see `require_admin` above); if an admin wants to turn a
    correctly-identified probe into training data, the supported path is
    having that person's own account claim/re-enroll, not silently promoting
    an arbitrary probe session."""
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
    log_verification("1toN", None, valid, result)
    return result


@app.post("/api/v1/review-samples/{review_id}/feedback")
def review_feedback(review_id: str, request: FeedbackRequest, current_user: CurrentUser = Depends(get_current_user)) -> dict:
    try:
        return submit_review_feedback(review_id, request.prediction_correct, request.true_profile_id)
    except KeyError as error:
        raise HTTPException(404, "Review sample or profile not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.get("/api/v1/admin/analytics")
def admin_analytics(current_user: CurrentUser = Depends(require_platform_admin)) -> dict:
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
    personal_reports = [json.loads(path.read_text()) for path in PERSONAL_NEURAL_DIR.glob("*.json")]
    if PERSONAL_NEURAL_REPORT_PATH.exists():
        legacy = json.loads(PERSONAL_NEURAL_REPORT_PATH.read_text())
        if not any(report["target_profile_id"] == legacy["target_profile_id"] for report in personal_reports):
            personal_reports.append(legacy)
    personal_reports.sort(key=lambda report: report.get("created_at", ""), reverse=True)
    personal_neural = personal_reports[0] if personal_reports else None
    review_counts = review_sample_counts()
    review_queue = list_review_samples()
    for sample in review_queue:
        target = sample["true_profile_id"] or sample["predicted_profile_id"]
        sample["comparison"] = build_review_comparison(sample["id"], target) if target else None
    return {
        "summary": {"profiles": len(profiles), "active_profiles": len(active), "sessions": sum(p["enrollment_count"] for p in profiles), "verifications": verification_count(), "review_samples_available": review_counts["available"]},
        "profiles": profiles, "similarity_labels": [p["label"] for p in active], "similarity_matrix": similarity,
        "model": status, "experiment": experiment, "personal_neural": personal_neural,
        "personal_neural_reports": personal_reports,
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
def review_comparison(review_id: str, profile_id: str = Query(...), current_user: CurrentUser = Depends(require_platform_admin)) -> dict:
    try:
        return build_review_comparison(review_id, profile_id)
    except KeyError as error:
        raise HTTPException(404, "Review sample or profile not found") from error


@app.patch("/api/v1/admin/review-samples/{review_id}")
def review_sample(review_id: str, request: ReviewAction, current_user: CurrentUser = Depends(require_platform_admin)) -> dict:
    try:
        if request.action == "approve":
            return promote_review_sample(review_id, request.profile_id)
        return reject_review_sample(review_id)
    except KeyError as error:
        raise HTTPException(404, "Review sample or profile not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.post("/api/v1/admin/retrain")
def retrain(current_user: CurrentUser = Depends(require_platform_admin)) -> dict:
    classical = retrain_model()
    job_id = enqueue_retrain_neural(reason="admin_retrain")
    included_review_samples = mark_approved_samples_trained()
    return {"classical": classical, "neural_retrain_job_id": job_id, "included_review_samples": included_review_samples}


@app.get("/api/v1/admin/jobs")
def jobs_status(current_user: CurrentUser = Depends(require_platform_admin)) -> list[dict]:
    return list_recent_job_statuses()


@app.get("/api/v1/admin/model-versions")
def model_versions(kind: str | None = Query(None), current_user: CurrentUser = Depends(require_platform_admin)) -> list[dict]:
    return list_model_versions(kind)


@app.get("/api/v1/admin/security-alerts")
def security_alerts(
    status: str = Query("open"), current_user: CurrentUser = Depends(require_platform_admin)
) -> list[dict]:
    statuses = ("open", "ack", "dismissed") if status == "all" else (status,)
    return list_security_alerts(statuses)


@app.patch("/api/v1/admin/security-alerts/{alert_id}")
def update_security_alert(
    alert_id: str, request: SecurityAlertAction, current_user: CurrentUser = Depends(require_platform_admin)
) -> dict:
    try:
        return update_security_alert_status(alert_id, request.status)
    except KeyError as error:
        raise HTTPException(404, "Security alert not found") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/v1/admin/merge/scan")
def merge_scan(current_user: CurrentUser = Depends(require_platform_admin)) -> dict:
    """Triggers an immediate auto-merge scan. No individual merge is
    approved beforehand — see merging.scan_and_auto_merge's docstring for
    why that's an acceptable default (conservative threshold + reversible
    MergeEvent audit trail instead of a per-merge human gate)."""
    return scan_and_auto_merge()


@app.get("/api/v1/admin/merge/events")
def merge_events(current_user: CurrentUser = Depends(require_platform_admin)) -> list[dict]:
    return list_merge_events()


@app.post("/api/v1/admin/merge/{event_id}/revert")
def revert_merge(event_id: str, current_user: CurrentUser = Depends(require_platform_admin)) -> dict:
    try:
        event = revert_merge_event(event_id)
        retrain_model()
        return event
    except KeyError as error:
        raise HTTPException(404, "Merge event not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.post("/api/v1/admin/profiles/{profile_id}/claim-token")
def admin_generate_claim_token(profile_id: str, current_user: CurrentUser = Depends(require_platform_admin)) -> dict:
    """Dashboard equivalent of the old `generate-claim-token` CLI command
    (now removed from the CLI — see cli.py). Mints a one-time token for the
    real owner of a pre-existing/legacy profile to link it to their own
    self-registered account; still gated to platform_admin, same as the CLI
    version was gated to whoever had shell access. `promote-admin` remains
    the one CLI-only action by design (see cli.py's docstring)."""
    try:
        get_profile(profile_id)
        token = create_claim_token(profile_id)
    except KeyError as error:
        raise HTTPException(404, "Profile not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {"profile_id": profile_id, "token": token}


@app.get("/api/v1/admin/profiles/{profile_id}/stats")
def profile_stats(profile_id: str, current_user: CurrentUser = Depends(require_platform_admin)) -> dict:
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
