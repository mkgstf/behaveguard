"""Build the privacy-preserving BehaveGuard Kaggle dataset package.

The raw workbook is intentionally gitignored. This exporter removes names,
wall-clock timestamps, literal keys, absolute pointer coordinates, synthetic
pressure, and redundant derived sheets. It emits linked event tables plus
session- and window-level feature matrices for reproducible modeling.

Usage:
    uv run python scripts/export_kaggle_dataset.py

The optional local privacy configuration is never published. It can contain:

    {"pseudonym_salt": "a long random string", "alias_groups": [["alias-a", "alias-b"]]}

If it is absent, labels are still pseudonymized but aliases are not merged.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO / "Behaveguard-client.xlsx"
DEFAULT_OUTPUT = REPO / "kaggle" / "behaveguard-dataset"
DEFAULT_PRIVACY_CONFIG = REPO / ".kaggle_export.local.json"
WINDOW_COUNT = 5


def _normalize_label(value: object) -> str:
    return str(value).strip().casefold()


def build_alias_lookup(alias_groups: Iterable[Iterable[str]]) -> dict[str, str]:
    """Return alias -> canonical label without exposing policy in public data."""
    lookup: dict[str, str] = {}
    for group in alias_groups:
        normalized = [_normalize_label(value) for value in group if str(value).strip()]
        if not normalized:
            continue
        canonical = normalized[0]
        for alias in normalized:
            existing = lookup.get(alias)
            if existing is not None and existing != canonical:
                raise ValueError(f"Alias {alias!r} appears in multiple groups")
            lookup[alias] = canonical
    return lookup


def canonicalize(label: object, alias_lookup: dict[str, str]) -> str:
    normalized = _normalize_label(label)
    return alias_lookup.get(normalized, normalized)


def _digest(value: str, salt: str) -> str:
    return hmac.new(salt.encode(), value.encode(), hashlib.sha256).hexdigest()


def build_pseudonym_map(
    raw_labels: Iterable[object], alias_lookup: dict[str, str], salt: str
) -> dict[str, str]:
    """Map canonical labels to stable opaque IDs ordered by keyed digest."""
    canonical = {canonicalize(label, alias_lookup) for label in raw_labels}
    ordered = sorted(canonical, key=lambda value: _digest(value, salt))
    return {label: f"candidate_{index:02d}" for index, label in enumerate(ordered, 1)}


def build_key_token_map(key_ids: Iterable[object], salt: str) -> dict[str, str]:
    distinct = {_normalize_label(value) for value in key_ids}
    ordered = sorted(distinct, key=lambda value: _digest(f"key:{value}", salt))
    return {key: f"key_{index:02d}" for index, key in enumerate(ordered, 1)}


def _safe_float(value: object) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else math.nan
    except (TypeError, ValueError):
        return math.nan


def _relative_time(frame: pd.DataFrame, source: str, groups: list[str]) -> pd.Series:
    values = pd.to_numeric(frame[source], errors="coerce")
    return values - values.groupby([frame[column] for column in groups]).transform("min")


def _stats(prefix: str, values: Iterable[object]) -> dict[str, float]:
    array = np.asarray([_safe_float(value) for value in values], dtype=float)
    array = array[np.isfinite(array)]
    names = ("mean", "std", "p10", "p50", "p90", "iqr")
    if array.size == 0:
        return {f"{prefix}_{name}": math.nan for name in names}
    q10, q25, q50, q75, q90 = np.percentile(array, [10, 25, 50, 75, 90])
    return {
        f"{prefix}_mean": float(array.mean()),
        f"{prefix}_std": float(array.std()),
        f"{prefix}_p10": float(q10),
        f"{prefix}_p50": float(q50),
        f"{prefix}_p90": float(q90),
        f"{prefix}_iqr": float(q75 - q25),
    }


def _path_features(points: pd.DataFrame, prefix: str) -> dict[str, float]:
    if len(points) < 2:
        return {
            **_stats(f"{prefix}_speed", []),
            **_stats(f"{prefix}_acceleration", []),
            **_stats(f"{prefix}_turn", []),
            f"{prefix}_pause_ratio": math.nan,
        }
    ordered = points.sort_values("time_ms")
    dt = ordered["time_ms"].diff().to_numpy(dtype=float) / 1000.0
    dx = ordered["dx"].to_numpy(dtype=float)
    dy = ordered["dy"].to_numpy(dtype=float)
    valid = np.isfinite(dt) & (dt > 0) & np.isfinite(dx) & np.isfinite(dy)
    speed = np.hypot(dx[valid], dy[valid]) / dt[valid]
    acceleration = np.diff(speed) / np.maximum(dt[valid][1:], 1e-3) if len(speed) > 1 else []
    angles = np.unwrap(np.arctan2(dy[valid], dx[valid]))
    turns = np.abs(np.diff(angles)) if len(angles) > 1 else []
    return {
        **_stats(f"{prefix}_speed", speed),
        **_stats(f"{prefix}_acceleration", acceleration),
        **_stats(f"{prefix}_turn", turns),
        f"{prefix}_pause_ratio": float(np.mean(speed < 30)) if len(speed) else math.nan,
    }


def _keyboard_features(events: pd.DataFrame) -> dict[str, float]:
    if events.empty:
        return {
            **_stats("key_dwell_ms", []),
            **_stats("key_iki_ms", []),
            **_stats("key_flight_ms", []),
            "key_backspace_rate": math.nan,
            "key_shift_rate": math.nan,
            "key_space_rate": math.nan,
            "key_special_rate": math.nan,
            "typing_wpm": math.nan,
        }
    ordered = events.sort_values("press_time_ms")
    press = ordered["press_time_ms"].to_numpy(dtype=float)
    release = ordered["release_time_ms"].to_numpy(dtype=float)
    dwell = release - press
    iki = np.diff(press)
    flight = press[1:] - release[:-1]
    span_minutes = max((np.nanmax(press) - np.nanmin(press)) / 60_000.0, 1 / 60)
    word_equivalents = float((ordered["key_category"] == "alphanum").sum()) / 5.0
    return {
        **_stats("key_dwell_ms", dwell),
        **_stats("key_iki_ms", iki),
        **_stats("key_flight_ms", flight),
        "key_backspace_rate": float((ordered["key_category"] == "backspace").mean()),
        "key_shift_rate": float(ordered["shift_held"].fillna(False).astype(bool).mean()),
        "key_space_rate": float((ordered["key_category"] == "space").mean()),
        "key_special_rate": float((ordered["key_category"] == "special").mean()),
        "typing_wpm": word_equivalents / span_minutes,
    }


def _trial_features(frame: pd.DataFrame, prefix: str, columns: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for column in columns:
        result.update(_stats(f"{prefix}_{column}", frame[column] if column in frame else []))
    return result


def extract_feature_row(
    key_events: pd.DataFrame,
    passive: pd.DataFrame,
    track_samples: pd.DataFrame,
    track_trials: pd.DataFrame,
    dot_trials: pd.DataFrame,
    drag_trials: pd.DataFrame,
    *,
    include_track_trial_summaries: bool = True,
) -> dict[str, float]:
    features = _keyboard_features(key_events)
    features.update(_path_features(passive, "mouse"))
    features.update(
        _trial_features(
            dot_trials,
            "dot",
            ["travel_time_ms", "error_px", "sub_movement_count", "hover_dwell_ms", "avg_velocity", "avg_acceleration", "avg_jerk"],
        )
    )
    features.update(
        _trial_features(
            drag_trials,
            "drag",
            ["duration_ms", "sub_movement_count", "hover_dwell_ms", "avg_velocity", "avg_acceleration", "avg_jerk"],
        )
    )
    features["drag_success_rate"] = (
        float(drag_trials["success"].astype(float).mean()) if len(drag_trials) else math.nan
    )
    for pattern in ("sinusoidal", "random_walk"):
        if include_track_trial_summaries:
            trials = track_trials[track_trials["pattern"] == pattern]
            features.update(
                _trial_features(
                    trials,
                    f"track_{pattern}",
                    ["mean_error_px", "rms_error_px", "lag_ms", "prediction_ratio", "tremor_px", "correlation_x", "correlation_y", "fatigue_delta_px"],
                )
            )
        samples = track_samples[track_samples["pattern"] == pattern]
        features.update(_stats(f"track_{pattern}_sample_error_px", samples.get("error_px", [])))
    return features


def _slice_ordered(frame: pd.DataFrame, index: int, count: int, order: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    ordered = frame.sort_values(order)
    boundaries = np.linspace(0, len(ordered), count + 1).round().astype(int)
    return ordered.iloc[boundaries[index] : boundaries[index + 1]].copy()


def _load_privacy_config(path: Path) -> tuple[dict[str, str], str]:
    if path.exists():
        payload = json.loads(path.read_text())
        aliases = build_alias_lookup(payload.get("alias_groups", []))
        salt = str(payload.get("pseudonym_salt", "")).strip()
        if len(salt) < 16:
            raise ValueError("pseudonym_salt must contain at least 16 characters")
        return aliases, salt
    # Still avoids names in output. A local secret is recommended for stable,
    # keyed pseudonyms and alias merging across repeated exports.
    return {}, "behaveguard-public-export-v1"


def _prepare_tables(workbook: dict[str, pd.DataFrame], alias_lookup: dict[str, str], salt: str):
    sessions_raw = workbook["Sessions"].copy()
    subject_map = build_pseudonym_map(sessions_raw["subject_id"], alias_lookup, salt)
    source_keys = [
        (str(row.subject_id), str(row.collected_at))
        for row in sessions_raw[["subject_id", "collected_at"]].itertuples(index=False)
    ]
    ordered_sessions = sorted(source_keys, key=lambda key: _digest(f"session:{key[0]}:{key[1]}", salt))
    session_map = {key: f"session_{index:03d}" for index, key in enumerate(ordered_sessions, 1)}

    def identifiers(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        keys = list(zip(out["subject_id"].astype(str), out["collected_at"].astype(str)))
        out.insert(0, "session_id", [session_map[key] for key in keys])
        out.insert(
            1,
            "subject_id",
            [subject_map[canonicalize(value, alias_lookup)] for value in out.pop("subject_id")],
        )
        out = out.drop(columns=["collected_at"])
        return out

    sessions = identifiers(sessions_raw)[
        ["session_id", "subject_id", "duration_ms", "n_keystrokes", "backspace_count", "n_mouse_events", "n_dot_targets", "n_drags", "n_track_trials"]
    ].copy()
    sessions["has_keyboard"] = sessions["n_keystrokes"].fillna(0).gt(0)
    sessions["has_mouse"] = sessions[["n_mouse_events", "n_dot_targets", "n_drags", "n_track_trials"]].fillna(0).sum(axis=1).gt(0)

    keys = identifiers(workbook["KeyEvents"])
    key_tokens = build_key_token_map(keys["key_id"], salt)
    keys.loc[keys["key_id"].map(_normalize_label) == "backspace", "key_category"] = "backspace"
    keys["key_id"] = keys["key_id"].map(lambda value: key_tokens[_normalize_label(value)])
    keys["press_time_ms"] = _relative_time(keys, "press_ts", ["session_id"])
    keys["release_time_ms"] = pd.to_numeric(keys["release_ts"], errors="coerce") - pd.to_numeric(keys["press_ts"], errors="coerce") + keys["press_time_ms"]
    keys["dwell_ms"] = keys["release_time_ms"] - keys["press_time_ms"]
    keys = keys[["session_id", "subject_id", "segment", "key_id", "key_category", "press_time_ms", "release_time_ms", "dwell_ms", "shift_held", "shift_hold_ms"]]

    passive = identifiers(workbook["MousePassive"])
    passive["time_ms"] = _relative_time(passive, "ts", ["session_id"])
    passive = passive[["session_id", "subject_id", "time_ms", "dx", "dy"]]

    track_samples = identifiers(workbook["TrackSamples"])
    track_samples["time_ms"] = _relative_time(track_samples, "ts", ["session_id", "trial_index"])
    track_samples["error_px"] = np.hypot(
        pd.to_numeric(track_samples["offset_x"], errors="coerce"),
        pd.to_numeric(track_samples["offset_y"], errors="coerce"),
    )
    track_samples = track_samples[["session_id", "subject_id", "trial_index", "pattern", "time_ms", "offset_x", "offset_y", "error_px"]]

    track_trials = identifiers(workbook["TrackTrials"])[
        ["session_id", "subject_id", "trial_index", "pattern", "duration_ms", "mean_error_px", "rms_error_px", "lag_ms", "prediction_ratio", "tremor_px", "correlation_x", "correlation_y", "error_first_half_px", "error_second_half_px", "fatigue_delta_px"]
    ]
    dots = identifiers(workbook["DotTrials"])[
        ["session_id", "subject_id", "trial_index", "travel_time_ms", "error_px", "sub_movement_count", "angle_of_approach_deg", "hover_dwell_ms", "avg_velocity", "avg_acceleration", "avg_jerk"]
    ]
    drags = identifiers(workbook["DragTrials"])[
        ["session_id", "subject_id", "trial_index", "duration_ms", "success", "sub_movement_count", "angle_of_approach_deg", "hover_dwell_ms", "avg_velocity", "avg_acceleration", "avg_jerk"]
    ]
    return {
        "sessions": sessions,
        "key_events": keys,
        "mouse_passive": passive,
        "track_samples": track_samples,
        "track_trials": track_trials,
        "dot_trials": dots,
        "drag_trials": drags,
    }


def _feature_tables(tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    session_rows: list[dict[str, object]] = []
    window_rows: list[dict[str, object]] = []
    for session in tables["sessions"].itertuples(index=False):
        sid = session.session_id
        subject = session.subject_id
        scoped = {name: frame[frame["session_id"] == sid] for name, frame in tables.items() if name != "sessions"}
        features = extract_feature_row(
            scoped["key_events"], scoped["mouse_passive"], scoped["track_samples"],
            scoped["track_trials"], scoped["dot_trials"], scoped["drag_trials"],
        )
        session_rows.append({"session_id": sid, "subject_id": subject, **features})
        for window in range(WINDOW_COUNT):
            key = _slice_ordered(scoped["key_events"], window, WINDOW_COUNT, "press_time_ms")
            mouse = _slice_ordered(scoped["mouse_passive"], window, WINDOW_COUNT, "time_ms")
            samples = pd.concat(
                [
                    _slice_ordered(group, window, WINDOW_COUNT, "time_ms")
                    for _, group in scoped["track_samples"].groupby(["trial_index", "pattern"], sort=False)
                ],
                ignore_index=True,
            ) if len(scoped["track_samples"]) else scoped["track_samples"].copy()
            dots = _slice_ordered(scoped["dot_trials"], window, WINDOW_COUNT, "trial_index")
            drags = _slice_ordered(scoped["drag_trials"], window, WINDOW_COUNT, "trial_index")
            # Trial aggregates are full-trial summaries, so allocate by trial
            # order. Sample-level tracking features remain present in every window.
            tracks = _slice_ordered(scoped["track_trials"], window, WINDOW_COUNT, "trial_index")
            row = extract_feature_row(
                key, mouse, samples, tracks, dots, drags,
                include_track_trial_summaries=False,
            )
            window_rows.append({
                "sample_id": f"{sid}_window_{window + 1}",
                "session_id": sid,
                "subject_id": subject,
                "window_index": window + 1,
                **row,
            })
    return pd.DataFrame(session_rows), pd.DataFrame(window_rows)


def _write_data_card(output: Path, tables: dict[str, pd.DataFrame], session_features: pd.DataFrame, window_features: pd.DataFrame) -> None:
    sessions = tables["sessions"]
    text = f"""# BehaveGuard Multimodal Behavioral Authentication Dataset

