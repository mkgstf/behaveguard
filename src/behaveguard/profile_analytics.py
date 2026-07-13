from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any

from .database import profile_sessions


def _numbers(values) -> list[float]:
    result = []
    for value in values:
        try:
            number = float(value)
            if math.isfinite(number):
                result.append(number)
        except (TypeError, ValueError):
            pass
    return result


def _mean(values) -> float | None:
    clean = _numbers(values)
    return mean(clean) if clean else None


def session_behavior_metrics(session: dict[str, Any]) -> dict[str, float | None]:
    keyboard = session.get("keyboard") or {}
    events = sorted(keyboard.get("events") or [], key=lambda event: float(event.get("press_ts", 0)))
    typing_events = [event for event in events if event.get("key_category") in {"alphanum", "space"}]
    duration_minutes = 0.0
    if len(typing_events) >= 2:
        duration_minutes = (float(typing_events[-1].get("press_ts", 0)) - float(typing_events[0].get("press_ts", 0))) / 60_000
    wpm = (len(typing_events) / 5) / duration_minutes if duration_minutes > 0 else None
    dwell = [float(event["release_ts"]) - float(event["press_ts"]) for event in events if event.get("release_ts") is not None]
    iki = [float(right.get("press_ts", 0)) - float(left.get("press_ts", 0)) for left, right in zip(typing_events, typing_events[1:])]
    flight = [
        float(right.get("press_ts", 0)) - float(left["release_ts"])
        for left, right in zip(typing_events, typing_events[1:]) if left.get("release_ts") is not None
    ]
    iki_clean = [value for value in iki if 0 < value < 2000]
    rhythm_cv = pstdev(iki_clean) / mean(iki_clean) if len(iki_clean) > 1 and mean(iki_clean) else None

    mouse = session.get("mouse") or {}
    passive = mouse.get("passive_points") or []
    speeds = []
    for left, right in zip(passive, passive[1:]):
        dt = float(right.get("ts", 0)) - float(left.get("ts", 0))
        if dt <= 0:
            continue
        distance = math.hypot(float(right.get("x", 0)) - float(left.get("x", 0)), float(right.get("y", 0)) - float(left.get("y", 0)))
        speed = distance / (dt / 1000)
        if speed < 20_000:
            speeds.append(speed)

    dots = mouse.get("dot_trials") or []
    drags = mouse.get("drag_trials") or []
    tracks = mouse.get("track_trials") or []
    track_error = [(trial.get("derived") or {}).get("mean_error_px") for trial in tracks]
    track_tremor = [(trial.get("derived") or {}).get("tremor_px") for trial in tracks]
    return {
        "wpm": wpm,
        "dwell_ms": _mean(value for value in dwell if 0 < value < 1000),
        "flight_ms": _mean(value for value in flight if -500 < value < 2000),
        "iki_ms": _mean(iki_clean),
        "rhythm_cv": rhythm_cv,
        "backspace_rate": sum(event.get("key_id") == "backspace" for event in events) / len(events) if events else None,
        "mouse_speed_pxs": _mean(speeds),
        "click_error_px": _mean(trial.get("error_px") for trial in dots),
        "target_time_ms": _mean(trial.get("travel_time_ms") for trial in dots),
        "drag_duration_ms": _mean(trial.get("duration_ms") for trial in drags),
        "drag_success_rate": sum(bool(trial.get("success")) for trial in drags) / len(drags) if drags else None,
        "tracking_error_px": _mean(track_error),
        "tremor_px": _mean(track_tremor),
    }


def _round_metrics(metrics: dict[str, float | None]) -> dict[str, float | None]:
    return {name: round(value, 2) if value is not None else None for name, value in metrics.items()}


def _percentile(value: float | None, population: list[float], higher_is_better: bool) -> float | None:
    if value is None or not population:
        return None
    if len(population) == 1:
        return 50.0
    below = sum(candidate < value for candidate in population)
    equal = sum(candidate == value for candidate in population)
    score = 100 * (below + max(equal - 1, 0) / 2) / (len(population) - 1)
    return round(score if higher_is_better else 100 - score, 1)


def _rank(overall: float) -> str:
    if overall >= 85:
        return "S"
    if overall >= 70:
        return "A"
    if overall >= 55:
        return "B"
    if overall >= 40:
        return "C"
    return "D"


def build_character_cards(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = []
    metric_names = [
        "wpm", "dwell_ms", "flight_ms", "iki_ms", "rhythm_cv", "backspace_rate", "mouse_speed_pxs",
        "click_error_px", "target_time_ms", "drag_duration_ms", "drag_success_rate", "tracking_error_px", "tremor_px",
    ]
    for profile in profiles:
        sessions = profile_sessions(profile["id"])
        history = [{"collected_at": row["collected_at"], **session_behavior_metrics(row["payload"])} for row in sessions]
        aggregate = {name: _mean(row.get(name) for row in history) for name in metric_names}
        cards.append({
            "id": profile["id"], "label": profile["label"], "enrollment_count": profile["enrollment_count"],
            "metrics": aggregate, "history": [{**row, **_round_metrics({name: row.get(name) for name in metric_names})} for row in history],
        })

    populations = {name: _numbers(card["metrics"].get(name) for card in cards) for name in metric_names}
    definitions = {
        "Typing speed": ("wpm", True),
        "Rhythm": ("rhythm_cv", False),
        "Precision": ("click_error_px", False),
        "Cursor control": ("tracking_error_px", False),
        "Agility": ("target_time_ms", False),
        "Steadiness": ("tremor_px", False),
    }
    for card in cards:
        ratings = {}
        missing = []
        available = []
        for label, (metric, direction) in definitions.items():
            rating = _percentile(card["metrics"].get(metric), populations[metric], direction)
            if rating is None:
                missing.append(label)
                ratings[label] = 50.0
            else:
                ratings[label] = rating
                available.append(rating)
        overall = round(mean(available), 1) if available else 50.0
        card["metrics"] = _round_metrics(card["metrics"])
        card["ratings"] = ratings
        card["overall"] = overall
        card["rank"] = _rank(overall)
        card["missing_ratings"] = missing
    return cards
