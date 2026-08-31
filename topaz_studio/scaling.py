"""Scale arithmetic for single and multi-pass upscaling.

Pure logic, no ComfyUI and no Topaz process involved, so it is unit-testable.
"""

from __future__ import annotations

STRETCH = "stretch"
FIT = "fit"
FILL = "fill"
FIT_MODES = (FIT, FILL, STRETCH)


def factor_for_target(scales, in_width: int, in_height: int,
                      out_width: int, out_height: int,
                      fit_mode: str = FILL) -> int:
    """Smallest supported integer scale that reaches at least the target size.

    tvai_up only scales by whole numbers. Its ``w``/``h`` options are merely a hint it
    uses to *estimate* a scale, and for a 1.5x request it settles on 1 — meaning no AI
    upscaling happens at all. Choosing the next factor up and resampling down keeps the
    detail the model produced.

    How much is "enough" depends on how the frame is fitted into the target box. Under
    ``fit`` the image only has to fit *inside* it, so the smaller of the two ratios is
    the one to satisfy; ``fill`` and ``stretch`` need the larger one. Using the larger
    ratio for ``fit`` would still look right, just with a wasted pass of AI upscaling
    before the result is resampled back down.
    """
    supported = sorted(s for s in (scales or (1, 2, 3, 4)) if s >= 1) or [1]
    horizontal = out_width / max(in_width, 1)
    vertical = out_height / max(in_height, 1)
    needed = min(horizontal, vertical) if fit_mode == FIT \
        else max(horizontal, vertical)
    for scale in supported:
        if scale >= needed:
            return scale
    return supported[-1]


def fit_filters(fit_mode: str, out_width: int, out_height: int) -> list[str]:
    """FFmpeg filters that put the frame into an exact ``out_width`` x ``out_height`` box.

    Every mode ends at exactly that size — an IMAGE batch has to be one size, and a
    mismatch would only surface as a raw byte count that will not divide evenly.

    * ``stretch`` resamples both axes independently; the aspect ratio changes.
    * ``fit`` keeps the aspect ratio and pads the remainder with black.
    * ``fill`` keeps the aspect ratio and crops what does not fit.

    Returned as separate entries rather than one comma-joined string, because the caller
    joins the whole chain on commas.
    """
    width, height = int(out_width), int(out_height)
    if fit_mode == FIT:
        return [
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
        ]
    if fit_mode == FILL:
        return [
            f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos",
            f"crop={width}:{height}",
        ]
    return [f"scale={width}:{height}:flags=lanczos"]


def chain_scale(chain) -> int:
    """Combined scale factor of every stage in a chain: 2x then 2x is 4x."""
    total = 1
    for stage in (chain or []):
        total *= int(stage.get("scale", 1))
    return total


def describe_chain(chain) -> str:
    parts = []
    for stage in (chain or []):
        target = stage.get("target")
        if target:
            # The factor is not known until render time under target_size, so naming a
            # multiplier here would be a guess. Report what was actually asked for.
            parts.append(f"{stage.get('model', '?')}@{target[0]}x{target[1]}")
        else:
            parts.append(f"{stage.get('model', '?')}@{stage.get('scale', 1)}x")
    return " -> ".join(parts) or "(empty)"
