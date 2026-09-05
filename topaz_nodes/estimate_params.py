"""Topaz Parameter Estimate — let Topaz analyse the footage and choose the tuning.

This is the ``tvai_pe`` filter, which the package did not use before. It looks at the
frames and reports the parameters it would pick, which we hand on as
``TOPAZ_UPSCALE_PARAMS`` for the Upscale node.

The difference to the Upscale node's own ``estimate`` option: there, Topaz estimates
internally and you never see the numbers. Here you get them out, can inspect them, and
can reuse the same set across several passes instead of re-analysing each time.
"""

from __future__ import annotations

from ..topaz_video import estimation, models
from ..topaz_video.engine import EngineSettings, FilterSpec, TopazEngine
from ..topaz_video.logging_util import get_logger

from .common import (
    CATEGORY,
    default_model,
    interrupt_check,
    model_choices,
    settings_from_input,
)

logger = get_logger()


class TopazParameterEstimate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "model": (model_choices(models.ESTIMATE), {
                    "default": default_model(models.ESTIMATE, "prap-3"),
                    "tooltip": "prap-* estimates the full parameter set; nap-* "
                               "concentrates on noise and artefacts.",
                }),
                "aggregation": (["median", "mean"], {
                    "default": "median",
                    "tooltip": "How per-frame estimates are combined. Median ignores "
                               "outliers such as a cut or a single black frame; mean "
                               "follows them.",
                }),
                "fps": ("FLOAT", {
                    "default": 24.0, "min": 1.0, "max": 480.0, "step": 0.001,
                }),
            },
            "optional": {
                "max_frames": ("INT", {
                    "default": 0, "min": 0, "max": 4096,
                    "tooltip": "Analyse only the first N frames. 0 uses the whole batch. "
                               "Estimation is fast, but on very long batches a sample is "
                               "usually enough.",
                }),
                "engine": ("TOPAZ_ENGINE",),
            },
        }

    RETURN_TYPES = ("TOPAZ_UPSCALE_PARAMS", "STRING")
    RETURN_NAMES = ("params", "report")
    FUNCTION = "estimate"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Analyse footage with Topaz's parameter-estimation model and output "
                   "the tuning it suggests. Feed the result into Topaz Video Upscale.")

    def estimate(self, images, model, aggregation, fps, max_frames=0, engine=None):
        settings: EngineSettings = settings_from_input(engine)
        topaz = TopazEngine(settings)
        topaz.check_license()
        chosen = topaz.resolve_model(model, models.ESTIMATE)

        sample = images
        if max_frames and len(images) > max_frames:
            sample = images[:max_frames]
            logger.info("estimating from the first %d of %d frames",
                        max_frames, len(images))

        options = {
            "model": chosen.short_code,
            "download": 1 if settings.allow_model_download else 0,
        }
        stderr = topaz.analyze(
            sample, FilterSpec(models.ESTIMATE, options),
            fps=float(fps), model=chosen, interrupt_check=interrupt_check,
        )

        frames = estimation.parse_frames(stderr)
        params = estimation.aggregate(frames, aggregation)

        if not params:
            # Say so plainly rather than silently handing on an empty parameter set that
            # would look like "no tuning wanted".
            message = (f"{chosen.label} produced no parameter estimates. "
                       f"The model may not support estimation for this input.")
            logger.warning(message)
            return ({}, message)

        spread = estimation.spread(frames)
        lines = [
            f"Topaz parameter estimate — {chosen.label}",
            f"{len(frames)} frame(s) analysed, aggregated by {aggregation}",
            "",
        ]
        for name in estimation.PARAMETER_ORDER:
            low, high = spread.get(name, (0, 0))
            lines.append(f"  {name:<12} {params[name]:>8.4f}"
                         f"   (range {low:+.4f} … {high:+.4f})")
        report = "\n".join(lines)

        logger.info("estimated parameters from %d frames: %s",
                    len(frames), estimation.describe(params))

        # estimate=0 so the Upscale node uses these values rather than estimating again.
        result = dict(params)
        result["estimate"] = 0
        return (result, report)
