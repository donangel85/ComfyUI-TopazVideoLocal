"""Valid ranges for the tvai_up tuning parameters.

One table, because the same numbers were needed in four places and had already drifted:
profiles clamped everything to -1..1, the user-preset store carried its own per-key
table, the widget declarations spelled the limits out again, and the browser payload
clamped nothing at all.

That drift is not cosmetic. ``prenoise`` runs 0..0.1, so a profile carrying 0.3 would be
passed straight through to a filter that rejects it — and, once a preset can fill the
sliders, written into a widget that refuses it:

    Value 0.3 bigger than max of 0.1: prenoise

Read from the filter's own help text (``ffmpeg -h filter=tvai_up``), not from
documentation.
"""

from __future__ import annotations

# Relative to what the model detects in the input, which is why most run -1..1 with 0
# meaning "leave it to the model".
TUNING = ("preblur", "noise", "details", "halo", "blur", "compression")

# The rest are absolute amounts rather than relative corrections, hence their own ranges.
RANGES: dict[str, tuple[float, float]] = {
    "preblur": (-1.0, 1.0),
    "noise": (-1.0, 1.0),
    "details": (-1.0, 1.0),
    "halo": (-1.0, 1.0),
    "blur": (-1.0, 1.0),
    "compression": (-1.0, 1.0),
    "prenoise": (0.0, 0.1),
    "grain": (0.0, 1.0),
    "gsize": (0.0, 5.0),
    "blend": (0.0, 1.0),
}

# Keys a preset may carry. Anything else in a payload is dropped rather than trusted.
KNOWN = frozenset(RANGES)

DEFAULT_RANGE = (-1.0, 1.0)


def range_for(key: str) -> tuple[float, float]:
    return RANGES.get(key, DEFAULT_RANGE)


def clamp(key: str, value) -> float:
    """Coerce to float and hold to the parameter's own range.

    Raises the same exceptions ``float()`` does for a value that is not numeric at all;
    callers that accept untrusted input catch them.
    """
    low, high = range_for(key)
    return max(low, min(high, float(value)))


def clamp_all(values: dict) -> dict:
    """Clamp every known key, skipping anything unknown or non-numeric."""
    clean = {}
    for key, value in (values or {}).items():
        if key not in KNOWN:
            continue
        try:
            clean[key] = clamp(key, value)
        except (TypeError, ValueError):
            continue
    return clean


def widget_spec(key: str, tooltip: str = "", step: float = 0.01) -> tuple:
    """A ComfyUI FLOAT widget declaration whose limits cannot drift from this table."""
    low, high = range_for(key)
    spec = {"default": 0.0, "min": low, "max": high, "step": step}
    if tooltip:
        spec["tooltip"] = tooltip
    return ("FLOAT", spec)
