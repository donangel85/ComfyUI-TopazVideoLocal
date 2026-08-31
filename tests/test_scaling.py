"""Scale arithmetic for single and multi-pass upscaling."""

import pytest

from topaz_studio.scaling import (
    FILL,
    FIT,
    STRETCH,
    chain_scale,
    describe_chain,
    factor_for_target,
    fit_filters,
)


def test_exact_factor_is_chosen():
    assert factor_for_target((1, 2, 4), 320, 240, 640, 480) == 2


def test_fractional_target_rounds_up_not_down():
    """1.5x must pick 2 and resample down. Rounding to 1 would mean no AI upscaling."""
    assert factor_for_target((1, 2, 4), 320, 240, 480, 360) == 2


def test_target_smaller_than_input_still_uses_the_smallest_factor():
    assert factor_for_target((1, 2, 4), 320, 240, 160, 120) == 1


def test_unsupported_intermediate_factor_steps_up():
    """pnat-1 only allows 2, so a 1.2x request must use 2."""
    assert factor_for_target((2,), 320, 240, 384, 288) == 2


def test_target_beyond_the_largest_factor_uses_the_largest():
    assert factor_for_target((1, 2, 4), 320, 240, 4000, 3000) == 4


def test_the_wider_dimension_decides():
    # Needs 3x horizontally but only 1.5x vertically -> must cover both.
    assert factor_for_target((1, 2, 4), 320, 240, 960, 360) == 4


def test_empty_scales_falls_back_to_the_usual_set():
    assert factor_for_target((), 320, 240, 640, 480) == 2


def test_chain_scale_multiplies():
    chain = [{"model": "prob-4", "scale": 2}, {"model": "prob-4", "scale": 2}]
    assert chain_scale(chain) == 4


def test_chain_scale_of_empty_chain_is_one():
    assert chain_scale(None) == 1
    assert chain_scale([]) == 1


def test_chain_scale_ignores_identity_stages():
    chain = [{"model": "prob-4", "scale": 2}, {"model": "pnat-1", "scale": 1}]
    assert chain_scale(chain) == 2


def test_describe_chain_is_readable():
    chain = [{"model": "pnat-1", "scale": 2}, {"model": "prob-4", "scale": 2}]
    assert describe_chain(chain) == "pnat-1@2x -> prob-4@2x"
    assert describe_chain([]) == "(empty)"


def test_describe_chain_names_a_target_instead_of_a_guessed_factor():
    """Under target_size the factor is only known at render time, so the description
    reports the size that was asked for rather than inventing a multiplier."""
    chain = [{"model": "prob-4", "scale": 2, "target": (1920, 1088)}]
    assert describe_chain(chain) == "prob-4@1920x1088"


class TestFitModeAffectsTheFactor:
    """Under fit the frame only has to land *inside* the target box, so the smaller
    ratio decides. fill and stretch have to cover it, so the larger one does."""

    def test_fit_needs_less_upscaling_than_fill(self):
        # 320x240 into 1000x480: 3.125x horizontally, 2x vertically.
        # fit only has to reach 2x, fill has to reach 3.125x.
        assert factor_for_target((1, 2, 4), 320, 240, 1000, 480, FIT) == 2
        assert factor_for_target((1, 2, 4), 320, 240, 1000, 480, FILL) == 4

    def test_stretch_behaves_like_fill(self):
        assert (factor_for_target((1, 2, 4), 320, 240, 1000, 480, STRETCH)
                == factor_for_target((1, 2, 4), 320, 240, 1000, 480, FILL))

    def test_default_is_the_covering_behaviour(self):
        """Existing callers passed no mode and must keep the factor they had."""
        assert (factor_for_target((1, 2, 4), 320, 240, 960, 360)
                == factor_for_target((1, 2, 4), 320, 240, 960, 360, FILL))

    def test_matching_aspect_ratios_agree_in_every_mode(self):
        for mode in (FIT, FILL, STRETCH):
            assert factor_for_target((1, 2, 4), 320, 240, 640, 480, mode) == 2


class TestFitFilters:
    def test_stretch_is_a_single_scale(self):
        filters = fit_filters(STRETCH, 1920, 1088)
        assert filters == ["scale=1920:1088:flags=lanczos"]

    def test_fit_scales_down_then_pads(self):
        filters = fit_filters(FIT, 1920, 1088)
        assert len(filters) == 2
        assert "force_original_aspect_ratio=decrease" in filters[0]
        assert filters[1].startswith("pad=1920:1088:")
        assert "color=black" in filters[1]

    def test_fill_scales_up_then_crops(self):
        filters = fit_filters(FILL, 1920, 1088)
        assert len(filters) == 2
        assert "force_original_aspect_ratio=increase" in filters[0]
        assert filters[1] == "crop=1920:1088"

    @pytest.mark.parametrize("mode", [FIT, FILL, STRETCH])
    def test_every_mode_ends_at_the_exact_target(self, mode):
        """An IMAGE batch has to be one size; a mismatch only surfaces later as a raw
        byte count that will not divide evenly."""
        assert f"{1920}:{1088}" in fit_filters(mode, 1920, 1088)[-1]

    @pytest.mark.parametrize("mode", [FIT, FILL, STRETCH])
    def test_no_entry_contains_a_comma(self, mode):
        """The caller joins the whole chain on commas, so a filter carrying one of its
        own would split into two broken halves."""
        for entry in fit_filters(mode, 1920, 1088):
            assert "," not in entry
