"""Multi-pass upscaling.

Topaz Video lets you stack several enhancement passes, and so does the FFmpeg filter:
chaining ``tvai_up=...,tvai_up=...`` in one call runs both models over the frames without
ever leaving the process. That is verifiably supported — and much better than wiring two
Upscale nodes in series, which would mean two ffmpeg launches, two model loads and a
needless tensor round trip in between.

Chain stages by feeding one **Topaz Upscale Stage** into the next through
``previous_stage``, then connect the last one to the ``upscale_chain`` input of
**Topaz Video Upscale**.
"""

from __future__ import annotations

from ..topaz_video import models
from ..topaz_video.command import render_parameters_dict
from ..topaz_video.engine import FilterSpec
from ..topaz_video.logging_util import get_logger
from ..topaz_video.scaling import (
    FIT,
    FIT_MODES,
    describe_chain,
    factor_for_target,
    fit_filters,
)

from .common import CATEGORY, default_model, model_choices, model_dir_or_none

logger = get_logger()


class TopazUpscaleStage:
    """One pass in a multi-pass upscale."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (model_choices(models.UPSCALE), {
                    "default": default_model(models.UPSCALE, "prob-4"),
                }),
                "scale_factor": ([1, 2, 3, 4], {
                    "default": 2,
                    "tooltip": "Used when scale_mode is 'factor'. Scales multiply along "
                               "the chain: 2x then 2x is 4x overall. Not every model "
                               "supports every factor — pnat-1 only allows 2, hyp-1 "
                               "only 1.",
                }),
            },
            "optional": {
                # scale_mode reads better above scale_factor, but it cannot go there.
                # ComfyUI maps a saved workflow's widgets_values onto this list by
                # position, and this node shipped with exactly two widgets, so anything
                # new has to come after both of them.
                "scale_mode": (["factor", "target_size"], {
                    "default": "factor",
                    "tooltip": "factor: an exact integer multiple, the most predictable "
                               "option. target_size: upscale far enough to cover the "
                               "size below, then resample this stage's output to it "
                               "before the next stage sees it.",
                }),
                "target_width": ("INT", {
                    "default": 1920, "min": 16, "max": 16384, "step": 8,
                    "tooltip": "Used when scale_mode is 'target_size'. Connect a Topaz "
                               "Resolution node here to pick a named size.",
                }),
                "target_height": ("INT", {
                    "default": 1088, "min": 16, "max": 16384, "step": 8,
                    "tooltip": "Used when scale_mode is 'target_size'.",
                }),
                "fit_mode": (list(FIT_MODES), {
                    "default": FIT,
                    "tooltip": "How the frame is placed into the target size. fit pads "
                               "with black, fill crops the overflow, stretch changes "
                               "the aspect ratio.",
                }),
                "params": ("TOPAZ_UPSCALE_PARAMS", {
                    "tooltip": "Tuning for this stage only.",
                }),
                "previous_stage": ("TOPAZ_UPSCALE_CHAIN", {
                    "tooltip": "Chain another stage in front of this one. Stages run in "
                               "the order they are connected.",
                }),
            },
        }

    RETURN_TYPES = ("TOPAZ_UPSCALE_CHAIN",)
    RETURN_NAMES = ("chain",)
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = ("One pass of a multi-pass Topaz upscale. Chain several of these, then "
                   "connect the last to Topaz Video Upscale.")

    def build(self, model, scale_factor, scale_mode="factor", target_width=1920,
              target_height=1088, fit_mode=FIT, params=None, previous_stage=None):
        resolved = models.resolve(model_dir_or_none(), model, models.UPSCALE)
        short_code = resolved.short_code if resolved else str(model)
        scale = int(scale_factor)

        # Validate here rather than letting ffmpeg fail several seconds into a run.
        # Topaz's own message is "Invalid scale 1 for model pnat-1, allowed scales are: 2".
        # Only in factor mode: under target_size the factor is derived from the geometry
        # at render time, when the size the previous stages produced is finally known.
        if scale_mode == "factor" and resolved and not resolved.supports_scale(scale):
            supported = ", ".join(str(s) for s in resolved.scales) or "unknown"
            raise ValueError(
                f"{resolved.display_name} ({short_code}) does not support scale {scale}. "
                f"Supported: {supported}."
            )

        tuning = dict(params) if params else {}
        extra = tuning.pop("_extra_parameters", {}) or {}
        tuning.setdefault("estimate", 0)

        stage = {
            "model": short_code,
            "scale": scale,
            "options": tuning,
            "extra": extra,
        }
        if scale_mode == "target_size":
            stage["target"] = (int(target_width), int(target_height))
            stage["fit_mode"] = fit_mode

        chain = list(previous_stage or []) + [stage]
        logger.debug("upscale chain now has %d stage(s): %s", len(chain),
                     describe_chain(chain))
        return (chain,)


def build_chain_segments(topaz, upscale_chain, in_width: int, in_height: int):
    """Render the preceding stages of a chain.

    Returns ``(segments, width, height)``: the rendered filter strings and the geometry
    after those stages, which the caller needs to size its own final pass.

    Shared by the video and image upscale nodes so the validation and the scale
    bookkeeping cannot drift apart between them.
    """
    segments: list[str] = []
    width, height = int(in_width), int(in_height)

    for index, stage in enumerate(upscale_chain or [], start=1):
        stage_model = topaz.resolve_model(stage["model"], models.UPSCALE)
        target = stage.get("target")
        stage_fit = stage.get("fit_mode", FIT)

        if target:
            # Only now is the incoming size known, so this is the first point at which
            # the factor needed to cover the target can be worked out.
            stage_scale = factor_for_target(stage_model.scales, width, height,
                                            target[0], target[1], stage_fit)
        else:
            stage_scale = int(stage.get("scale", 1))

        if not stage_model.supports_scale(stage_scale):
            supported = ", ".join(str(s) for s in stage_model.scales) or "unknown"
            raise ValueError(
                f"Chain stage {index}: {stage_model.display_name} "
                f"({stage_model.short_code}) does not support scale {stage_scale}. "
                f"Supported: {supported}."
            )
        options = dict(topaz.base_options())
        options["model"] = stage_model.short_code
        options["scale"] = stage_scale
        options.update(stage.get("options") or {})
        if stage.get("extra"):
            options["parameters"] = render_parameters_dict(stage["extra"])
        segments.append(FilterSpec(models.UPSCALE, options).render())
        width *= stage_scale
        height *= stage_scale

        if target:
            # Resample before the next stage runs, so the following model sees the size
            # this stage was asked to produce rather than a whole-number multiple of it.
            segments.extend(fit_filters(stage_fit, target[0], target[1]))
            width, height = int(target[0]), int(target[1])

    return segments, width, height
