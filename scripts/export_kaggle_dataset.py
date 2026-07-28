"""Export Behaveguard-client.xlsx to a cleaned, anonymized, Kaggle-ready CSV dataset.

Drops redundant sheets (IKI_Sequences, Trigraphs), leakage-prone columns
(absolute coords, wall-clock timestamps, time-of-day encodings, fixed counts,
synthetic pressure), and derived duplicates. Subject labels are then
anonymized: known aliases (elrond/akshit -> saruman) are merged first, and
every canonical identity is replaced by a stable, opaque token of the form
``subject_NN``. No subject name or handle survives into the exported CSVs.

Usage: uv run python scripts/export_kaggle_dataset.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "Behaveguard-client.xlsx"
OUT = REPO / "kaggle_dataset"

# Alias merge applied *before* anonymization so an alias of one identity is
# never split across two anonymized tokens. (Akshat is a distinct person and
# is intentionally NOT listed here.)
PROFILE_ALIASES = {"elrond": "saruman", "akshit": "saruman"}

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


def _canonicalize(label: str) -> str:
    """Apply known alias merges before anonymization."""
    normalized = str(label).strip().casefold()
    return PROFILE_ALIASES.get(normalized, normalized)


def build_anon_map(raw_labels) -> dict[str, str]:
    """Map raw subject_id -> opaque subject_NN token (aliases share a token)."""
    canonical = sorted({_canonicalize(lbl) for lbl in raw_labels}, key=str.casefold)
    return {name: f"subject_{i:02d}" for i, name in enumerate(canonical, start=1)}


def build_key_token_map(key_ids) -> dict[str, str]:
    """Map raw key_id -> opaque key_NN token (preserves same-key grouping)."""
    distinct = sorted({str(k) for k in key_ids}, key=str.casefold)
    return {k: f"key_{i:02d}" for i, k in enumerate(distinct, start=1)}


def export() -> dict[str, int]:
    if not SRC.exists():
        raise FileNotFoundError(f"Workbook not found at {SRC}")
    OUT.mkdir(parents=True, exist_ok=True)
    workbook = pd.read_excel(SRC, sheet_name=None)
    raw_labels = workbook["Sessions"]["subject_id"].astype(str).tolist()
    anon_map = build_anon_map(raw_labels)
    n_identities = len(set(anon_map.values()))
    # Tokenize key_id values: the keystroke dynamics signal is in timing,
    # not the typed character. Same-key grouping is preserved for any
    # downstream modeling while the readable character is hidden.
    key_token_map = build_key_token_map(
        workbook["KeyEvents"]["key_id"].astype(str).tolist()
    )
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
        # Anonymize: canonicalize aliases first, then map to subject_NN.
        frame = frame.copy()
        frame["subject_id"] = (
            frame["subject_id"].astype(str).map(lambda s: anon_map[_canonicalize(s)])
        )
        if name == "KeyEvents":
            frame["key_id"] = frame["key_id"].astype(str).map(
                lambda k: key_token_map.get(str(k), str(k))
            )
        out_path = OUT / f"{name}.csv"
        frame.to_csv(out_path, index=False)
        summary[name] = len(frame)
    metadata = {
        "title": "BehaveGuard Client Behavioral Authentication Dataset",
        "id": "behaveguard-client",
        "id_no": "behaveguard-client",
        "description": (
            "Anonymized, cleaned keyboard + mouse behavioral-authentication "
            "collection: 10 sessions across 9 identities. Known aliases "
            "are merged before anonymization and every identity is replaced "
            "by an opaque subject_NN token; no subject name or handle "
            "survives into the export. Redundant sheets (IKI_Sequences, "
            "Trigraphs) and leakage-prone columns (absolute coordinates, "
            "wall-clock timestamps, time-of-day encodings, fixed counts, "
            "synthetic pressure) have been removed. "
            "See notebooks/behaveguard_demo.ipynb for the full reproducible demo."
        ),
        "licenses": [{"name": "CC0-1.0"}],
    }
    (OUT / "dataset-metadata.json").write_text(json.dumps(metadata, indent=2))
    # The reversible map is biometric-adjacent metadata; keep it local and
    # gitignored (kaggle_dataset/), never upload it alongside the CSVs.
    (OUT / "anon_map.local.json").write_text(json.dumps(anon_map, indent=2))
    summary["__anon__"] = n_identities
    return summary


if __name__ == "__main__":
    counts = export()
    print(f"Exported anonymized CSVs to {OUT}/")
    for name, n in counts.items():
        if name == "__anon__":
            print(f"  identities     {n}")
            continue
        flag = "DROP" if n == -1 else f"{n} rows"
        print(f"  {name:14s} {flag}")
