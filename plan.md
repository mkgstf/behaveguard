# BehaveGuard Rewrite Plan

## 1. Goal and success criteria

Build a complete behavioral-authentication system around the existing Next.js collector:

- Enroll a person from multiple keyboard and mouse sessions.
- Verify **1:1** by selecting a claimed profile and accepting or rejecting the new session.
- Identify **1:N** by selecting a profile group, ranking its members by similarity, and returning the closest match or `no_match`.
- Train, evaluate, version, and serve a deep multimodal embedding model through a reproducible `uv` workflow.
- Keep raw behavioral data private, preserve consent, prevent train/test leakage, and expose calibrated verification scores rather than unqualified confidence claims.

The first usable release is complete when a user can create profiles and groups, enroll repeated sessions, run both verification modes in the frontend, inspect ranked/calibrated results, retrain through a documented CLI, and promote a tested model artifact to the backend.

## 2. Current-state findings

### Frontend

The cloned frontend lives in `behaveguard-client/` and is a Next.js 16/React 19 application. Its current flow is consent -> session label -> keyboard task -> dot task -> tracking task -> drag task -> analytics -> fire-and-forget submission to Google Apps Script. The existing `SessionData` payload already contains key events, IKI/trigraph features, passive mouse points, dot paths and kinematics, pursuit-tracking samples, and drag paths and kinematics.

There is currently no backend API, durable profile/group model, enrollment workflow, verification workflow, model serving, retryable submission, or server-confirmed result state. The name field is only a free-text session label.

### Workbook

Treat `Behaveguard-client.xlsx` as immutable source data and import it through an explicit dataset-ingestion command. It contains 9 sheets with 10 subjects/sessions, 30,000 passive mouse rows, 22,404 tracking samples, 6,485 key events, 250 dot trials, and 100 drag trials.

Important limitations and quality issues:

- Every subject has only one session. Windowing one session creates training examples but does **not** create independent enrollment/probe evidence.
- `Siya` has a session and mouse data but no `KeyEvents` or `Trigraphs` rows.
- `release_ts`/`dwell_ms` are missing for 49 key events and must be masked, not imputed as zero.
- Fixed-count fields (`n_mouse_events`, `n_dot_targets`, `n_drags`, `n_track_trials`), fixed task duration, and fixed drag start position carry no identity value.
- Absolute coordinates, collection timestamps, subject names, and time-of-day encodings can leak device/session identity and must not be authentication features.
- Pressure is mostly synthetic browser data (`0` or `0.5`) and should only be enabled when real pointer-type coverage proves it useful.

The workbook can support parser tests, feature-pipeline tests, self-supervised pretraining experiments, and an explicitly labelled demo model. It cannot support a trustworthy production FAR/FRR result. Collect at least **5 sessions per person across 3 days** (minimum 3 sessions for development), ideally on more than one device/context, before model selection and threshold calibration.

## 3. Repository and technology layout

Keep the frontend clone intact and add one root Python project managed only with `uv`:

```text
behave-rewrite/
  behaveguard-client/       # existing Next.js application
  src/behaveguard/
    api/                    # FastAPI routes, dependencies, schemas
    db/                     # SQLAlchemy models and repositories
    data/                   # XLSX/JSON ingestion and validation
    features/               # canonical preprocessing and feature engineering
    modeling/               # PyTorch encoders, losses, export and inference
    training/               # splits, loaders, training, evaluation, calibration
    verification/           # enrollment prototypes and 1:1/1:N scoring
    cli.py                  # import, train, evaluate, promote commands
  configs/                  # versioned data/model/training configuration
  migrations/               # Alembic migrations
  tests/                    # unit, integration, ML and contract tests
  artifacts/                # gitignored local model artifacts
  pyproject.toml
  uv.lock
  compose.yaml
```

Use Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL with `pgvector`, NumPy/Polars/PyArrow for data preparation, PyTorch for modeling, scikit-learn for metrics/calibration, and Typer for CLI commands. Use plain PyTorch training loops with TensorBoard/JSON metrics to keep the training stack inspectable. Docker Compose should provide PostgreSQL/pgvector and the API; local raw/model storage should be replaceable with S3-compatible storage through one storage interface.

