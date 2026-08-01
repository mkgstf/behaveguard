from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_SCRIPT = Path(__file__).parents[1] / "scripts" / "export_kaggle_dataset.py"
_SPEC = spec_from_file_location("export_kaggle_dataset", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

build_alias_lookup = _MODULE.build_alias_lookup
build_key_token_map = _MODULE.build_key_token_map
build_pseudonym_map = _MODULE.build_pseudonym_map
canonicalize = _MODULE.canonicalize


def test_alias_groups_merge_before_pseudonymization():
    aliases = build_alias_lookup([["primary", "alternate-one", "alternate-two"]])
    mapping = build_pseudonym_map(
        ["primary", "alternate-one", "alternate-two", "distinct"], aliases, "unit-test-secret-value"
    )

    assert canonicalize("PRIMARY", aliases) == canonicalize("alternate-one", aliases)
    assert len(mapping) == 2
    assert all(value.startswith("candidate_") for value in mapping.values())


def test_pseudonyms_are_stable_for_same_secret_and_do_not_expose_labels():
    labels = ["alpha", "beta", "gamma"]
    first = build_pseudonym_map(labels, {}, "unit-test-secret-value")
    second = build_pseudonym_map(reversed(labels), {}, "unit-test-secret-value")

    assert first == second
    assert not (set(labels) & set(first.values()))


def test_key_tokens_preserve_equality_without_exposing_keys():
    mapping = build_key_token_map(["a", "a", "Backspace"], "unit-test-secret-value")

    assert mapping["a"].startswith("key_")
    assert mapping["backspace"].startswith("key_")
    assert mapping["a"] != mapping["backspace"]
