from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

import numpy as np


def _finite(values: Iterable[Any]) -> np.ndarray:
    out = []
    for value in values:
        try:
            number = float(value)
            if math.isfinite(number):
                out.append(number)
        except (TypeError, ValueError):
            pass
    return np.asarray(out, dtype=np.float64)


def _stats(prefix: str, values: Iterable[Any]) -> dict[str, float]:
    arr = _finite(values)
    if arr.size == 0:
        return {f"{prefix}_{name}": 0.0 for name in ("mean", "std", "p10", "p50", "p90", "iqr")}
    q10, q25, q50, q75, q90 = np.percentile(arr, [10, 25, 50, 75, 90])
    return {
        f"{prefix}_mean": float(np.mean(arr)),
        f"{prefix}_std": float(np.std(arr)),
        f"{prefix}_p10": float(q10),
        f"{prefix}_p50": float(q50),
        f"{prefix}_p90": float(q90),
        f"{prefix}_iqr": float(q75 - q25),
    }


def _path_features(points: list[dict[str, Any]], prefix: str) -> dict[str, float]:
    if len(points) < 2:
        return {**_stats(f"{prefix}_speed", []), **_stats(f"{prefix}_turn", []), f"{prefix}_pause_ratio": 0.0}
    dx, dy, dt = [], [], []
    for a, b in zip(points, points[1:]):
        delta_t = max(float(b.get("ts", 0)) - float(a.get("ts", 0)), 1.0)
        dx.append(float(b.get("x", b.get("cursor_x", 0))) - float(a.get("x", a.get("cursor_x", 0))))
        dy.append(float(b.get("y", b.get("cursor_y", 0))) - float(a.get("y", a.get("cursor_y", 0))))
        dt.append(delta_t)
    speeds = np.hypot(dx, dy) / (np.asarray(dt) / 1000.0)
    angles = np.unwrap(np.arctan2(dy, dx))
    turns = np.abs(np.diff(angles)) if len(angles) > 1 else np.asarray([])
    return {
        **_stats(f"{prefix}_speed", speeds),
        **_stats(f"{prefix}_turn", turns),
        f"{prefix}_pause_ratio": float(np.mean(speeds < 30)) if speeds.size else 0.0,
    }


def extract_features(session: dict[str, Any]) -> dict[str, float]:
    keyboard = session.get("keyboard") or {}
    events = keyboard.get("events") or []
    ordered = sorted(events, key=lambda event: float(event.get("press_ts", 0)))
    dwell = [float(e["release_ts"]) - float(e["press_ts"]) for e in ordered if e.get("release_ts") is not None]
    iki = [float(b.get("press_ts", 0)) - float(a.get("press_ts", 0)) for a, b in zip(ordered, ordered[1:])]
    flight = [
        float(b.get("press_ts", 0)) - float(a.get("release_ts", a.get("press_ts", 0)))
        for a, b in zip(ordered, ordered[1:])
        if a.get("release_ts") is not None
    ]
    features: dict[str, float] = {
        **_stats("key_dwell", dwell),
        **_stats("key_iki", iki),
        **_stats("key_flight", flight),
        "key_count": float(len(ordered)),
        "key_backspace_rate": float(sum(e.get("key_id") == "backspace" for e in ordered) / max(len(ordered), 1)),
        "key_shift_rate": float(sum(bool(e.get("shift_held")) for e in ordered) / max(len(ordered), 1)),
        "key_space_rate": float(sum(e.get("key_category") == "space" for e in ordered) / max(len(ordered), 1)),
        "key_special_rate": float(sum(e.get("key_category") == "special" for e in ordered) / max(len(ordered), 1)),
    }

    mouse = session.get("mouse") or {}
    passive = mouse.get("passive_points") or []
    features.update(_path_features(passive, "passive"))
    features["passive_count"] = float(len(passive))

    dots = mouse.get("dot_trials") or []
    features.update(_stats("dot_travel", (trial.get("travel_time_ms") for trial in dots)))
    features.update(_stats("dot_error", (trial.get("error_px") for trial in dots)))
    features.update(_stats("dot_submove", ((trial.get("kinematics") or {}).get("sub_movement_count", trial.get("sub_movement_count")) for trial in dots)))
    features.update(_stats("dot_hover", ((trial.get("kinematics") or {}).get("hover_dwell_ms", trial.get("hover_dwell_ms")) for trial in dots)))

    drags = mouse.get("drag_trials") or []
    features.update(_stats("drag_duration", (trial.get("duration_ms") for trial in drags)))
    features.update(_stats("drag_submove", ((trial.get("kinematics") or {}).get("sub_movement_count", trial.get("sub_movement_count")) for trial in drags)))
    features["drag_success_rate"] = float(sum(bool(t.get("success")) for t in drags) / max(len(drags), 1))

    tracks = mouse.get("track_trials") or []
    for pattern in ("sinusoidal", "random_walk"):
        selected = [trial for trial in tracks if trial.get("pattern") == pattern]
        for name in ("mean_error_px", "rms_error_px", "lag_ms", "prediction_ratio", "tremor_px", "correlation_x", "correlation_y", "fatigue_delta_px"):
            features.update(_stats(f"track_{pattern}_{name}", ((trial.get("derived") or {}).get(name) for trial in selected)))

    return {name: float(value) if math.isfinite(float(value)) else 0.0 for name, value in sorted(features.items())}


def feature_vector(features: dict[str, float], names: list[str]) -> np.ndarray:
    return np.asarray([float(features.get(name, 0.0)) for name in names], dtype=np.float64)


def detailed_comparison(probe: dict[str, float], enrolled: list[dict[str, float]]) -> list[dict[str, Any]]:
    if not enrolled:
        return []
    categories = {
        "Keyboard rhythm": ["key_dwell", "key_iki", "key_flight", "key_backspace", "key_shift"],
        "Passive mouse": ["passive_speed", "passive_turn", "passive_pause"],
        "Click targets": ["dot_travel", "dot_error", "dot_submove", "dot_hover"],
        "Dragging": ["drag_duration", "drag_submove", "drag_success"],
        "Target tracking": ["track_sinusoidal", "track_random_walk"],
    }
    result = []
    for label, prefixes in categories.items():
        names = [name for name in probe if any(name.startswith(prefix) for prefix in prefixes)]
        distances = []
        for name in names:
            values = np.asarray([row.get(name, 0.0) for row in enrolled], dtype=float)
            center = float(np.mean(values))
            scale = max(float(np.std(values)), abs(center) * 0.15, 1.0)
            distances.append(abs(probe.get(name, 0.0) - center) / scale)
        similarity = 100.0 * math.exp(-float(np.mean(distances))) if distances else 0.0
        result.append({"category": label, "similarity": round(similarity, 1), "feature_count": len(names)})
    return result