## Overview

This is a privacy-preserving research export of keyboard timing and mouse dynamics collected through the BehaveGuard browser tasks. It contains **{len(sessions)} sessions**, **{sessions['subject_id'].nunique()} anonymized candidates**, **{len(tables['key_events']):,} key events**, and **{len(tables['mouse_passive']):,} passive mouse samples**.

The package supports exploratory analysis, multimodal feature engineering, closed-set identification, one-vs-rest verification, modality ablation, calibration analysis, and sequence-model experiments. `window_features.csv` contains {len(window_features)} chronological pseudo-samples and {len(window_features.columns) - 4} engineered features.

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
| `sessions.csv` | collection session | {len(tables['sessions']):,} |
| `key_events.csv` | key press/release event | {len(tables['key_events']):,} |
| `mouse_passive.csv` | passive pointer delta sample | {len(tables['mouse_passive']):,} |
| `track_samples.csv` | pursuit-task offset sample | {len(tables['track_samples']):,} |
| `track_trials.csv` | pursuit task trial | {len(tables['track_trials']):,} |
| `dot_trials.csv` | point-and-click trial | {len(tables['dot_trials']):,} |
| `drag_trials.csv` | drag-and-drop trial | {len(tables['drag_trials']):,} |
| `session_features.csv` | full-session feature vector | {len(session_features):,} |
| `window_features.csv` | chronological within-session window | {len(window_features):,} |

