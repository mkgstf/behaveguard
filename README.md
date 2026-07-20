# BehaveGuard

BehaveGuard is an integrated behavioral-authentication application with:

- Profile enrollment with automatic saved-model retraining.
- Detailed 1:1 behavioral verification.
- Ranked 1:N identification across any selected profiles.
- A quarantined verification-sample review queue with user identity feedback and admin-controlled promotion.
- A FastAPI backend, PostgreSQL (+pgvector) persistence, RBF-SVM/centroid scoring, and an optional BiLSTM + TCN fusion model.
- A Next.js admin dashboard for enrollment health, profile similarity, blacklisting, and deletion.

> **Phase 0 of the production migration**: persistence moved from a local SQLite file to PostgreSQL (with the `pgvector` extension) plus a Redis instance (provisioned now; not yet used by the app — job-queue/cache wiring lands in a later phase). Schema is managed by Alembic. See `docker-compose.yml`.

## 1. Start the data layer (PostgreSQL + Redis)

```bash
docker compose up -d
```

This starts Postgres 16 (with `pgvector` pre-installed) on `localhost:5432` and Redis on `localhost:6379`, matching the defaults in `behaveguard.config` (`DATABASE_URL`, `REDIS_URL`). Override either with an environment variable to point at a different instance (e.g. a staging RDS/Cloud SQL database).

Apply the schema:

```bash
uv sync --extra dev
uv run alembic upgrade head
```

`alembic upgrade head` is the source of truth for schema changes going forward. `database.init_db()` still runs `CREATE TABLE IF NOT EXISTS`-equivalent logic on startup as a dev-convenience fallback, but production deployments should rely on Alembic migrations, not on that fallback, to change the schema.

### Migrating an existing SQLite dev database

If you have an existing `data/behaveguard.db` from before this change:

```bash
uv run python scripts/migrate_sqlite_to_postgres.py --dry-run   # preview counts
uv run python scripts/migrate_sqlite_to_postgres.py             # migrate for real
```

The script preserves original ids, timestamps, and cross-table references (e.g. `review_samples.promoted_session_id`) exactly, and is safe to re-run — rows that already exist in Postgres (matched by id) are skipped.

## 2. Start the backend

```bash
uv run behaveguard import-xlsx Behaveguard-client.xlsx
uv run behaveguard serve --reload
```

The workbook import is idempotent. `elrond` and `akshit` are known aliases for the canonical `saruman` identity; those labels are deliberately canonicalized rather than trained as separate people. The original development workbook therefore initializes 9 profiles from 10 sessions.

## 3. Auth (Phase 1)

Every API route except `/health` and `/auth/*` now requires a logged-in user. There is **no admin-creation route** — every account, including admins, is created identically via self-service register or Google login; the only difference is a one-time role promotion run directly against the database.

**Environment variables** (all optional for local dev — see defaults in `config.py`; set real values before deploying anywhere reachable):

```bash
JWT_SECRET_KEY=<a long random string>       # required in any non-local environment
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=30
CLAIM_TOKEN_EXPIRE_DAYS=7

# Only needed for "Sign in with Google" — password register/login work without these.
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback
FRONTEND_URL=http://localhost:3000
```

To enable Google login: in Google Cloud Console → **APIs & Services → Credentials → Create Credentials → OAuth client ID → Web application**, add `http://localhost:8000/api/v1/auth/google/callback` as an authorized redirect URI, and copy the generated Client ID/Secret into the env vars above.

**Creating the (two) admin accounts** — register normally through the app first, then:

```bash
uv run behaveguard promote-admin admin@example.com --role platform_admin
```

**Linking a pre-existing/legacy profile** (e.g. one created by `import-xlsx`) to its real owner's new account:

```bash
uv run behaveguard generate-claim-token saruman
# -> prints a one-time token; send it to that person yourself (email/Slack/in person)
```

They register or log in normally, then call `POST /api/v1/profiles/claim` with `{"token": "..."}` while authenticated.

## Start the frontend

```bash
cd behaveguard-client
npm install
npm run dev
```

