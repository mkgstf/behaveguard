from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .database import add_session, create_profile, list_profiles, profile_sessions
from .features import extract_features


PROFILE_ALIASES = {"elrond": "saruman"}


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.where(pd.notna(frame), None).to_json(orient="records"))


def import_xlsx(path: Path) -> dict[str, int]:
    workbook = pd.read_excel(path, sheet_name=None)
    sessions = workbook["Sessions"]
    existing = {profile["label"].lower(): profile for profile in list_profiles()}
    imported = 0
    created = 0
    for _, summary in sessions.iterrows():
        source_label = str(summary["subject_id"])
        label = PROFILE_ALIASES.get(source_label.casefold(), source_label)
        collected = str(summary["collected_at"])
        profile = existing.get(label.lower())
        if profile is None:
            profile = create_profile(label)
            existing[label.lower()] = profile
            created += 1
        if any(str(row["collected_at"]) == collected for row in profile_sessions(profile["id"])):
            continue
        def rows(sheet: str) -> list[dict[str, Any]]:
            frame = workbook[sheet]
            selected = frame[(frame.subject_id.astype(str) == source_label) & (frame.collected_at.astype(str) == collected)]
            return _records(selected.drop(columns=["subject_id", "collected_at"], errors="ignore"))
        key_events = rows("KeyEvents")
        for event in key_events:
            event.pop("dwell_ms", None)
        track_trials = rows("TrackTrials")
        track_samples = rows("TrackSamples")
        for trial in track_trials:
            index = trial.get("trial_index")
            trial["samples"] = [sample for sample in track_samples if sample.get("trial_index") == index]
            trial["derived"] = {name: trial.pop(name) for name in list(trial) if name in {"mean_error_px", "rms_error_px", "lag_ms", "prediction_ratio", "tremor_px", "correlation_x", "correlation_y", "error_first_half_px", "error_second_half_px", "fatigue_delta_px"}}
        dots = rows("DotTrials")
        drags = rows("DragTrials")
        payload = {
            "subject_id": label, "collected_at": collected, "duration_ms": float(summary["duration_ms"]),
            "keyboard": {"events": key_events, "pangram_text_length": 0, "free_text_length": 0, "extras": {}},
            "mouse": {"passive_points": rows("MousePassive"), "dot_trials": dots, "drag_trials": drags, "track_trials": track_trials},
            "context": {"source": "xlsx-import"},
        }
        add_session(profile["id"], payload, extract_features(payload), "import")
        imported += 1
    return {"profiles_created": created, "sessions_imported": imported}
