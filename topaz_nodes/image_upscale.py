"""Topaz Image Upscale — still images through the Topaz Video engine.

Topaz Gigapixel cannot be automated (its CLI needs an enterprise licence), but
``tvai_up`` works on stills just as well as on video, and Topaz's ffmpeg reads and writes
PNG/TIFF. So this covers a good part of the same ground using the models the Video
licence already unlocks.

The one thing that needs care is batch semantics. Upscale models are *temporal*: they
look at neighbouring frames. Feeding a batch of unrelated photos through as one sequence
would let them bleed into each other. Hence the explicit choice below.
"""

from __future__ import annotations

import numpy as np

from ..topaz_studio import models
from ..topaz_studio.engine import EngineSettings, FilterSpec, TopazEngine
from ..topaz_studio.frames import MIN_FRAMES
from ..topaz_studio.logging_util import get_logger

from .common import (
    CATEGORY,
    default_model,
    interrupt_check,
    model_choices,
    settings_from_input,
)
from ..topaz_studio.command import render_parameters_dict
from ..topaz_studio.scaling import (
    FIT,
    FIT_MODES,
    describe_chain,
    factor_for_target,
    fit_filters,
)
from .upscale_chain import build_chain_segments
from .video_upscale import _RawSpec

logger = get_logger()


class TopazImageUpscale:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "model": (model_choices(models.UPSCALE), {
                    "default": default_model(models.UPSCALE, "prob-4"),
                }),
                "scale_mode": (["factor", "target_size"], {"default": "factor"}),
                "scale_factor": ([1, 2, 3, 4], {"default": 2}),
                "batch_mode": (["independent_images", "sequence"], {
                    "default": "independent_images",
                    "tooltip": "independent_images: each picture is processed on its "
                               "own. Correct for unrelated photos, but slower — Topaz "
                               "needs at least 4 frames, so each image is repeated. "
                               "sequence: treat the batch as consecutive video frames. "
                               "Much faster, but only right if they really are a "
                               "sequence.",
                }),
            },
            "optional": {
                "target_width": ("INT", {"default": 2048, "min": 16, "max": 16384,
                                         "step": 8}),
                "target_height": ("INT", {"default": 2048, "min": 16, "max": 16384,
                                          "step": 8}),
                "fit_mode": (list(FIT_MODES), {
                    "default": FIT,
                    "tooltip": "Only applies to target_size. fit: keep the aspect "
                               "ratio, pad the remainder black. fill: keep it and crop "
                               "the overflow. stretch: hit the exact size and let the "
                               "aspect ratio change. fit is the safe default for a "
                               "square target, which would otherwise distort every "
                               "photo that is not already square.",
                }),
                "params": ("TOPAZ_UPSCALE_PARAMS",),
                "upscale_chain": ("TOPAZ_UPSCALE_CHAIN", {
                    "tooltip": "Extra passes from Topaz Upscale Stage nodes. They run "
                               "first, in order, and this node's own model runs last — "
                               "all inside a single ffmpeg call. Particularly useful on "
                               "stills: repair on the first pass, resolution on the "
                               "second.",
                }),
                "engine": ("TOPAZ_ENGINE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "upscale"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Upscale still images with Topaz Video's AI models. An alternative to "
                   "Gigapixel, whose CLI requires an enterprise licence.")

    def upscale(self, images, model, scale_mode, scale_factor, batch_mode,
                target_width=2048, target_height=2048, fit_mode=FIT, params=None,
                upscale_chain=None, engine=None):
        settings: EngineSettings = settings_from_input(engine)
        topaz = TopazEngine(settings)
        topaz.check_license()
        chosen = topaz.resolve_model(model, models.UPSCALE)

        in_height, in_width = int(images.shape[1]), int(images.shape[2])

        segments, width, height = build_chain_segments(
            topaz, upscale_chain, in_width, in_height)

        options = dict(topaz.base_options())
        options["model"] = chosen.short_code

        post_filters = []
        if scale_mode == "factor":
            factor = int(scale_factor)
            if not chosen.supports_scale(factor):
                supported = ", ".join(str(s) for s in chosen.scales) or "unknown"
                raise ValueError(
                    f"{chosen.display_name} ({chosen.short_code}) does not support "
                    f"scale {factor}. Supported: {supported}."
                )
            options["scale"] = factor
            out_width, out_height = width * factor, height * factor
        else:
            out_width, out_height = int(target_width), int(target_height)
            factor = factor_for_target(chosen.scales, width, height,
                                       out_width, out_height, fit_mode)
            options["scale"] = factor
            post_filters.extend(fit_filters(fit_mode, out_width, out_height))

        extra = {}
        if params:
            tuning = dict(params)
            extra = tuning.pop("_extra_parameters", {}) or {}
            options.update(tuning)
        else:
            options.setdefault("estimate", 0)
        if extra:
            options["parameters"] = render_parameters_dict(extra)

        segments.append(FilterSpec(models.UPSCALE, options).render())
        chain = ",".join(segments + post_filters)

        count = int(images.shape[0])
        if upscale_chain:
            logger.info("image upscale chain: %s then %s (%dx%d before this node)",
                        describe_chain(upscale_chain), chosen.label, width, height)
        logger.info("image upscale %dx%d -> %dx%d, %d image(s), %s, %s, "
                    "%d Topaz pass(es)",
                    in_width, in_height, out_width, out_height, count,
                    chosen.label, batch_mode, len(segments))

        if batch_mode == "sequence" or count == 1:
            result = topaz.process(
                images, _RawSpec(chain), fps=24.0,
                out_width=out_width, out_height=out_height, model=chosen,
                interrupt_check=interrupt_check,
            )
            return (result,)

        # Independent images: run each one on its own so temporal models cannot mix
        # content from different pictures.
        outputs = []
        for index in range(count):
            single = images[index: index + 1]
            processed = topaz.process(
                single, _RawSpec(chain), fps=24.0,
                out_width=out_width, out_height=out_height, model=chosen,
                interrupt_check=interrupt_check,
            )
            # process() pads a 1-image batch up to the minimum and trims back, so this
            # is already a single frame; guard anyway.
            outputs.append(np.asarray(processed)[:1])
            logger.info("  image %d/%d done", index + 1, count)

        stacked = np.concatenate(outputs, axis=0)
        try:
            import torch
            return (torch.from_numpy(stacked),)
        except ImportError:
            return (stacked,)

    @staticmethod
    def _min_frames() -> int:
        return MIN_FRAMES
