"""Topaz Resolution — pick an output size by name instead of typing two numbers.

Outputs plain ``INT`` width and height rather than a private type, so this feeds the
Topaz upscale nodes and equally MiniMax-H3, LTX2.5 or anything else that takes
dimensions. That matters, because the divisibility constraint this node exists to solve
belongs to those models, not to Topaz: MiniMax-H3 only accepts multiples of 32, so Full
HD there is 1920x1088.
"""

from __future__ import annotations

from ..topaz_studio import resolutions
from ..topaz_studio.logging_util import get_logger

from .common import CATEGORY

logger = get_logger()

# Powers of two cover every latent video model in practice — the constraint comes from
# how far the encoder downsamples. custom_divisor is there for anything that is not.
_DIVISORS = [1, 2, 4, 8, 16, 32, 64, 128]


class TopazResolution:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "preset": (resolutions.labels(), {
                    "default": "Full HD 1080p (1920x1080)",
                    "tooltip": "Named output size. 'custom' uses the width and height "
                               "below. Note the two entries that both get called 2K: "
                               "QHD is 2560x1440, DCI 2K is 2048x1080.",
                }),
                "orientation": (list(resolutions.ORIENTATIONS), {
                    "default": resolutions.LANDSCAPE,
                    "tooltip": "portrait swaps width and height. square takes the "
                               "shorter edge, so 1080p becomes 1080x1080.",
                }),
                "divisible_by": (_DIVISORS, {
                    "default": 1,
                    "tooltip": "Force both edges to a multiple of this. Many video "
                               "models require it — MiniMax-H3 needs 32, which turns "
                               "1920x1080 into 1920x1088. 1 means no constraint.",
                }),
                "rounding": (list(resolutions.ROUNDING_MODES), {
                    "default": resolutions.UP,
                    "tooltip": "Which way to move a size that does not divide evenly. "
                               "up never returns less than you asked for; down never "
                               "returns more; nearest keeps the smallest difference.",
                }),
            },
            "optional": {
                "custom_width": ("INT", {
                    "default": 1920, "min": resolutions.MIN_DIMENSION, "max": 16384,
                    "step": 1,
                    "tooltip": "Used only when preset is 'custom'. Still snapped to "
                               "divisible_by.",
                }),
                "custom_height": ("INT", {
                    "default": 1080, "min": resolutions.MIN_DIMENSION, "max": 16384,
                    "step": 1,
                    "tooltip": "Used only when preset is 'custom'. Still snapped to "
                               "divisible_by.",
                }),
                "custom_divisor": ("INT", {
                    "default": 0, "min": 0, "max": 256, "step": 1,
                    "tooltip": "Overrides divisible_by when above 0, for the rare model "
                               "whose constraint is not a power of two.",
                }),
            },
        }

    RETURN_TYPES = ("INT", "INT", "STRING")
    RETURN_NAMES = ("width", "height", "info")
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Output resolution by name, with orientation and a divisibility "
                   "constraint. Width and height are plain INTs, so this drives the "
                   "Topaz nodes and any other node that takes dimensions.")

    def build(self, preset, orientation, divisible_by, rounding,
              custom_width=1920, custom_height=1080, custom_divisor=0):
        divisor = int(custom_divisor) if int(custom_divisor) > 0 else int(divisible_by)

        width, height = resolutions.resolve(
            preset, orientation,
            custom_width=int(custom_width), custom_height=int(custom_height),
            divisor=divisor, rounding=rounding,
        )

        info = resolutions.describe(width, height, divisor)
        entry = resolutions.find(preset)
        if entry is not None and divisor > 1:
            asked = resolutions.orient(entry.width, entry.height, orientation)
            if (width, height) != asked:
                logger.info("resolution %s %s snapped %dx%d -> %dx%d for divisor %d (%s)",
                            entry.name, orientation, asked[0], asked[1],
                            width, height, divisor, rounding)
        logger.debug("resolution -> %s", info)
        return (width, height, info)
