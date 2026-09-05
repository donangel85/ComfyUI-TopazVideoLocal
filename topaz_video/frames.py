"""Conversion between ComfyUI IMAGE tensors and raw RGB24 bytes.

ComfyUI IMAGE is a float32 tensor shaped (B, H, W, C) with values in 0..1.
Topaz's FFmpeg is fed packed rgb24, which is what ``-pix_fmt rgb24`` expects.

Also handles the minimum-batch problem: with fewer than four frames ``tvai_up`` does not
report an error, it crashes the process with an access violation (0xC0000005). Short
batches are padded here and trimmed again afterwards.
"""

from __future__ import annotations

import numpy as np

# Established experimentally: 1-3 frames crash, 4 works. Temporal models look at
# neighbouring frames, so a minimum window is required.
MIN_FRAMES = 4


def tensor_to_rgb24(images) -> tuple[bytes, int, int, int]:
    """Return ``(payload, count, width, height)`` for a ComfyUI IMAGE batch."""
    array = _to_numpy(images)
    if array.ndim == 3:
        array = array[None, ...]
    if array.ndim != 4:
        raise ValueError(f"expected an IMAGE batch of shape (B,H,W,C), got {array.shape}")

    count, height, width, channels = array.shape
    if channels == 4:
        array = array[..., :3]        # drop alpha; Topaz works on RGB
    elif channels == 1:
        array = np.repeat(array, 3, axis=-1)
    elif channels != 3:
        raise ValueError(f"unsupported channel count: {channels}")

    array = np.clip(array, 0.0, 1.0)
    payload = (array * 255.0 + 0.5).astype(np.uint8, copy=False)
    return payload.tobytes(), int(count), int(width), int(height)


def rgb24_to_tensor(payload: bytes, width: int, height: int):
    """Rebuild a ComfyUI IMAGE batch from raw rgb24 bytes."""
    frame_bytes = int(width) * int(height) * 3
    if frame_bytes <= 0:
        raise ValueError("invalid frame geometry")
    if not payload:
        raise ValueError("Topaz produced no output frames")

    usable = len(payload) - (len(payload) % frame_bytes)
    if usable != len(payload):
        # Should not happen with the file sink; guard anyway so a stray byte cannot
        # reshape the whole batch into noise.
        raise ValueError(
            f"output is not a whole number of {width}x{height} frames "
            f"({len(payload)} bytes, frame is {frame_bytes})"
        )

    array = np.frombuffer(payload, dtype=np.uint8)
    array = array.reshape(-1, int(height), int(width), 3)
    result = array.astype(np.float32) / 255.0
    return _to_torch(result)


def pad_to_minimum(payload: bytes, count: int, width: int, height: int,
                   minimum: int = MIN_FRAMES) -> tuple[bytes, int]:
    """Repeat the last frame until *minimum* is reached.

    Returns ``(payload, padding_added)``. The caller must drop ``padding_added`` frames
    from the result.
    """
    if count >= minimum or count == 0:
        return payload, 0
    frame_bytes = width * height * 3
    last = payload[(count - 1) * frame_bytes: count * frame_bytes]
    missing = minimum - count
    return payload + last * missing, missing


def trim_padding(images, padding: int):
    """Remove frames appended by :func:`pad_to_minimum`."""
    if padding <= 0:
        return images
    if len(images) <= padding:
        return images
    return images[:-padding]


def _to_numpy(images):
    if isinstance(images, np.ndarray):
        return images
    cpu = getattr(images, "cpu", None)
    if cpu is not None:
        return cpu().numpy()
    return np.asarray(images)


def _to_torch(array):
    try:
        import torch
    except ImportError:
        return array
    return torch.from_numpy(array)
