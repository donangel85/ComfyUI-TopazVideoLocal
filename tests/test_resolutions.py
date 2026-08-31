"""Tests for the named resolutions and divisibility snapping.

The case that motivated all of this: MiniMax-H3 only accepts dimensions that are a
multiple of 32, so Full HD there is 1920x1088, not 1920x1080. Getting it wrong surfaces
much later as a tensor-shape error somewhere else entirely.
"""

import pytest

from topaz_studio import resolutions as res


class TestSnap:
    def test_the_minimax_case(self):
        assert res.snap(1080, 32, res.UP) == 1088
        assert res.snap(1920, 32, res.UP) == 1920  # already a multiple, left alone

    @pytest.mark.parametrize("mode,expected", [
        (res.UP, 1088),
        (res.NEAREST, 1088),   # 1080 is 33.75 divisors, so nearest also goes up
        (res.DOWN, 1056),
    ])
    def test_rounding_modes(self, mode, expected):
        assert res.snap(1080, 32, mode) == expected

    def test_nearest_can_go_down(self):
        # 1090 is 34.06 divisors: up gives 1120, nearest stays at 1088.
        assert res.snap(1090, 32, res.NEAREST) == 1088
        assert res.snap(1090, 32, res.UP) == 1120

    def test_nearest_halfway_goes_up(self):
        assert res.snap(16, 32, res.NEAREST) == 32

    @pytest.mark.parametrize("divisor", [0, 1])
    def test_no_constraint(self, divisor):
        assert res.snap(1080, divisor) == 1080

    def test_exact_multiples_are_untouched_in_every_mode(self):
        for mode in res.ROUNDING_MODES:
            assert res.snap(2048, 32, mode) == 2048

    def test_rounding_down_never_collapses_a_dimension(self):
        # 100 // 512 is 0; a zero-height frame is far worse than a too-small one.
        assert res.snap(100, 512, res.DOWN) == 512

    def test_result_never_below_the_minimum(self):
        assert res.snap(1, 1) >= res.MIN_DIMENSION

    def test_common_divisors(self):
        assert res.snap(1080, 8, res.UP) == 1080     # 1080 is 135 * 8
        assert res.snap(1080, 16, res.UP) == 1088
        assert res.snap(1080, 64, res.UP) == 1088
        assert res.snap(2160, 32, res.UP) == 2176


class TestOrient:
    def test_landscape_is_the_stored_form(self):
        assert res.orient(1920, 1080, res.LANDSCAPE) == (1920, 1080)

    def test_portrait_transposes(self):
        assert res.orient(1920, 1080, res.PORTRAIT) == (1080, 1920)

    def test_square_takes_the_shorter_edge(self):
        # Taking the longer edge would invent detail that is not in the frame.
        assert res.orient(1920, 1080, res.SQUARE) == (1080, 1080)


class TestTable:
    def test_every_entry_is_landscape(self):
        for entry in res.table():
            assert entry.width >= entry.height, f"{entry.name} is stored portrait"

    def test_labels_end_with_custom(self):
        assert res.labels()[-1] == res.CUSTOM

    def test_labels_are_unique(self):
        labels = res.labels()
        assert len(labels) == len(set(labels))

    def test_two_k_is_never_ambiguous(self):
        """DCI 2K and QHD both get called '2K'; a single entry would silently give half
        the users the size they did not want."""
        names = [entry.name for entry in res.table()]
        assert "DCI 2K" in names and "QHD 1440p" in names
        assert "2K" not in names

    def test_find_by_label_and_by_name(self):
        entry = res.find("Full HD 1080p")
        assert entry is not None and (entry.width, entry.height) == (1920, 1080)
        assert res.find(entry.label) is entry

    def test_find_returns_none_for_custom(self):
        assert res.find(res.CUSTOM) is None
        assert res.find("") is None
        assert res.find("no such size") is None


class TestResolve:
    def test_named_landscape(self):
        assert res.resolve("UHD 4K") == (3840, 2160)

    def test_named_portrait(self):
        assert res.resolve("Full HD 1080p", res.PORTRAIT) == (1080, 1920)

    def test_the_minimax_full_hd_case(self):
        assert res.resolve("Full HD 1080p", divisor=32) == (1920, 1088)

    def test_portrait_and_divisor_together(self):
        # Snapping runs after the transpose, so both edges satisfy the divisor.
        width, height = res.resolve("Full HD 1080p", res.PORTRAIT, divisor=32)
        assert (width, height) == (1088, 1920)
        assert width % 32 == 0 and height % 32 == 0

    def test_custom_size(self):
        assert res.resolve(res.CUSTOM, custom_width=1234,
                           custom_height=567) == (1234, 567)

    def test_custom_size_is_snapped_too(self):
        assert res.resolve(res.CUSTOM, custom_width=1234, custom_height=567,
                           divisor=32) == (1248, 576)

    def test_every_table_entry_snaps_cleanly_at_32(self):
        for entry in res.table():
            for orientation in res.ORIENTATIONS:
                width, height = res.resolve(entry.name, orientation, divisor=32)
                assert width % 32 == 0 and height % 32 == 0, entry.name

    def test_unknown_preset_falls_back_to_custom(self):
        assert res.resolve("not a preset", custom_width=800,
                           custom_height=600) == (800, 600)


class TestDescribe:
    def test_names_a_common_ratio(self):
        assert "16:9" in res.describe(1920, 1080)
        assert "9:16" in res.describe(1080, 1920)

    def test_snapped_size_still_reads_as_16_9(self):
        # 1920x1088 is 1.765, not 1.778 -- close enough to name rather than confuse.
        assert "16:9" in res.describe(1920, 1088)

    def test_reports_the_divisor(self):
        assert "/32" in res.describe(1920, 1088, 32)
        assert "NOT DIVISIBLE" not in res.describe(1920, 1088, 32)

    def test_flags_a_size_that_does_not_satisfy_the_divisor(self):
        assert "NOT DIVISIBLE" in res.describe(1920, 1080, 32)

    def test_unusual_ratio_falls_back_to_a_number(self):
        assert ":1" in res.describe(1000, 333)
