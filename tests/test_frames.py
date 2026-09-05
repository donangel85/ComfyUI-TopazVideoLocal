"""Tensor <-> raw bytes round trip, and the minimum-batch guard."""

import sys
from pathlib import Path

import numpy as np
import pytest


from topaz_video import frames  # noqa: E402


def batch(count=4, height=8, width=6, channels=3):
    rng = np.random.default_rng(1234)
    return rng.random((count, height, width, channels), dtype=np.float32)


def test_round_trip_preserves_geometry_and_values():
    original = batch()
    payload, count, width, height = frames.tensor_to_rgb24(original)
    assert (count, width, height) == (4, 6, 8)
    assert len(payload) == count * width * height * 3

    restored = np.asarray(frames.rgb24_to_tensor(payload, width, height))
    assert restored.shape == original.shape
    # 8-bit quantisation is the only loss.
    assert np.abs(restored - original).max() <= 1.5 / 255.0


def test_alpha_channel_is_dropped():
    payload, count, width, height = frames.tensor_to_rgb24(batch(channels=4))
    assert len(payload) == count * width * height * 3


def test_greyscale_is_expanded():
    payload, count, width, height = frames.tensor_to_rgb24(batch(channels=1))
    assert len(payload) == count * width * height * 3


def test_single_image_without_batch_dimension():
    payload, count, _, _ = frames.tensor_to_rgb24(batch(count=1)[0])
    assert count == 1


def test_values_are_clipped():
    data = np.array([[[[-5.0, 0.5, 9.0]]]], dtype=np.float32)
    payload, _, _, _ = frames.tensor_to_rgb24(data)
    assert payload[0] == 0
    assert payload[2] == 255


def test_padding_reaches_the_minimum():
    """1-3 frames crash tvai_up with an access violation, so short batches are padded."""
    payload, count, width, height = frames.tensor_to_rgb24(batch(count=2))
    padded, added = frames.pad_to_minimum(payload, count, width, height, 4)
    assert added == 2
    assert len(padded) == 4 * width * height * 3


def test_padding_repeats_the_last_frame():
    payload, count, width, height = frames.tensor_to_rgb24(batch(count=2))
    padded, _ = frames.pad_to_minimum(payload, count, width, height, 4)
    frame_bytes = width * height * 3
    last_original = padded[frame_bytes:2 * frame_bytes]
    assert padded[2 * frame_bytes:3 * frame_bytes] == last_original
    assert padded[3 * frame_bytes:4 * frame_bytes] == last_original


def test_no_padding_when_already_long_enough():
    payload, count, width, height = frames.tensor_to_rgb24(batch(count=6))
    padded, added = frames.pad_to_minimum(payload, count, width, height, 4)
    assert added == 0
    assert padded is payload


def test_trim_removes_exactly_the_padding():
    images = batch(count=6)
    assert len(frames.trim_padding(images, 2)) == 4
    assert len(frames.trim_padding(images, 0)) == 6


def test_trim_refuses_to_empty_the_batch():
    images = batch(count=2)
    assert len(frames.trim_padding(images, 5)) == 2


def test_partial_frame_is_rejected():
    """A truncated stream must fail loudly, not reshape into noise."""
    with pytest.raises(ValueError, match="whole number"):
        frames.rgb24_to_tensor(b"\x00" * 100, 6, 8)


def test_empty_output_is_rejected():
    with pytest.raises(ValueError, match="no output"):
        frames.rgb24_to_tensor(b"", 6, 8)