All Python actions use `uv`, for example `uv sync`, `uv run behaveguard import-xlsx ...`, `uv run behaveguard train ...`, and `uv run pytest`.

## 4. Data contracts and persistence

### Collection payload v2

Retain the existing behavioral arrays, but replace a name as the primary identifier with server-issued UUIDs and add:

- `schema_version`, `session_id`, `profile_id` when enrolling/verifying, `purpose` (`enroll`, `verify_1to1`, `identify_1ton`), and optional `group_id`.
- Viewport width/height, device-pixel ratio, pointer type, coarse device class, keyboard layout, app version, task configuration version, and monotonic/UTC timing metadata.
- Per-task completion/quality flags and explicit missing-modality markers.

Do not store typed free-text content. Key IDs remain sensitive behavioral data: never place payloads in logs, analytics products, URLs, or browser persistence. Validate payload sizes, finite numeric values, monotonic timestamps, allowed key vocabulary, task counts, and duration bounds before persistence.

### Database entities

- `profiles`: UUID, display label, status, timestamps, optional metadata.
- `groups` and `group_members`: named candidate sets for 1:N search.
- `sessions`: UUID, purpose, profile/group context, schema/task versions, quality state, raw-object reference, timestamps.
- `embeddings`: session/model/modality, normalized vector, quality score, metadata; indexed with pgvector.
- `profile_templates`: model/profile, centroid embedding, dispersion, enrollment session count, threshold override, version.
- `models`: immutable model version, artifact URI/checksum, config/dataset fingerprints, metrics, status (`candidate`, `active`, `retired`).
- `verification_events`: request context, model version, scores, threshold, decision, latency, and non-sensitive audit metadata.

Use soft deletion for profiles/groups, foreign keys for ownership consistency, idempotency keys on session upload, and database transactions when updating templates. Raw session payloads are immutable objects; derived features and embeddings are reproducible from raw data plus versioned configuration.

## 5. ML and feature pipeline

### Ingestion and quality gates

1. Import every workbook sheet, join by `(subject_id, collected_at)`, generate stable UUID mappings, and emit a canonical Parquet dataset plus a validation report.
2. Apply the same Pydantic/canonicalization code to XLSX imports and live JSON submissions.
3. Reject or quarantine malformed sessions; retain valid mouse-only sessions with an explicit keyboard mask.
4. Window long streams with overlap only **after** assigning the parent session to a split. Never allow windows from one session on both sides of a split.
5. Fit normalization statistics on training data only and store them in the model artifact.

### Engineered inputs

Keyboard sequence inputs:

- Learned key/category/segment embeddings.
- Dwell, press-to-press IKI, release-to-press flight time, overlap, shift state/lead time, correction/backspace context, local rhythm statistics, and validity masks.
- Log-clipped robust-scaled timing values and sequence position; no subject label, wall-clock time, or absolute collection timestamp.

Mouse sequence inputs:

- Viewport-normalized displacement and target-relative coordinates, `dt`, distance, speed, acceleration, jerk, movement angle, angular velocity, curvature, pauses, direction changes, and click/drag endpoint error.
- Pursuit error/lag/correlation/fatigue features and per-task identifiers.
- Prefer displacement/target-relative dynamics over absolute screen position. Mask pressure unless the device reports meaningful pressure.

Session-level features:

- Robust quantiles, median/MAD, coefficient of variation, entropy, autocorrelation, error/correction rates, Fitts-law-style movement efficiency, path straightness, overshoot, tremor-band energy, and cross-task consistency.
- Keep these as an auxiliary branch and for interpretable diagnostics. Drop constants, duplicate summaries already derivable from raw sequences, identifiers, and leakage-prone context features.

Feature selection is performed inside training folds using constant/near-constant removal, correlation clustering, permutation/ablation checks, and modality-level ablations. Store the final feature manifest with the model.

### Deep model

Implement a multimodal metric-learning model that produces a 128-dimensional L2-normalized session embedding:

