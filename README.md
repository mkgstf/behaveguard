# BehaveGuard

BehaveGuard is an integrated behavioral-authentication application with:

- Profile enrollment with automatic saved-model retraining.
- Detailed 1:1 behavioral verification.
- Ranked 1:N identification across any selected profiles.
- A quarantined verification-sample review queue with user identity feedback and admin-controlled promotion.
- A FastAPI backend, SQLite persistence, RBF-SVM/centroid scoring, and an optional BiLSTM + TCN fusion model.
- A Next.js admin dashboard for enrollment health, profile similarity, blacklisting, and deletion.

## Start the backend

```bash
uv sync --extra dev
uv run behaveguard import-xlsx Behaveguard-client.xlsx
uv run behaveguard serve --reload
```

The workbook import is idempotent. In the development workbook, `elrond` is a legacy alias for `saruman`; both rows are deliberately canonicalized to one identity. The current sample therefore initializes 9 profiles from 10 sessions.

## Start the frontend

```bash
cd behaveguard-client
npm install
npm run dev
```

Open `http://localhost:3000`. The frontend calls `http://127.0.0.1:8000/api/v1` by default. Set `NEXT_PUBLIC_API_URL` to change the API location.

## Training and tests

```bash
uv run behaveguard train
uv run behaveguard experiment --windows 5 --neural-epochs 25
uv run behaveguard status
uv run pytest
cd behaveguard-client && npm run lint && npm run build
```

Every enrollment updates the feature scaler, profile centroids, and RBF-SVM artifact. Once there are at least two profiles with two independent sessions each and six sessions overall, enrollment also trains and saves the BiLSTM keyboard + TCN mouse fusion model.

Verification and identification probes are saved separately from enrollment data. The result screen asks who produced the sample; that answer places it in the admin review queue. An administrator must assign the identity and approve the sample before it becomes a training session, then explicitly use **retrain model** to rebuild the classical and neural artifacts. Rejected, unlisted, and unreviewed samples never enter training.

Before approval, the admin queue compares each identification run with the selected trained profile. It shows the original model similarity/certainty, weighted feature coincidence, keyboard and mouse category overlap, and side-by-side behavioral measurements such as WPM, dwell/flight timing, mouse speed, click error, tracking error, tremor, and drag performance. Selecting a different profile recalculates these statistics server-side without exposing the raw event stream to the browser.

The supplied workbook has one session per person, so its accuracy is suitable only for development. Collect at least three sessions per profile, preferably five across multiple days, before interpreting certainty as an operational authentication result.

The experiment command creates `artifacts/experiment_report.json`, tunes classical models and the RBF-SVM, runs keyboard/mouse ablations and profile comparisons, and saves an explicitly experimental BiLSTM + TCN artifact.

## Data and privacy

Raw workbooks, SQLite databases, and trained artifacts are intentionally excluded from this public repository because behavioral telemetry is biometric data. To run the project, place a consented workbook at `Behaveguard-client.xlsx`, or enroll fresh profiles through the application. Generated data and models remain under the ignored `data/` and `artifacts/` directories.

Do not interpret the dashboard's certainty as a calibrated security guarantee until every identity has multiple independent enrollment sessions and the operating threshold has been validated on held-out people and devices.
