"""Scale arithmetic for single and multi-pass upscaling."""

from topaz_studio.scaling import chain_scale, describe_chain, factor_for_target


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