- Keyboard tower: small Transformer encoder with timing projection, masks, attention pooling, and a handcrafted-feature projection.
- Mouse tower: shared temporal convolution/Transformer encoder over passive, dot, tracking, and drag windows, followed by task-aware attention pooling and a handcrafted-feature projection.
- Fusion: quality-aware gated attention so missing or low-quality modalities are down-weighted rather than zero-filled.
- Training loss: supervised contrastive loss plus ArcFace classification auxiliary loss; balanced identity/session batches and mild, behavior-preserving timing/point dropout augmentations.
- Export: TorchScript or ONNX artifact containing preprocessing metadata, feature manifest, thresholds, model checksum, and schema/task compatibility versions.

Also train a simple robust-statistics cosine baseline. The deep model is promoted only if it beats the baseline on session-disjoint verification metrics and does not regress badly for either keyboard-only or mouse-only samples.

### Splitting, evaluation, and calibration

- Production evaluation requires independent sessions. Use identity-disjoint outer evaluation where held-out people still have separate enrollment and probe sessions, plus a session-disjoint closed-roster evaluation for the deployed population.
- Report ROC-AUC, PR-AUC, EER, TAR at FAR `1%`, `0.1%`, and `0.01%` where sample size permits, FRR at the chosen threshold, top-1/top-3 identification accuracy, false-identification rate, no-match accuracy, calibration curves, and latency.
- Report bootstrap confidence intervals by resampling people/sessions, not individual windows.
- Calibrate a global cosine threshold from validation genuine/impostor pairs. Permit a per-profile threshold only after enough enrollment/validation samples; otherwise inherit the global threshold.
- For 1:N, apply both a minimum top score and a minimum top-1/top-2 margin. Return `no_match` when either fails.
- Mark all metrics from the current one-session workbook as `development_only`; do not promote that model to production status.

## 6. Enrollment and verification behavior

### Enrollment

- A profile becomes `ready` after 3 quality-passing sessions; 5 is the recommended target.
- Encode each enrollment session, reject low-quality/outlier embeddings, and create a normalized, quality-weighted centroid plus dispersion statistics.
- Never update a template with an unverified probe. Template refresh must be explicit or require a successful high-confidence verification and audit record.

### 1:1 verification

1. User selects a profile and completes the same versioned collection tasks.
2. Backend validates quality, generates an embedding, and compares it with that profile template.
3. Return `accept`, `reject`, or `insufficient_quality`, with similarity, applied threshold, model version, modality quality, and human-readable reason codes.

### 1:N identification

1. User selects a group and completes the collection tasks.
2. Backend searches only active templates in that group using pgvector cosine distance, then reranks the top candidates with the exact scorer.
3. Return `match` or `no_match`, the closest profile, calibrated score, threshold/margin result, and top 5 candidates. Do not claim a match merely because one candidate is mathematically closest.

## 7. Backend API

Version all routes under `/api/v1` and generate an OpenAPI client/types for the frontend.

- `POST/GET/PATCH /profiles`, `GET /profiles/{id}`, `DELETE /profiles/{id}`.
- `POST/GET/PATCH /groups`, member add/remove endpoints, and group detail with ready-profile counts.
- `POST /sessions` for validated, idempotent raw upload; return a server-confirmed session ID and quality summary.
- `POST /profiles/{id}/enroll` to attach a completed session and rebuild the template.
- `POST /verify/1to1` with `profile_id` and `session_id`.
- `POST /verify/1ton` with `group_id`, `session_id`, and bounded `top_k` (default/max 5/20).
- `GET /models/active`, `GET /health/live`, and `GET /health/ready`.

Use structured error envelopes with stable error codes, strict request limits, CORS restricted to configured frontend origins, redacted structured logs, request IDs, rate limiting on verification endpoints, and constant-time handling where practical. Model loading occurs once at startup; readiness fails when the active artifact/schema is incompatible.

The CLI owns administrative/offline operations:

- `import-xlsx`, `validate-dataset`, `build-dataset`.
- `train`, `evaluate`, `calibrate`, `export-model`, `promote-model`.
- `backfill-embeddings` and `rebuild-templates` for a selected model version.

Every command accepts a config file and seed, writes a run manifest, and exits nonzero on quality/test/promotion-gate failure.

## 8. Frontend changes

