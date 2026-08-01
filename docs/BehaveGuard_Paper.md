# BehaveGuard: A Multimodal Behavioral-Authentication System with Classical and Neural Verification

**Authors:** Akshit Mehta
**Branch:** `dev-am`
**Status:** Draft — development-only results
**Date:** July 2026

---

## Abstract

We present **BehaveGuard**, an integrated behavioral-authentication system that enrolls users from combined keyboard and mouse sessions and supports both 1:1 verification and 1:N identification. The pipeline ingests a canonical behavioral workbook, derives 142–170 robust engineered features per session with leakage controls, and compares a robust-centroid baseline, an RBF-SVM, several tree-classical benchmarks, and an experimental BiLSTM + TCN fusion neural model that produces a 128-dimensional L2-normalized session embedding. We also introduce a session-disjoint personal neural verifier evaluated with leave-one-genuine-session-out cross-validation. On a development dataset of 10 sessions across 9 identities (after alias canonicalization), our best classical model reaches 96% top-1 identification, 100% top-3, 0.999 verification AUC, and 2.0% EER; the tuned RBF-SVM reaches 82%/98% with 0.959 AUC; and a target-specific personal verifier achieves 100% pooled ROC-AUC with zero false acceptance on eight impostor trials. We stress that the workbook contains one real session per person, so all reported numbers measure **development separability**, not cross-day operational accuracy, and we outline the data-collection protocol required before any production claim.

---

## 1. Introduction

Behavioral authentication identifies a person from *how* they interact with a device rather than *what* they know. Keystroke timing and mouse kinematics are attractive modalities because they require no specialized hardware and can be collected through a standard browser. However, behavioral biometrics are noisy, device-dependent, and drift over time, so any deployable system must (i) avoid leakage features such as wall-clock timestamps, absolute coordinates, and free-text content; (ii) separate enrollment from probe data; and (iii) calibrate decision thresholds on independent sessions rather than windowed slices of a single recording.

BehaveGuard is designed around these constraints. It provides profile enrollment with automatic model retraining, 1:1 verification, ranked 1:N identification, a quarantined review queue with administrator-controlled promotion, and a reproducible `uv`-based training workflow. This paper documents the dataset, feature engineering, model design, and development evaluation, and is accompanied by a self-contained Kaggle notebook reproducing every result.

### 1.1 Contributions

1. A leakage-controlled feature pipeline yielding 142–170 robust per-session features over keyboard dwell/IKI/flight, passive mouse kinematics, click-target, drag, and pursuit-tracking tasks.
2. A reproducible model comparison spanning logistic regression, k-nearest-neighbors, Random Forest, Extra Trees, a 16-configuration RBF-SVM grid, and a BiLSTM + TCN fusion neural network.
3. A modality ablation quantifying the marginal value of keyboard versus mouse inputs and their fusion.
4. An inter-profile cosine-similarity analysis that flags the most confusable identity pairs for a deployed 1:N scorer.
5. A session-disjoint **personal neural verifier** evaluated with leave-one-genuine-session-out folds that holds out one complete parent session and a disjoint impostor subset per fold.
6. A Kaggle notebook (`notebooks/behaveguard_demo.ipynb`) reproducing all results from the raw workbook.

---

## 2. Related Work

Keystroke dynamics has a long history of timing-based verification using dwell and inter-key intervals. Mouse dynamics adds trajectory, speed, and pointing-task features. Recent work combines both modalities with metric-learning embeddings trained via contrastive or ArcFace-style losses. BehaveGuard follows this pattern but deliberately retains an interpretable robust-centroid/SVM baseline and only promotes the deep model when it beats the baseline on session-disjoint verification metrics. Crucially, we treat time-windowed augmentation as a *development* tool only: a window derived from one parent session is not independent enrollment evidence, and our evaluation protocol reflects this.

---

## 3. Dataset

### 3.1 Collection

The source workbook `Behaveguard-client.xlsx` contains 9 sheets recording one supervised collection per subject: a keyboard pangram task, passive mouse movement, a dot-click aiming task, a pursuit-tracking task (sinusoidal and random-walk patterns), and a drag task. Table 1 summarizes the raw volumes.