Open `http://localhost:3000`. The frontend uses the same-origin `/api/v1` path, which Next.js proxies to `http://127.0.0.1:8000` by default. Set server-side `BACKEND_URL` to change the proxy destination, or `NEXT_PUBLIC_API_URL` only when intentionally serving the API from a separate public origin.

The frontend now has a full login/register flow, Google sign-in, and a "claim a profile" screen (see below) — no need to hit `/api/v1/auth/*` directly anymore.

## 4. What changed in Phase 2 (auto-enroll, no review queue, auto-merge)

- **1:1 self-verification no longer creates a review-queue entry.** Login already answers "who is this," so there's nothing left for a human reviewer to confirm. A confident match (similarity ≥ `AUTO_ENROLLMENT_SIMILARITY_THRESHOLD`, default 85%) on your *own* profile is automatically folded in as an additional enrollment sample — the profile keeps improving every time you verify successfully, with no admin action required. The frontend's result screen shows this via an "auto-enrolled" indicator.
- **Duplicate profiles are merged automatically**, not via a human-reviewed queue. `uv run behaveguard auto-merge-scan` (or `POST /api/v1/admin/merge/scan`) compares every active profile's centroid and merges anything above `AUTO_MERGE_SIMILARITY_THRESHOLD` (default 0.97, conservative on purpose). Every merge is logged as a reversible `MergeEvent` — undo one with `uv run behaveguard revert-merge <event_id>` or `POST /api/v1/admin/merge/{id}/revert`.
- The old `review_samples` quarantine table/endpoints are untouched in the schema (so historical data isn't lost) but nothing new is written to them by `/verify` or `/identify` anymore.

## 5. What changed in Phase 3 (async retraining) + Phase 4 (rate limiting & security alerts)

**Async neural retraining.** The classical model (RobustScaler + centroid + SVM) is still refit inline on every enroll/verify/merge — it's cheap numpy work, and keeping it synchronous means your very next verification is scored against an up-to-date model immediately. The **neural fusion model** (real PyTorch training epochs, the actually slow part) is no longer trained inline:

- `enroll`, a confident auto-enrollment inside `verify`, `POST /admin/retrain`, and the auto-merge scan all now call `enqueue_retrain_neural(...)` instead of `train_neural(...)` directly — this appends a job to a Redis Stream and returns immediately. The response includes a `neural_retrain_job_id` instead of an inline training result.
- A **worker** consumes that stream and does the actual training. Locally, `uv run behaveguard serve` starts this worker automatically as a background thread — no second terminal needed. This is a deliberate local-dev shortcut; the eventual cloud deployment splits the worker into its own independent service/container (`uv run behaveguard worker`, already available standalone for exactly this) so the API and worker can scale and restart independently.
- **Promotion gate**: the worker doesn't blindly overwrite the live model. It trains a candidate on a held-out split (most recent session held out per profile with ≥3 sessions), evaluates it, and only promotes it over the currently active model (tracked in the `model_versions` table) if it's at least as good on held-out accuracy. A worse candidate is kept as `status='candidate'` — visible via `GET /api/v1/admin/model-versions` — rather than silently discarded or silently replacing a working model.
- `GET /api/v1/admin/jobs` shows recent job statuses (queued/running/done/failed) from the admin dashboard's new "Jobs & Security" panel.
- If a worker crashes mid-job, the unacknowledged job is automatically reclaimed by the next poll (Redis Streams' `XAUTOCLAIM`) rather than being silently lost.

**Rate limiting & passive security signals.** All Redis-backed, all per-minute/IP or per-minute/profile fixed windows:

- `/auth/login` and `/auth/register` are limited to `RATE_LIMIT_LOGIN_PER_MINUTE` (default 5) attempts per IP per minute; `/verify/{profile_id}` to `RATE_LIMIT_VERIFY_PER_MINUTE` (default 5) attempts per profile per minute. Exceeding either returns `429`.
- Nothing else blocks a request — the following are **passive** signals only, written to the `security_alerts` table and surfaced on the admin dashboard for a human to look at, never blocking the triggering request itself:
  - **`brute_force`** — raised once a key gets rate-limit-blocked 3 times within an hour (deduped, so it doesn't spam one alert per blocked request).
  - **`replay_suspected`** — raised when a verification submits the exact same raw payload (hashed) as a previous submission for that profile — a live person doesn't type/move identically twice.
  - **`far_spike`** — raised when several recent verification attempts for a profile cluster just under the accept threshold, a pattern consistent with probing for the boundary rather than natural variation.
- `GET /api/v1/admin/security-alerts` (optionally `?status=open|ack|dismissed|all`) and `PATCH /api/v1/admin/security-alerts/{id}` (`{"status": "ack"}` or `{"status": "dismissed"}`) manage them.

New env vars (see `config.py` for defaults): `RATE_LIMIT_LOGIN_PER_MINUTE`, `RATE_LIMIT_VERIFY_PER_MINUTE`, `REPLAY_DETECTION_TTL_SECONDS`, `RETRAIN_JOB_CLAIM_TIMEOUT_MS`, `NEURAL_RETRAIN_EPOCHS`.

## Temporary laptop hosting with Cloudflare Tunnel

Run the backend and production frontend locally, then point one Cloudflare Tunnel hostname at the frontend. The same-origin rewrite keeps the backend private:

```bash
uv run behaveguard serve
cd behaveguard-client && npm run build && npm run start -- --hostname 127.0.0.1 --port 3000
cloudflared tunnel run behaveguard
```


The local Cloudflare configuration maps `behave.amehta.space` to `http://127.0.0.1:3000`. The site is available only while the laptop is awake, connected, and all three processes are running.

## Training and tests

```bash
uv run behaveguard train
uv run behaveguard experiment --windows 5 --neural-epochs 25
uv run behaveguard personal-neural saruman --epochs 25 --windows 4
uv run behaveguard status
uv run pytest
cd behaveguard-client && npm run lint && npm run build
```

Every enrollment updates the feature scaler, profile centroids, and RBF-SVM artifact. Once there are at least two profiles with two independent sessions each and six sessions overall, enrollment also trains and saves the BiLSTM keyboard + TCN mouse fusion model.

Verification and identification probes are saved separately from enrollment data. The result screen asks who produced the sample; that answer places it in the admin review queue. An administrator must assign the identity and approve the sample before it becomes a training session, then explicitly use **retrain model** to rebuild the classical and neural artifacts. Rejected, unlisted, and unreviewed samples never enter training.

Before approval, the admin queue compares each identification run with the selected trained profile. It shows the original model similarity/certainty, weighted feature coincidence, keyboard and mouse category overlap, and side-by-side behavioral measurements such as WPM, dwell/flight timing, mouse speed, click error, tracking error, tremor, and drag performance. Selecting a different profile recalculates these statistics server-side without exposing the raw event stream to the browser.

The supplied workbook has one session per person, so its accuracy is suitable only for development. Collect at least three sessions per profile, preferably five across multiple days, before interpreting certainty as an operational authentication result.

The experiment command creates `artifacts/experiment_report.json`, tunes classical models and the RBF-SVM, runs keyboard/mouse ablations and profile comparisons, and saves an explicitly experimental BiLSTM + TCN artifact.

The `personal-neural` command trains a target-specific binary verifier when one identity has at least three independent sessions and at least four distinct impostor identities are available. Its outer evaluation holds out one complete genuine parent session and a disjoint subset of impostor identities per fold. Artifacts are stored per profile, so training another identity preserves existing personal verifiers. The saved personal vote is advisory and does not override the primary SVM/centroid decision.

## Data and privacy

Raw workbooks, SQLite databases, and trained artifacts are intentionally excluded from this public repository because behavioral telemetry is biometric data. To run the project, place a consented workbook at `Behaveguard-client.xlsx`, or enroll fresh profiles through the application. Generated data and models remain under the ignored `data/` and `artifacts/` directories.

Do not interpret the dashboard's certainty as a calibrated security guarantee until every identity has multiple independent enrollment sessions and the operating threshold has been validated on held-out people and devices.
