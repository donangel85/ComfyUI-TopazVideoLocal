"""Topaz Video Upscale — the primary node."""

from __future__ import annotations

from ..topaz_studio import models
from ..topaz_studio.engine import EngineSettings, FilterSpec, TopazEngine
from ..topaz_studio.logging_util import get_logger

from .common import (
    CATEGORY,
    default_model,
    interrupt_check,
    make_progress,
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

logger = get_logger()


render_extra_parameters = render_parameters_dict


class _RawSpec(FilterSpec):
    """Carries an already-rendered filter chain (filters plus any post-filters)."""

    def __init__(self, chain: str):
        super().__init__(name=chain, options={})
        self._chain = chain

    def render(self) -> str:
        return self._chain


class TopazVideoUpscale:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "model": (model_choices(models.UPSCALE), {
                    "default": default_model(models.UPSCALE, "prob-4"),
                    "tooltip": "Models marked [download required] have no weights on "
                               "this machine yet.",
                }),
                "scale_mode": (["factor", "target_size"], {
                    "default": "factor",
                    "tooltip": "factor: exact integer multiple, the most reliable "
                               "option. target_size: any resolution; Topaz upscales and "
                               "the result is fitted to the exact size you ask for.",
                }),
                "scale_factor": ([1, 2, 3, 4], {
                    "default": 2,
                    "tooltip": "Used when scale_mode is 'factor'.",
                }),
                "fps": ("FLOAT", {
                    "default": 24.0, "min": 1.0, "max": 480.0, "step": 0.001,
                    "tooltip": "Frame rate the batch represents. Affects Topaz's "
                               "temporal analysis, not the frame count.",
                }),
            },
            "optional": {
                "target_width": ("INT", {"default": 1920, "min": 16, "max": 16384,
                                         "step": 8}),
                "target_height": ("INT", {"default": 1088, "min": 16, "max": 16384,
                                          "step": 8}),
                "fit_mode": (list(FIT_MODES), {
                    "default": FIT,
                    "tooltip": "Only applies to target_size. fit: keep the aspect "
                               "ratio, pad the remainder black. fill: keep it and crop "
                               "the overflow. stretch: hit the exact size and let the "
                               "aspect ratio change.",
                }),
                "params": ("TOPAZ_UPSCALE_PARAMS",),
                "upscale_chain": ("TOPAZ_UPSCALE_CHAIN", {
                    "tooltip": "Extra passes from Topaz Upscale Stage nodes. They run "
                               "first, in order, and this node's own model runs last — "
                               "all inside a single ffmpeg call.",
                }),
                "engine": ("TOPAZ_ENGINE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "upscale"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Upscale an image batch with Topaz Video's AI models "
                   "(Proteus, Rhea, Iris, Gaia, Nyx, Themis, ...). "
                   "Requires a licensed local Topaz Video installation.")

    def upscale(self, images, model, scale_mode, scale_factor, fps,
                target_width=1920, target_height=1088, fit_mode=FIT, params=None,
                upscale_chain=None, engine=None):
        settings: EngineSettings = settings_from_input(engine)
        topaz = TopazEngine(settings)
        topaz.check_license()

        in_height, in_width = int(images.shape[1]), int(images.shape[2])

        # --- preceding stages, if any ----------------------------------------
        # Chained tvai_up filters run in one ffmpeg call, so the frames never leave
        # the process between passes.
        segments, width, height = build_chain_segments(
            topaz, upscale_chain, in_width, in_height)

        # --- this node's own stage, always last -------------------------------
        chosen = topaz.resolve_model(model, models.UPSCALE)
        options = dict(topaz.base_options())
        options["model"] = chosen.short_code

        post_filters: list[str] = []
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
            # tvai_up only scales by whole numbers. Its w/h options are merely a hint it
            # uses to *estimate* a scale, and for a 1.5x request it settles on 1 — no AI
            # upscaling at all. So pick the smallest supported factor covering what is
            # still missing after the chain, then resample to the exact size.
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
            options["parameters"] = render_extra_parameters(extra)

        segments.append(FilterSpec(models.UPSCALE, options).render())
        chain = ",".join(segments + post_filters)

        if upscale_chain:
            logger.info("upscale chain: %s then %s (%dx%d before this node)",
                        describe_chain(upscale_chain), chosen.label, width, height)
        logger.info("upscale %dx%d -> %dx%d using %s (%d Topaz pass(es))",
                    in_width, in_height, out_width, out_height, chosen.label,
                    len(segments))

        result = topaz.process(
            images,
            _RawSpec(chain),
            fps=float(fps),
            out_width=out_width,
            out_height=out_height,
            model=chosen,
            progress=make_progress(int(images.shape[0])),
            interrupt_check=interrupt_check,
        )
        return (result,)