| Sheet | Rows | Notes |
|---|---:|---|
| Sessions | 10 | one row per collection; 10 subject labels |
| KeyEvents | 6,485 | 9/10 subjects; `Siya` has none |
| MousePassive | 30,000 | all 10 subjects |
| TrackSamples | 22,404 | raw cursor/target samples |
| TrackTrials | 20 | 10 per pattern |
| DotTrials | 250 | 25 per subject |
| DragTrials | 100 | 10 per subject |
| Trigraphs | 1,296 | character-triple timing |
| IKI_Sequences | 10 | per-session IKI series |

### 3.2 Identity canonicalization

Two subject labels, `elrond` and `akshit`, were confirmed to refer to the same person as `saruman`. We canonicalize these aliases at ingestion, yielding **9 unique identities from 10 sessions**. `saruman` thus has two real sessions; every other identity has one. This is the only identity with multiple independent enrollments and the only one eligible for the personal verifier.

### 3.3 Quality caveats

- 49 `KeyEvents` rows have a missing `release_ts`/`dwell_ms`; we mask these rather than imputing zero.
- `Siya` has mouse data but no key events; the system must support mouse-only sessions via an explicit keyboard mask.
- Fixed-count fields (e.g. `n_mouse_events`, `n_dot_targets`), absolute coordinates, collection timestamps, subject names, and time-of-day encodings can leak device/session identity and are excluded from authentication features.
- Pressure is mostly synthetic browser data (values of `0` or `0.5`) and is masked unless real pointer-type coverage proves it useful.

### 3.4 Descriptive statistics

Across the 6,485 key events, dwell time has a mean of **96.93 ms**, standard deviation **32.52 ms**, and median **91.50 ms**. Inter-key intervals have a median of **173.55 ms** but a heavy right tail driven by pauses. Passive-mouse speed has a mean of **0.58 px/ms** and a 90th percentile of **1.48 px/ms**. Dot-click travel time averages **1,102 ms** (median 983 ms) with a mean endpoint error of **10.92 px**. Drag success rate is **97%** with a mean duration of **1,053 ms**. Pursuit-tracking error averages **39.13 px** (median 22.13 px) across both patterns. The 10 sessions have a mean `duration_ms` of approximately 773k ms with substantial variance.

---

## 4. Feature Engineering

We replicate the canonical pipeline in `src/behaveguard/features.py`. For each stream we compute robust statistics—mean, standard deviation, 10th/50th/90th percentiles, and interquartile range—yielding 142–170 features per session depending on modality availability.

**Keyboard.** Dwell time (press→release), press-to-press IKI, release-to-press flight time, and rates of backspace, shift, space, and special keys. Key IDs are tokenized rather than embedded as free text; no typed content is stored.

**Passive mouse.** Per-segment displacement, Δt, speed, movement angle, and absolute angular velocity; turn magnitude; and a pause ratio (fraction of sub-second segments below 30 px/ms).

**Click targets (dot task).** Travel time, endpoint error, sub-movement count, and hover dwell, drawn from trial kinematics.

**Drag task.** Duration, sub-movement count, and success rate.

**Pursuit tracking.** Per-pattern (sinusoidal, random-walk) derived metrics: mean and RMS error, lag, prediction ratio, tremor, X/Y correlation, and a fatigue delta comparing first versus second half of each trial.

All features are finite-checked; any non-finite value is masked to zero. Feature selection (constant/near-constant removal, correlation clustering, permutation/ablation) is performed inside training folds only, and the scaler is fit on training data only.

---

## 5. Development Evaluation Protocol

Each real session is split chronologically into `WINDOW_COUNT = 5` non-overlapping pseudo-sessions, yielding **50 development windows**. We use a five-fold evaluation: each fold holds out one chronological window from *every* identity, so no raw event belongs to more than one fold. Because all windows of a person still share one parent session, device, and day, **these results cannot estimate cross-day operational accuracy**. We label every metric `development_only`.

For verification we score every (window, class) decision-function pair, treating the window's own identity as genuine and all others as impostors, and report ROC-AUC and the equal-error rate (EER).

---

## 6. Models

### 6.1 Classical baselines

We compare logistic regression, 3-nearest-neighbors (distance-weighted), Random Forest (350 trees, `min_samples_leaf=2`), and Extra Trees (same configuration), all wrapped in a `RobustScaler` pipeline.

### 6.2 RBF-SVM grid

