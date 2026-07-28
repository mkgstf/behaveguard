from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_SCRIPT = Path(__file__).parents[1] / "scripts" / "export_kaggle_dataset.py"
_SPEC = spec_from_file_location("export_kaggle_dataset", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

_canonicalize = _MODULE._canonicalize
build_anon_map = _MODULE.build_anon_map
build_key_token_map = _MODULE.build_key_token_map


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
