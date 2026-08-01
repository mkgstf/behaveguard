from __future__ import annotations

import numpy as np

from behaveguard.modeling import behavioral_drift


def _profile(count: int = 4) -> dict:
    return {
        "count": count,
        "feature_center": np.zeros(4),
        "feature_scale": np.ones(4),
    }


def test_drift_requires_three_independent_enrollments():
    result = behavioral_drift(np.zeros(4), _profile(count=2))

    assert result == {
        "status": "insufficient_baseline",
        "level": "unknown",
        "score": None,
        "outlier_feature_rate": None,
    }


def test_drift_labels_stable_and_high_probes():
    stable = behavioral_drift(np.asarray([0.1, -0.2, 0.3, 0.0]), _profile())
    high = behavioral_drift(np.asarray([5.0, -5.0, 6.0, -6.0]), _profile())

    assert stable["level"] == "stable"
    assert stable["outlier_feature_rate"] == 0.0
    assert high["level"] == "high"
    assert high["outlier_feature_rate"] == 1.0
