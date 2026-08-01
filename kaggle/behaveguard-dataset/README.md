# BehaveGuard Multimodal Behavioral Authentication Dataset

## Overview

This is a privacy-preserving research export of keyboard timing and mouse dynamics collected through the BehaveGuard browser tasks. It contains **10 sessions**, **9 anonymized candidates**, **6,485 key events**, and **30,000 passive mouse samples**.

The package supports exploratory analysis, multimodal feature engineering, closed-set identification, one-vs-rest verification, modality ablation, calibration analysis, and sequence-model experiments. `window_features.csv` contains 50 chronological pseudo-samples and 133 engineered features.

## Privacy transformations

- Candidate names and known aliases are merged locally, then replaced by opaque IDs.
- Collection timestamps are removed and session IDs are non-chronological pseudonyms.
- Literal key values are replaced by opaque key tokens.
- Absolute pointer, click, target, and screen coordinates are removed.
- Only relative event timing, movement deltas, target offsets/errors, and aggregate task metrics remain.
- The reversible alias configuration and pseudonym salt are excluded from this package.

These transformations reduce disclosure risk but do **not** make behavioral biometrics non-sensitive. Do not use this dataset to identify real people or make consequential decisions.

## Files

| File | Unit of observation | Rows |
|---|---|---:|
| `sessions.csv` | collection session | 10 |
| `key_events.csv` | key press/release event | 6,485 |
| `mouse_passive.csv` | passive pointer delta sample | 30,000 |
| `track_samples.csv` | pursuit-task offset sample | 22,404 |
| `track_trials.csv` | pursuit task trial | 20 |
| `dot_trials.csv` | point-and-click trial | 250 |
| `drag_trials.csv` | drag-and-drop trial | 100 |
| `session_features.csv` | full-session feature vector | 10 |
| `window_features.csv` | chronological within-session window | 50 |

All times are milliseconds, distances are pixels, angles are degrees, and rates are fractions unless the column name says otherwise.

## Evaluation warning

Most candidates currently contribute one real session. Splitting one session into windows enables a **within-session development benchmark**, but it does not estimate cross-day authentication accuracy. Report parent-session counts, keep chronological windows non-overlapping, and label all results as development-only. A production study needs multiple independently collected sessions per candidate across days, devices, browsers, and physical conditions.

## Suggested Kaggle task

Use the accompanying notebook to compare robust logistic regression, k-nearest neighbors, RBF-SVM, random forest, Extra Trees, and a BiLSTM+TCN fusion model. Recommended metrics are balanced accuracy and macro-F1 for identification, plus ROC-AUC, equal-error rate, false-accept rate, and false-reject rate for verification.

## License and permitted use

The package uses a custom research-demonstration notice in `LICENSE_DATA.md`. Before making the dataset public, the publisher is responsible for confirming participant consent and the legal basis for releasing biometric-adjacent data.