All times are milliseconds, distances are pixels, angles are degrees, and rates are fractions unless the column name says otherwise.

## Evaluation warning

Most candidates currently contribute one real session. Splitting one session into windows enables a **within-session development benchmark**, but it does not estimate cross-day authentication accuracy. Report parent-session counts, keep chronological windows non-overlapping, and label all results as development-only. A production study needs multiple independently collected sessions per candidate across days, devices, browsers, and physical conditions.

## Suggested Kaggle task

Use the accompanying notebook to compare robust logistic regression, k-nearest neighbors, RBF-SVM, random forest, Extra Trees, and a BiLSTM+TCN fusion model. Recommended metrics are balanced accuracy and macro-F1 for identification, plus ROC-AUC, equal-error rate, false-accept rate, and false-reject rate for verification.

## License and permitted use

The package uses a custom research-demonstration notice in `LICENSE_DATA.md`. Before making the dataset public, the publisher is responsible for confirming participant consent and the legal basis for releasing biometric-adjacent data.
"""
    (output / "README.md").write_text(text)


def _write_manifest(output: Path, tables: dict[str, pd.DataFrame]) -> None:
    files = {}
    for path in sorted(output.glob("*.csv")):
        with path.open("rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        frame = pd.read_csv(path)
        files[path.name] = {"sha256": digest, "rows": len(frame), "columns": list(frame.columns)}
    payload = {
        "schema_version": "1.0.0",
        "generated_by": "scripts/export_kaggle_dataset.py",
        "privacy": {
            "direct_identifiers_removed": True,
            "wall_clock_timestamps_removed": True,
            "literal_keys_removed": True,
            "absolute_pointer_coordinates_removed": True,
        },
        "files": files,
    }
    (output / "manifest.json").write_text(json.dumps(payload, indent=2))


def export(source: Path = DEFAULT_SOURCE, output: Path = DEFAULT_OUTPUT, privacy_config: Path = DEFAULT_PRIVACY_CONFIG) -> dict[str, int]:
    if not source.exists():
        raise FileNotFoundError(f"Workbook not found at {source}")
    output.mkdir(parents=True, exist_ok=True)
    alias_lookup, salt = _load_privacy_config(privacy_config)
    workbook = pd.read_excel(source, sheet_name=None)
    required = {"Sessions", "KeyEvents", "MousePassive", "TrackSamples", "TrackTrials", "DotTrials", "DragTrials"}
    missing = required - set(workbook)
    if missing:
        raise KeyError(f"Workbook is missing required sheets: {sorted(missing)}")
    tables = _prepare_tables(workbook, alias_lookup, salt)
    session_features, window_features = _feature_tables(tables)
    exported = {**tables, "session_features": session_features, "window_features": window_features}
    for name, frame in exported.items():
        frame.to_csv(output / f"{name}.csv", index=False, float_format="%.6g")

    metadata = {
        "title": "BehaveGuard Multimodal Behavioral Authentication",
        "id": "behaveguard-multimodal-behavioral-authentication",
        "licenses": [{"name": "other"}],
        "keywords": ["biometrics", "cybersecurity", "keystroke-dynamics", "mouse-dynamics", "deep-learning"],
    }
    (output / "dataset-metadata.json").write_text(json.dumps(metadata, indent=2))
    (output / "LICENSE_DATA.md").write_text(
        "# Research demonstration data notice\n\n"
        "This release is provided for non-production research, education, and project demonstration. "
        "Do not attempt to re-identify candidates, infer sensitive traits, or use the data for employment, "
        "credit, insurance, policing, access denial, or other consequential decisions. Redistribution requires "
        "preserving this notice and the privacy transformations. The publisher must confirm participant consent "
        "and applicable legal requirements before public release. No warranty is provided.\n"
    )
    _write_data_card(output, tables, session_features, window_features)
    _write_manifest(output, exported)
    return {name: len(frame) for name, frame in exported.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--privacy-config", type=Path, default=DEFAULT_PRIVACY_CONFIG)
    args = parser.parse_args()
    counts = export(args.source, args.output, args.privacy_config)
    print(f"Exported privacy-preserving Kaggle package to {args.output}")
    for name, rows in counts.items():
        print(f"  {name:18s} {rows:>8,} rows")


if __name__ == "__main__":
    main()
