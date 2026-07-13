from behaveguard.importer import PROFILE_ALIASES


def test_known_identity_alias_is_preserved():
    assert PROFILE_ALIASES["elrond"] == "saruman"