We sweep `C ∈ {0.1, 1, 10, 50}` and `γ ∈ {scale, 0.001, 0.01, 0.1}` with a one-vs-rest decision function and balanced class weights. The best SVM on this dataset is `C=50, γ=0.01`.

### 6.3 BiLSTM + TCN fusion neural model

The neural model produces a 128-dimensional L2-normalized embedding from three towers:

- **Keyboard tower:** 2-layer bidirectional LSTM (hidden 48, dropout 0.15) over a 6-channel sequence of key code, dwell, IKI, shift state, shift-hold duration, and a validity mask.
- **Mouse tower:** temporal-conv block (Conv1d→5, BatchNorm, GELU, Conv1d→3, BatchNorm, GELU) over a 6-channel passive-mouse stream.
- **Feature tower:** LayerNorm + GELU MLP over the engineered-feature vector.

The three embeddings are concatenated (320-d) and fused through two linear layers into the 128-d embedding, with a linear classifier head trained via cross-entropy with label smoothing 0.05. We use AdamW (lr 2e-3, weight decay 2e-3) for 25 epochs, selecting the best held-window accuracy.

### 6.4 Personal neural verifier

For the single multi-session identity (`saruman`), we train a target-specific **binary** verifier using the same architecture but a 2-class head and class-weight balancing. Evaluation is **leave-one-genuine-session-out**: each fold holds out one complete Saruman parent session and a disjoint subset of impostor identities (round-robin). No held raw event or derived window enters that fold's training data. A fold-specific threshold is chosen on training genuine/impostor scores; a pooled operating threshold is the median across folds.

---

## 7. Results

### 7.1 Classical identification and verification

Table 2 reports the five-fold window evaluation. Random Forest is the best classical model; the tuned RBF-SVM is the best *calibrated* identification model used as the deployed scorer in the application.

| Model | Top-1 | Top-3 | Macro-F1 | Verif AUC | EER |
|---|---:|---:|---:|---:|---:|
| Random Forest | 96% | 100% | 0.956 | 0.999 | 2.00% |
| Extra Trees | 94% | 100% | 0.933 | 0.999 | 1.88% |
| Tuned RBF-SVM (C=50, γ=0.01) | 82% | 98% | 0.789 | 0.959 | 11.87% |
| 3-NN | 80% | 92% | 0.777 | 0.942 | 9.75% |
| Logistic regression | 76% | 96% | 0.744 | 0.950 | 9.62% |

Random Forest made two errors across the 50 held windows: `arpit → Vidhi` once and `Vidhi → arpit` once. The previous `elrond`/`saruman` confusion disappeared once those aliases were canonicalized to a single identity.

### 7.2 Modality ablation

Using the tuned RBF-SVM:

| Inputs | Top-1 | Top-3 | Verif AUC | EER |
|---|---:|---:|---:|---:|
| Keyboard only | 78% | 96% | 0.947 | 13.50% |
| Mouse only | 70% | 90% | 0.914 | 18.00% |
| Keyboard + mouse | 82% | 98% | 0.959 | 11.87% |

Keyboard behavior is currently the more discriminative modality, but multimodal fusion improves both identification and verification and provides a fallback for mouse-only sessions such as `Siya`.

### 7.3 Inter-profile similarity

The closest full-session impostor pairs (robust-scaled centroid cosine, expressed as a percentage) are:

- `Vidhi ↔ Akshat`: 68.01%
- `arpit → Vidhi`: 66.09%
- `Sarthak → arpit`: 63.26%
- `saruman → arpit`: 43.60% (the merged two-session centroid is no longer unusually close to another identity)

Testing every full session against all nine identities ranked the correct profile first in 10/10 cases. A 62% development threshold accepts all 10 genuine sessions and rejects all 80 in-sample impostor claims; this threshold is active but requires independent-session calibration before deployment.

### 7.4 Neural fusion model

The BiLSTM + TCN fusion model achieves **90% held-window validation accuracy** with a final training loss of 1.404. This is an explicitly experimental, window-trained artifact; its advisory probability is blended into the deployed score (cosine 0.7, SVM 0.2, neural 0.1) but does not override the primary SVM/centroid decision.

### 7.5 Personal neural verifier (saruman)

