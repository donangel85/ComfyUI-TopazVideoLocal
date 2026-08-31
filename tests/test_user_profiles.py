"""Tests for user-saved presets.

These are written through an HTTP route, so whatever arrives is untrusted input. The
sanitising is the interesting part: a bad payload must cost the caller their preset, not
the ability to open a workflow.
"""

import json

import pytest

from topaz_studio import profiles, user_profiles


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point the store at a temp file so tests never touch the real user_presets.json."""
    path = tmp_path / "user_presets.json"
    monkeypatch.setattr(user_profiles, "USER_PRESETS_PATH", path)
    profiles.clear_cache()
    yield path
    profiles.clear_cache()


class TestSaveAndLoad:
    def test_round_trip(self):
        user_profiles.save("My look", {"noise": 0.4, "details": 0.2})
        entries = user_profiles.load()
        assert len(entries) == 1
        assert entries[0]["name"] == "My look"
        assert entries[0]["options"] == {"noise": 0.4, "details": 0.2}

    def test_saving_the_same_name_replaces_rather_than_duplicates(self):
        user_profiles.save("Look", {"noise": 0.4})
        user_profiles.save("Look", {"noise": 0.9})
        entries = user_profiles.load()
        assert len(entries) == 1
        assert entries[0]["options"]["noise"] == 0.9

    def test_entries_are_sorted_by_name(self):
        for name in ("zebra", "alpha", "mango"):
            user_profiles.save(name, {"noise": 0.1})
        assert [e["name"] for e in user_profiles.load()] == ["alpha", "mango", "zebra"]

    def test_missing_file_is_an_empty_list_not_an_error(self, isolated_store):
        assert not isolated_store.exists()
        assert user_profiles.load() == []

    def test_corrupt_file_is_an_empty_list_not_an_error(self, isolated_store):
        isolated_store.write_text("{ this is not json", encoding="utf-8")
        assert user_profiles.load() == []

    def test_file_holding_the_wrong_shape_is_ignored(self, isolated_store):
        isolated_store.write_text(json.dumps({"presets": "nope"}), encoding="utf-8")
        assert user_profiles.load() == []

    def test_a_bad_entry_does_not_discard_the_good_ones(self, isolated_store):
        isolated_store.write_text(json.dumps({"presets": [
            "not a dict",
            {"name": "", "options": {}},
            {"name": "keeper", "options": {"noise": 0.5}},
        ]}), encoding="utf-8")
        entries = user_profiles.load()
        assert [e["name"] for e in entries] == ["keeper"]


class TestSanitising:
    def test_unknown_keys_are_dropped(self):
        """The payload comes from an HTTP route; only known tuning keys are kept."""
        cleaned = user_profiles.sanitize_options(
            {"noise": 0.5, "rm": "-rf", "model": "prob-4", "scale": 4})
        assert cleaned == {"noise": 0.5}

    def test_values_are_clamped_to_their_range(self):
        cleaned = user_profiles.sanitize_options({"noise": 99, "blur": -99})
        assert cleaned == {"noise": 1.0, "blur": -1.0}

    def test_keys_with_their_own_range_are_clamped_to_it(self):
        # prenoise runs 0..0.1, not -1..1.
        assert user_profiles.sanitize_options({"prenoise": 5})["prenoise"] == 0.1
        assert user_profiles.sanitize_options({"gsize": 99})["gsize"] == 5.0

    def test_non_numeric_values_are_skipped(self):
        assert user_profiles.sanitize_options({"noise": "loud", "blur": None}) == {}

    def test_strings_that_are_numbers_are_accepted(self):
        assert user_profiles.sanitize_options({"noise": "0.5"}) == {"noise": 0.5}

    def test_control_characters_are_stripped_from_names(self):
        assert user_profiles.sanitize_name("bad\x00name\n") == "badname"

    def test_names_are_length_capped(self):
        long_name = "x" * 500
        assert len(user_profiles.sanitize_name(long_name)) == user_profiles.MAX_NAME_LENGTH

    def test_an_empty_name_is_refused(self):
        with pytest.raises(ValueError):
            user_profiles.save("   ", {"noise": 0.5})

    def test_estimate_is_clamped(self):
        entry = user_profiles.save("p", {}, estimate=9999)
        assert entry["estimate"] == 100


class TestDelete:
    def test_delete_removes_the_entry(self):
        user_profiles.save("gone", {"noise": 0.5})
        assert user_profiles.delete("gone") is True
        assert user_profiles.load() == []

    def test_deleting_something_absent_reports_false(self):
        assert user_profiles.delete("never existed") is False


class TestCatalogIntegration:
    def test_a_saved_preset_appears_in_the_dropdown(self):
        user_profiles.save("House look", {"noise": 0.4})
        profiles.clear_cache()
        labels = profiles.labels(None)
        assert f"{user_profiles.PREFIX}House look" in labels

    def test_a_saved_preset_resolves_back_to_its_values(self):
        user_profiles.save("House look", {"noise": 0.4, "details": 0.2})
        profiles.clear_cache()
        found = profiles.resolve(f"{user_profiles.PREFIX}House look", None)
        assert found is not None and found.source == "user"
        resolved = found.resolve(1.0)
        assert resolved["noise"] == 0.4 and resolved["details"] == 0.2

    def test_strength_scales_a_saved_preset_like_any_other(self):
        user_profiles.save("House look", {"noise": 0.4})
        profiles.clear_cache()
        found = profiles.resolve(f"{user_profiles.PREFIX}House look", None)
        assert found.resolve(0.5)["noise"] == pytest.approx(0.2)

    def test_a_saved_name_can_shadow_a_builtin_without_colliding(self):
        """The prefix is what tells them apart, so both must stay reachable."""
        builtin = profiles.labels(None)[1]
        user_profiles.save(builtin, {"noise": 0.9})
        profiles.clear_cache()

        mine = profiles.resolve(f"{user_profiles.PREFIX}{builtin}", None)
        theirs = profiles.resolve(builtin, None)
        assert mine is not None and mine.source == "user"
        assert theirs is not None and theirs.source == "builtin"

    def test_manual_still_resolves_to_nothing(self):
        assert profiles.resolve(profiles.MANUAL, None) is None
