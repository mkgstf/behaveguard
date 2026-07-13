# BehaveGuard Development Training Report

Generated from `Behaveguard-client.xlsx` on 2026-07-13.

## Validity warning

The source contains 10 real sessions across 9 identities. `elrond` and `saruman` were confirmed to be the same person and are now merged under `saruman`, which has two sessions; the other identities have one session each. Each session was split chronologically into five non-overlapping pseudo-sessions for model development. No raw event belongs to more than one fold, but most windows from a person still share a device, day, and parent session. These results measure development separability and **must not be presented as cross-day authentication accuracy**.

## Experiment design

- 9 identities, 10 real sessions, 50 temporal windows, and 142 engineered features.
- Five-fold evaluation: each fold holds out one chronological window from every profile.
- Models: logistic regression, 3-nearest-neighbors, Random Forest, Extra Trees, and 16 RBF-SVM configurations.
- SVM grid: `C in {0.1, 1, 10, 50}` and `gamma in {scale, 0.001, 0.01, 0.1}`.
- Metrics: top-1 and top-3 identification, macro F1, pairwise verification ROC-AUC, and equal-error rate.
- Neural model: BiLSTM keyboard tower, TCN mouse tower, engineered-feature MLP, and a 128-dimensional fused embedding.

## Results

| Model | Top-1 | Top-3 | Verification AUC | EER |
|---|---:|---:|---:|---:|
| Random Forest | 96% | 100% | 0.9990 | 2.00% |
| Extra Trees | 94% | 100% | 0.9990 | 1.88% |
| Tuned RBF-SVM (`C=50`, `gamma=0.01`) | 82% | 98% | 0.9589 | 11.87% |
| 3-NN | 80% | 92% | 0.9421 | 9.75% |
| Logistic regression | 76% | 96% | 0.9498 | 9.62% |
| BiLSTM + TCN fusion | 90% held-window accuracy | — | — | — |

Random Forest made two errors across the 50 held windows: `arpit -> Vidhi` once and `Vidhi -> arpit` once. The previous `elrond`/`saruman` confusion disappeared because those labels represented the same identity rather than two confusable people.

## Modality ablation using the tuned SVM

| Inputs | Top-1 | Top-3 | Verification AUC | EER |
|---|---:|---:|---:|---:|
| Keyboard only | 78% | 96% | 0.9468 | 13.50% |
| Mouse only | 70% | 90% | 0.9138 | 18.00% |
| Keyboard + mouse | 82% | 98% | 0.9589 | 11.87% |

Keyboard behavior is currently more discriminative, but multimodal fusion improves both identification and verification. Mouse-only performance is still meaningful and provides a fallback for missing keyboard data such as the `Siya` session.

## Profile comparison findings

The closest full-session impostor pairs were:

- `Vidhi <-> Akshat`: 68.01%.
- `arpit -> Vidhi`: 66.09%.
- `Sarthak -> arpit`: 63.26%.
- `saruman -> arpit`: 43.60%; the merged two-session `saruman` centroid is no longer unusually close to another identity.

Testing every full session against all 9 identities ranked the correct profile first in 10/10 cases. The 62% development threshold accepts all 10 genuine sessions and rejects all 80 in-sample impostor claims. This threshold is active, but it still requires independent-session calibration before deployment.

## Saved artifacts

- `behavior_model.joblib`: online robust scaler, profile centroids, and tuned RBF-SVM.
- `benchmark_model.joblib`: best Extra Trees development benchmark.
- `behavior_neural.pt`: experimental BiLSTM + TCN window-trained checkpoint.
- `tuned_config.json`: selected SVM parameters and conservative development threshold.
- `experiment_report.json`: complete metrics, confusion matrices, ablations, and pairwise profile similarities.

## Next data requirement

Collect at least three sessions per identity on separate days, preferably five. `saruman` currently has two sessions; every other identity still needs repeated data. The next evaluation must split by real session and should include identity-disjoint testing, calibration confidence intervals, and TAR at fixed FAR targets before any production claim.
