from pathlib import Path

from behaveguard import personal_verifier


def test_personal_scoring_selects_profile_specific_artifact(tmp_path, monkeypatch):
    first = tmp_path / "first.pt"
    second = tmp_path / "second.pt"
    first.touch()
    second.touch()
    loaded: list[str] = []

    monkeypatch.setattr(personal_verifier, "PERSONAL_NEURAL_DIR", tmp_path)
    monkeypatch.setattr(personal_verifier, "_artifact_path", lambda profile_id: tmp_path / f"{profile_id}.pt")
    monkeypatch.setattr(personal_verifier, "_migrate_legacy_artifact", lambda: None)
    monkeypatch.setattr(personal_verifier, "_score_payload", lambda *args: 0.8)

    def fake_load(path: str, modified_at: float):
        loaded.append(Path(path).name)
        profile_id = Path(path).stem
        return ({
            "target_profile_id": profile_id,
            "target_label": profile_id,
            "feature_names": [],
            "window_count": 4,
            "threshold": 0.5,
        }, object(), object())

    monkeypatch.setattr(personal_verifier, "_load_personal_artifact", fake_load)

    assert personal_verifier.score_personal_verifier({}, "first")["match"] is True
    assert personal_verifier.score_personal_verifier({}, "second")["match"] is True
    assert loaded == ["first.pt", "second.pt"]
