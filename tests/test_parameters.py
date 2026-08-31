"""Tests for the tvai_up parameter ranges.

These limits are not decoration. A value outside a widget's range fails the whole prompt
in ComfyUI, with a message naming a parameter nobody touched:

    Value 0.3 bigger than max of 0.1: prenoise

Before this table existed the ranges lived in three places and disagreed: profiles
clamped everything to -1..1, the preset store had its own per-key table, and the widget
declarations spelled the limits out a third time.
"""

import pytest

from topaz_studio import parameters, profiles


class TestRanges:
    @pytest.mark.parametrize("key,expected", [
        # Read from `ffmpeg -h filter=tvai_up` against the real installation.
        ("preblur", (-1.0, 1.0)),
        ("noise", (-1.0, 1.0)),
        ("details", (-1.0, 1.0)),
        ("halo", (-1.0, 1.0)),
        ("blur", (-1.0, 1.0)),
        ("compression", (-1.0, 1.0)),
        ("prenoise", (0.0, 0.1)),
        ("grain", (0.0, 1.0)),
        ("gsize", (0.0, 5.0)),
        ("blend", (0.0, 1.0)),
    ])
    def test_range_matches_the_filter(self, key, expected):
        assert parameters.range_for(key) == expected

    def test_the_six_tuning_parameters_are_the_relative_ones(self):
        for key in parameters.TUNING:
            assert parameters.range_for(key) == (-1.0, 1.0)

    def test_tuning_order_matches_topaz(self):
        """Topaz's own parameters[0..5] use this order; the estimate node reports in it."""
        assert parameters.TUNING == (
            "preblur", "noise", "details", "halo", "blur", "compression")

    def test_unknown_key_falls_back_rather_than_raising(self):
        assert parameters.range_for("no such parameter") == parameters.DEFAULT_RANGE


class TestClamp:
    def test_the_reported_case(self):
        """A profile carrying compression 0.3 must not become prenoise 0.3."""
        assert parameters.clamp("prenoise", 0.3) == 0.1

    def test_holds_both_ends(self):
        assert parameters.clamp("noise", 5) == 1.0
        assert parameters.clamp("noise", -5) == -1.0

    def test_a_value_inside_the_range_is_untouched(self):
        assert parameters.clamp("noise", 0.25) == 0.25

    def test_the_asymmetric_ranges_have_no_negative_half(self):
        assert parameters.clamp("prenoise", -1) == 0.0
        assert parameters.clamp("blend", -0.5) == 0.0

    def test_gsize_reaches_five(self):
        assert parameters.clamp("gsize", 9) == 5.0

    def test_strings_that_are_numbers_are_accepted(self):
        assert parameters.clamp("noise", "0.5") == 0.5

    def test_a_non_numeric_value_raises(self):
        with pytest.raises((TypeError, ValueError)):
            parameters.clamp("noise", "loud")


class TestClampAll:
    def test_unknown_keys_are_dropped(self):
        assert parameters.clamp_all({"noise": 0.5, "model": "prob-4"}) == {"noise": 0.5}

    def test_non_numeric_values_are_skipped_not_raised(self):
        assert parameters.clamp_all({"noise": "loud", "blur": 0.2}) == {"blur": 0.2}

    def test_each_key_uses_its_own_range(self):
        cleaned = parameters.clamp_all({"noise": 9, "prenoise": 9, "gsize": 9})
        assert cleaned == {"noise": 1.0, "prenoise": 0.1, "gsize": 5.0}

    def test_empty_and_none(self):
        assert parameters.clamp_all({}) == {}
        assert parameters.clamp_all(None) == {}


class TestWidgetSpec:
    def test_limits_come_from_the_table(self):
        kind, spec = parameters.widget_spec("prenoise")
        assert kind == "FLOAT"
        assert (spec["min"], spec["max"]) == (0.0, 0.1)

    def test_default_sits_inside_the_range(self):
        for key in parameters.RANGES:
            _, spec = parameters.widget_spec(key)
            assert spec["min"] <= spec["default"] <= spec["max"], key

    def test_tooltip_is_optional(self):
        _, spec = parameters.widget_spec("noise")
        assert "tooltip" not in spec
        _, spec = parameters.widget_spec("noise", "some help")
        assert spec["tooltip"] == "some help"


class TestProfilesRespectTheRanges:
    def test_every_shipped_profile_stays_in_range(self):
        """A profile is authored by hand, so this is the guard against a typo shipping."""
        for profile in profiles.load(None):
            for key, value in profile.resolve(1.0).items():
                if key not in parameters.RANGES:
                    continue
                low, high = parameters.range_for(key)
                assert low <= value <= high, f"{profile.name}: {key}={value}"

    def test_strength_above_one_cannot_push_a_value_out_of_range(self):
        """profile_strength goes to 2.0, which would double a 0.6 to 1.2."""
        for profile in profiles.load(None):
            for key, value in profile.resolve(2.0).items():
                if key not in parameters.RANGES:
                    continue
                low, high = parameters.range_for(key)
                assert low <= value <= high, f"{profile.name} at 2x: {key}={value}"

    def test_a_profile_declaring_an_out_of_range_value_is_clamped(self):
        rogue = profiles.Profile("rogue", "", options={"prenoise": 0.3, "noise": 5.0})
        resolved = rogue.resolve(1.0)
        assert resolved["prenoise"] == 0.1
        assert resolved["noise"] == 1.0
