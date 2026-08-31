"""Scale arithmetic for single and multi-pass upscaling.

Pure logic, no ComfyUI and no Topaz process involved, so it is unit-testable.
"""

from __future__ import annotations


def factor_for_target(scales, in_width: int, in_height: int,
                      out_width: int, out_height: int) -> int:
    """Smallest supported integer scale that reaches at least the target size.

    tvai_up only scales by whole numbers. Its ``w``/``h`` options are merely a hint it
    uses to *estimate* a scale, and for a 1.5x request it settles on 1 — meaning no AI
    upscaling happens at all. Choosing the next factor up and resampling down keeps the
    detail the model produced.
    """
    supported = sorted(s for s in (scales or (1, 2, 3, 4)) if s >= 1) or [1]
    needed = max(out_width / max(in_width, 1), out_height / max(in_height, 1))
    for scale in supported:
        if scale >= needed:
            return scale
    return supported[-1]


def chain_scale(chain) -> int:
    """Combined scale factor of every stage in a chain: 2x then 2x is 4x."""
    total = 1
    for stage in (chain or []):
        total *= int(stage.get("scale", 1))
    return total


def describe_chain(chain) -> str:
    parts = [f"{s.get('model', '?')}@{s.get('scale', 1)}x" for s in (chain or [])]
    return " -> ".join(parts) or "(empty)"
