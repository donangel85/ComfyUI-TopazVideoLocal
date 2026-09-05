"""Parsing tvai_pe output.

The sample lines are verbatim from a real run against prap-3.
"""

import pytest

from topaz_video import estimation

REAL_OUTPUT = """
Stream mapping:
  Stream #0:0 -> #0:0 (wrapped_avframe (native) -> wrapped_avframe (native))
 Parameter values:[-0.245082 ,0.0104915 ,0.228516 ,0.50298 ,0.0961366 ,0.20163 , ]
 Parameter values:[-0.263154 ,0.0129402 ,0.201192 ,0.470065 ,0.0917969 ,0.224271 , ]
 Parameter values:[-0.261709 ,0.0121044 ,0.212691 ,0.504185 ,0.0884586 ,0.230479 , ]
frame=   14 fps=0.0 q=-0.0 size=N/A time=00:00:01.75
"""


def test_parses_every_frame_line():
    frames = estimation.parse_frames(REAL_OUTPUT)
    assert len(frames) == 3
    assert all(len(f) == 6 for f in frames)


def test_first_value_is_preblur_and_may_be_negative():
    """preBlur is the only parameter with a -1..1 range."""
    frames = estimation.parse_frames(REAL_OUTPUT)
    assert frames[0][0] == pytest.approx(-0.245082)
    assert estimation.PARAMETER_ORDER[0] == "preblur"


def test_ignores_surrounding_ffmpeg_chatter():
    assert estimation.parse_frames("frame= 14 fps=0.0\nStream mapping:") == []
    assert estimation.parse_frames("") == []
    assert estimation.parse_frames(None) == []


def test_median_is_the_default_aggregation():
    frames = [[0.0] * 6, [1.0] * 6, [0.5] * 6]
    assert estimation.aggregate(frames)["noise"] == pytest.approx(0.5)


def test_median_ignores_a_single_outlier():
    """A cut or a black frame should not drag the whole clip's settings."""
    frames = [[0.0, 0.2, 0.2, 0.2, 0.2, 0.2],
              [0.0, 0.2, 0.2, 0.2, 0.2, 0.2],
              [0.0, 1.0, 1.0, 1.0, 1.0, 1.0]]
    median = estimation.aggregate(frames, "median")
    mean = estimation.aggregate(frames, "mean")
    assert median["noise"] == pytest.approx(0.2)
    assert mean["noise"] > median["noise"]


def test_results_are_clamped_to_the_declared_ranges():
    frames = [[-5.0, -5.0, 9.0, 9.0, -1.0, 2.0]]
    result = estimation.aggregate(frames)
    assert result["preblur"] == -1.0
    assert result["noise"] == 0.0        # noise range is 0..1, not -1..1
    assert result["details"] == 1.0


def test_all_six_parameters_are_named():
    result = estimation.aggregate(estimation.parse_frames(REAL_OUTPUT))
    assert set(result) == set(estimation.PARAMETER_ORDER)


def test_parameter_names_match_the_filter_options():
    """These keys go straight into tvai_up, so they must be its option names."""
    assert estimation.PARAMETER_ORDER == (
        "preblur", "noise", "details", "halo", "blur", "compression")


def test_empty_input_aggregates_to_nothing():
    assert estimation.aggregate([]) == {}
    assert estimation.describe({}) == "no estimate produced"


def test_spread_reports_min_and_max():
    """Values are rounded to 4 decimals for display."""
    spread = estimation.spread(estimation.parse_frames(REAL_OUTPUT))
    low, high = spread["preblur"]
    assert low == pytest.approx(-0.2632, abs=1e-4)
    assert high == pytest.approx(-0.2451, abs=1e-4)
    assert low < high
