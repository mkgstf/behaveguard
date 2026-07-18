from __future__ import annotations

from typing import Any

from .config import AUTO_MERGE_SIMILARITY_THRESHOLD
from .database import list_profiles, merge_profiles_with_tracking
from .modeling import _cosine, load_model, retrain_model


def scan_and_auto_merge(threshold: float = AUTO_MERGE_SIMILARITY_THRESHOLD) -> dict[str, Any]:
    """Detects likely-duplicate profiles by centroid cosine similarity and
    merges them immediately — no human approves any individual merge before
    it executes. Safety comes from three places instead: (1) the threshold
    is deliberately conservative, (2) every merge is recorded as a
    reversible `MergeEvent` (see `database.revert_merge_event`), and (3)
    this only ever compares *active* (non-blacklisted) profiles that already
    have a trained centroid — brand-new, single-session profiles are
    excluded rather than risking a merge on thin data.

    Runs as an explicit action (CLI command or admin-triggered API route)
    rather than a background scheduler, since no job-queue worker
    infrastructure exists yet (see the Phase 0 architecture notes on Redis
    being provisioned but not yet wired to a task queue).
    """
    artifact = load_model()
    profiles = [profile for profile in list_profiles(include_blacklisted=False) if profile["id"] in artifact["profiles"]]

    merged_pairs: list[dict[str, Any]] = []
    considered_ids: set[str] = set()

    # Sort so merge decisions are deterministic across runs given the same data.
    profiles.sort(key=lambda profile: profile["id"])

    for i, left in enumerate(profiles):
        if left["id"] in considered_ids:
            continue
        for right in profiles[i + 1 :]:
            if right["id"] in considered_ids:
                continue
            left_centroid = artifact["profiles"][left["id"]]["centroid"]
            right_centroid = artifact["profiles"][right["id"]]["centroid"]
            similarity = _cosine(left_centroid, right_centroid)
            if similarity < threshold:
                continue
            # Merge the newer/smaller-history profile into the
            # older/larger-history one, so the surviving profile keeps the
            # longer track record.
            source, target = (
                (left, right)
                if (left["enrollment_count"], left["created_at"]) < (right["enrollment_count"], right["created_at"])
                else (right, left)
            )
            event = merge_profiles_with_tracking(
                source["label"], target["label"], similarity_score=similarity, method="auto_high_confidence"
            )
            merged_pairs.append(
                {
                    "source_label": source["label"],
                    "target_label": target["label"],
                    "similarity": round(similarity, 4),
                    "merge_event_id": event["id"],
                }
            )
            considered_ids.add(source["id"])
            # `right` (or `left`) no longer exists post-merge; stop comparing
            # `left` against anything once it's been merged away as a source.
            if source["id"] == left["id"]:
                break

    if merged_pairs:
        retrain_model()

    return {"threshold": threshold, "candidates_considered": len(profiles), "merged": merged_pairs}
