"""Export Behaveguard-client.xlsx to a cleaned, Kaggle-ready CSV dataset.

Drops redundant sheets (IKI_Sequences, Trigraphs), leakage-prone columns
(absolute coords, wall-clock timestamps, time-of-day encodings, fixed counts,
synthetic pressure), and derived duplicates. Keeps raw subject_id; canonical
alias merging (elrond/akshit -> saruman) happens in the notebook/pipeline.

Usage: uv run python scripts/export_kaggle_dataset.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "Behaveguard-client.xlsx"
OUT = REPO / "kaggle_dataset"

DROP_SHEETS = {
    "IKI_Sequences",
    "Trigraphs",
}

DROP_COLUMNS: dict[str, list[str]] = {
    "Sessions": [
        "n_mouse_events", "n_dot_targets", "n_drags", "n_track_trials",
        "drift_iki_ms", "time_sin", "time_cos",
    ],
    "KeyEvents": ["dwell_ms"],
    "MousePassive": ["x", "y", "pressure"],
    "TrackSamples": ["offset_x", "offset_y", "distance_px", "pressure", "pattern"],
    "TrackTrials": ["started_at", "ended_at", "n_samples"],
    "DragTrials": ["start_x", "start_y", "end_x", "end_y", "zone_x", "zone_y"],
}

KEEP_ORDER: dict[str, list[str]] = {
    "Sessions": [
        "subject_id", "collected_at", "n_keystrokes", "duration_ms", "backspace_count",
    ],
    "KeyEvents": [
        "subject_id", "collected_at", "segment", "key_id", "key_category",
        "press_ts", "release_ts", "shift_held", "shift_hold_ms",
    ],
    "MousePassive": ["subject_id", "collected_at", "ts", "dx", "dy"],
    "TrackSamples": [
        "subject_id", "collected_at", "trial_index",
        "cursor_x", "cursor_y", "target_x", "target_y", "ts",
    ],
    "TrackTrials": [
        "subject_id", "collected_at", "trial_index", "pattern", "duration_ms",
        "mean_error_px", "rms_error_px", "lag_ms", "prediction_ratio",
        "tremor_px", "correlation_x", "correlation_y",
        "error_first_half_px", "error_second_half_px", "fatigue_delta_px",
    ],
    "DotTrials": [
        "subject_id", "collected_at", "trial_index",
        "target_x", "target_y", "click_x", "click_y",
        "travel_time_ms", "error_px", "sub_movement_count",
        "angle_of_approach_deg", "hover_dwell_ms",
        "avg_velocity", "avg_acceleration", "avg_jerk",
    ],
    "DragTrials": [
        "subject_id", "collected_at", "trial_index",
        "duration_ms", "success", "sub_movement_count",
        "angle_of_approach_deg", "hover_dwell_ms",
        "avg_velocity", "avg_acceleration", "avg_jerk",
    ],
}


def export() -> dict[str, int]:
    if not SRC.exists():
        raise FileNotFoundError(f"Workbook not found at {SRC}")
    OUT.mkdir(parents=True, exist_ok=True)
    workbook = pd.read_excel(SRC, sheet_name=None)
    summary: dict[str, int] = {}
    for name, frame in workbook.items():
        if name in DROP_SHEETS:
            summary[name] = -1
            continue
        keep = KEEP_ORDER.get(name)
        if keep is None:
            frame = frame.drop(columns=DROP_COLUMNS.get(name, []), errors="ignore")
        else:
            missing = [c for c in keep if c not in frame.columns]
            if missing:
                raise KeyError(f"{name}: missing kept columns {missing}")
            frame = frame[keep]
        out_path = OUT / f"{name}.csv"
        frame.to_csv(out_path, index=False)
        summary[name] = len(frame)
    metadata = {
        "title": "BehaveGuard Client Behavioral Authentication Dataset",
        "id": "behaveguard-client",
        "id_no": "behaveguard-client",
        "description": (
            "Cleaned keyboard + mouse behavioral-authentication collection "
            "for 10 sessions across 9 identities (after canonicalizing the "
            "elrond/akshit aliases into saruman). Redundant sheets "
            "(IKI_Sequences, Trigraphs) and leakage-prone columns (absolute "
            "coordinates, wall-clock timestamps, time-of-day encodings, "
            "fixed counts, synthetic pressure) have been removed. Raw "
            "subject_id is preserved; alias merging is performed in the "
            "accompanying notebook/pipeline. See notebooks/behaveguard_demo.ipynb."
        ),
        "licenses": [{"name": "CC0-1.0"}],
    }
    (OUT / "dataset-metadata.json").write_text(json.dumps(metadata, indent=2))
    return summary


if __name__ == "__main__":
    counts = export()
    print(f"Exported cleaned CSVs to {OUT}/")
    for name, n in counts.items():
        flag = "DROP" if n == -1 else f"{n} rows"
        print(f"  {name:14s} {flag}")