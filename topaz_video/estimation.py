"""Parsing the output of the tvai_pe parameter-estimation filter.

``tvai_pe`` has no output file and no options beyond ``model`` and ``download``. It writes
one line per analysed frame to **stderr**:

    Parameter values:[-0.245082 ,0.0104915 ,0.228516 ,0.50298 ,0.0961366 ,0.20163 , ]

The six values are the tvai_up tuning parameters, in the order the model JSONs declare
them (``prob-4.json`` → ``parameters[0..5]``):

    preBlur, noise, details, halo, blur, compression

The ranges confirm the mapping: only ``preBlur`` runs -1..1, the rest 0..1, and only the
first value in the observed output is ever negative.

Kept free of ComfyUI and of any subprocess handling so it can be unit-tested against
captured output.
"""

from __future__ import annotations

import re
import statistics

# Order is load-bearing: it comes from the model JSON's own parameter list.
PARAMETER_ORDER = ("preblur", "noise", "details", "halo", "blur", "compression")

_LINE = re.compile(r"Parameter values:\s*\[([^\]]*)\]", re.IGNORECASE)
_NUMBER = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

# Ranges as declared by the models; used to clamp aggregated results.
_RANGES = {
    "preblur": (-1.0, 1.0),
    "noise": (0.0, 1.0),
    "details": (0.0, 1.0),
    "halo": (0.0, 1.0),
    "blur": (0.0, 1.0),
    "compression": (0.0, 1.0),
}


def parse_frames(text: str) -> list[list[float]]:
    """Every per-frame parameter vector found in *text*."""
    frames = []
    for match in _LINE.finditer(text or ""):
        values = [float(v) for v in _NUMBER.findall(match.group(1))]
        if len(values) >= len(PARAMETER_ORDER):
            frames.append(values[:len(PARAMETER_ORDER)])
    return frames


def aggregate(frames: list[list[float]], method: str = "median") -> dict:
    """Collapse per-frame estimates into one parameter set.

    Median by default: a single odd frame — a cut, a flash, a black frame — should not
    drag the whole clip's settings with it.
    """
    if not frames:
        return {}

    columns = list(zip(*frames))
    if method == "mean":
        values = [statistics.fmean(c) for c in columns]
    else:
        values = [statistics.median(c) for c in columns]

    result = {}
    for name, value in zip(PARAMETER_ORDER, values):
        low, high = _RANGES[name]
        result[name] = max(low, min(high, round(float(value), 4)))
    return result


def describe(params: dict) -> str:
    if not params:
        return "no estimate produced"
    return ", ".join(f"{k}={params[k]:g}" for k in PARAMETER_ORDER if k in params)


def spread(frames: list[list[float]]) -> dict:
    """Per-parameter min/max across frames.

    Useful for judging whether one setting fits the whole clip: a wide spread means the
    material changes character partway through.
    """
    if not frames:
        return {}
    columns = list(zip(*frames))
    return {name: (round(min(c), 4), round(max(c), 4))
            for name, c in zip(PARAMETER_ORDER, columns)}
