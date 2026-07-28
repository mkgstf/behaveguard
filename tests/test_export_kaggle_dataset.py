from scripts.export_kaggle_dataset import _canonicalize, build_anon_map, build_key_token_map


def test_subject_aliases_are_merged_before_anonymization():
    mapping = build_anon_map(["Saruman", "elrond", "AKSHIT", "Akshat"])

    assert _canonicalize("Saruman") == _canonicalize("elrond") == _canonicalize("AKSHIT")
    assert set(mapping) == {"saruman", "akshat"}
    assert len(set(mapping.values())) == 2


def test_key_tokens_preserve_equality_without_exposing_keys():
    mapping = build_key_token_map(["a", "a", "Backspace"])

    assert mapping["a"].startswith("key_")
    assert mapping["Backspace"].startswith("key_")
    assert mapping["a"] != mapping["Backspace"]