- Replace the single linear entry point with `Enroll`, `Verify 1:1`, and `Identify 1:N` modes while retaining the existing consent and behavioral tasks.
- Add profile creation/selection, group creation/membership management, enrollment readiness/progress, and clear handling for missing profiles or groups with no ready templates.
- Submit to the FastAPI backend with retry/idempotency and visible server-confirmed status; remove Google Apps Script as the primary sink.
- For 1:1, show accept/reject/insufficient-quality, score versus threshold, modality quality, and retry guidance.
- For 1:N, show matched/no-match, the closest candidate, top-candidate ranking, score/margin, and retry guidance.
- Keep detailed behavioral charts available as optional session diagnostics, but never present them as authentication confidence.
- Generate TypeScript API types from OpenAPI and keep the collection payload schema shared through contract tests.
- Preserve accessibility, responsive layout, consent text, and a way to withdraw/delete a profile and its raw sessions.

## 9. Testing and acceptance gates

### Data and ML

- Golden XLSX import test covering all 9 sheets, missing keyboard modality, null releases, duplicate rows, non-monotonic timestamps, invalid JSON sequences, and join mismatches.
- Deterministic feature tests on synthetic keyboard/mouse paths; normalization and masks must contain no NaN/Inf values.
- Explicit leakage test proving a parent session exists in only one split and preprocessing is fit only on training data.
- Model forward/backward smoke tests for full, keyboard-only, mouse-only, short, and padded batches.
- Verification tests for genuine/impostor scoring, threshold boundaries, top-1 tie/margin behavior, empty groups, inactive profiles, and no-match.
- Reproducible tiny overfit test and artifact round-trip test asserting exported inference matches training-runtime inference within tolerance.

### Backend

- Migration tests against PostgreSQL/pgvector; repository and transaction tests for idempotency, soft deletion, membership, enrollment, and template replacement.
- API contract tests for success and every stable error code, payload/size limits, CORS, unavailable model, malformed sessions, and incompatible schema versions.
- Concurrency test ensuring simultaneous enrollment updates cannot lose or mix template versions.
- Performance target after warmup: p95 under 2 seconds for session embedding plus 1:1 scoring and under 3 seconds for a 10,000-profile group search on the deployment reference hardware.

### Frontend and end-to-end

- Component tests for all mode/quality/result states and generated API types.
- Playwright flows for create profile -> enroll, select profile -> 1:1 result, create/select group -> 1:N result, retry after upload failure, and no-match/insufficient-quality.
- End-to-end fixture run through frontend, API, database, active model, and audit record.

Promotion is blocked unless migrations/tests pass, artifact checksums match, metrics beat the baseline on independent sessions, the selected operating threshold meets its declared FAR target with an adequate confidence interval, and latency/missing-modality acceptance gates pass.

## 10. Implementation order

1. Bootstrap the root `uv` project, configuration, database, migrations, canonical schemas, and XLSX validation/import report.
2. Replace Google Sheets submission with versioned backend ingestion and generated frontend API types.
3. Implement feature extraction, windowing, leakage-safe splits, baseline, metrics, and calibration.
4. Implement/train/export the multimodal deep embedding model and model registry/promotion checks.
5. Implement profile templates, enrollment, 1:1 scoring, 1:N group search, and audit records.
6. Add frontend mode selection, profile/group management, enrollment progress, and verification result screens.
7. Add full automated tests, Docker Compose, observability, privacy controls, and operator documentation.
8. Collect repeated multi-day sessions, rerun evaluation/calibration, review error cohorts, and only then promote the first non-demo model.

## 11. Defaults and explicit non-goals

- This plan assumes a single-tenant research/demo deployment first; application user accounts and organization-level RBAC are deferred, while profile/group identifiers and auditability are included now.
- PostgreSQL/pgvector is the source of truth; Google Sheets is removed from the online verification path.
- The backend returns decisions and ranked candidates; raw embeddings are never exposed to the browser.
- The current workbook is never modified or treated as sufficient evidence of production accuracy.
- Face, voice, device fingerprinting, and continuous background authentication are out of scope for this release.
- No automatic template adaptation from rejected or low-confidence sessions.