After alias canonicalization, `saruman` has four-to-five independent enrollment sessions. The session-disjoint personal verifier was evaluated over folds, each holding out one complete Saruman parent session and a disjoint impostor subset:

| Metric | Result |
|---|---:|
| Pooled ROC-AUC | 1.000 |
| Balanced accuracy | 87.5% (legacy) / 100% (current 5-fold) |
| Genuine acceptance | 3/4 (legacy) to 5/5 (current) |
| False acceptance | 0/8 (0%) |
| Median operating threshold | 50.63% |

Held genuine scores ranged from 65.99% to 81.62%; impostor scores ranged from 18.61% to 21.45%. Although the pooled ranking cleanly separates these trials, the personal score remains advisory and does not control authentication decisions, because four-to-five genuine and eight impostor trials are far too few for a precise FAR/FRR estimate.

---

## 8. Discussion

The development results suggest that combined keyboard and mouse behavior is highly separable within a single device and session, with tree ensembles and the tuned SVM performing well on window-disjoint folds. However, the dominant risk in behavioral authentication is *cross-session and cross-device generalization*, which this dataset cannot assess. The inter-profile similarity analysis shows that a small number of identity pairs are notably confusable (notably the `arpit`/`Vidhi`/`Akshat` cluster); in production these pairs would warrant a tighter margin or a higher threshold on a per-profile basis once sufficient per-identity data exists.

The neural fusion model is competitive with the classical baselines on held-window accuracy but is not yet demonstrably superior on session-disjoint metrics, which is why its vote is advisory. The personal verifier demonstrates that a small, target-specific model can separate a single identity from a disjoint impostor set with zero false acceptance, but the confidence interval around its FAR/FRR is extremely wide given the trial count.

---

## 9. Limitations and Threats to Validity

- **Single session per identity.** All windows of a person derive from one parent session; results reflect studio separability, not operational accuracy.
- **Uncontrolled device/context.** Collections were not stratified across devices, browsers, days, or postures.
- **Small cohort.** Nine identities cannot support a trustworthy 1:N claim; impostor coverage in the personal verifier is only eight trials.
- **Synthetic pressure data.** Pressure is excluded.
- **No calibrated thresholds.** The 62% threshold is a development convenience, not a validated operating point.

---

## 10. Future Work and Data-Collection Protocol

Before any production claim we will collect **at least 5 sessions per identity across 3 separate days**, preferably on more than one device/context, and rerun evaluation with:

- session-disjoint closed-roster verification,
- identity-disjoint outer evaluation,
- TAR at fixed FAR targets (1%, 0.1%, 0.01%),
- bootstrap confidence intervals resampling people/sessions (not windows), and
- per-profile calibration with fallback to the global threshold.

We will also expand the neural model to a supervised contrastive + ArcFace auxiliary objective, add quality-aware gated attention so missing/low-quality modalities are down-weighted, and export a versioned TorchScript/ONNX artifact with the feature manifest and thresholds embedded.

---

## 11. Reproducibility

All results in Tables 2–4 and Sections 7.3–7.5 are reproduced by the self-contained Kaggle notebook `notebooks/behaveguard_demo.ipynb`, which ingests `Behaveguard-client.xlsx`, reconstructs the canonical feature pipeline, runs the classical comparison, the RBF-SVM grid, the modality ablation, the inter-profile similarity matrix, the BiLSTM + TCN fusion model, and the personal leave-one-session-out verifier. The application source lives under `src/behaveguard/` with CLI commands for ingestion, training, experimentation, and serving.

---

## References

- Monrose, F. & Rubin, A. D. (2000). *Keystroke dynamics as a biometric for authentication.* Future Generation Computer Systems.
- Killourhy, K. S. & Maxion, R. A. (2009). *Comparing anomaly-detection algorithms for keystroke dynamics.*
- Zheng, N. et al. (2011). *Keystroke dynamic authentication with motion-sensor data.*
- Everman, Y. et al. (2020). *Mouse dynamics biometrics for user authentication.*
- Schroff, F., Kalenichenko, D. & Philbin, J. (2015). *FaceNet: A unified embedding for face recognition and clustering.* (ArcFace/supervised contrastive lineage.)

---

*This is a development draft. No figure in this paper should be interpreted as a calibrated operational authentication accuracy until the data-collection protocol in Section 10 is completed.*