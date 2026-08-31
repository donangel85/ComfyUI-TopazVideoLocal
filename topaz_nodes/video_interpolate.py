"""Topaz Video Frame Interpolation (tvai_fi)."""

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

logger = get_logger()


class TopazVideoInterpolate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "model": (model_choices(models.INTERPOLATE), {
                    "default": default_model(models.INTERPOLATE, "apo-8"),
                }),
                "input_fps": ("FLOAT", {
                    "default": 24.0, "min": 1.0, "max": 480.0, "step": 0.001,
                    "tooltip": "Frame rate the incoming batch represents.",
                }),
                "mode": (["target_fps", "slowmo"], {
                    "default": "target_fps",
                    "tooltip": "target_fps: interpolate up to a new frame rate. "
                               "slowmo: keep the frame rate and stretch time.",
                }),
                "target_fps": ("FLOAT", {
                    "default": 48.0, "min": 1.0, "max": 480.0, "step": 0.001,
                }),
                "slowmo_factor": ("FLOAT", {
                    "default": 2.0, "min": 0.1, "max": 16.0, "step": 0.1,
                }),
            },
            "optional": {
                "replace_duplicate_threshold": ("FLOAT", {
                    "default": 0.01, "min": -0.01, "max": 0.2, "step": 0.005,
                    "tooltip": "Detect and replace duplicate frames. "
                               "0 or below disables it.",
                }),
                "engine": ("TOPAZ_ENGINE",),
            },
        }

    RETURN_TYPES = ("IMAGE", "FLOAT")
    RETURN_NAMES = ("images", "output_fps")
    FUNCTION = "interpolate"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Interpolate frames with Topaz Video (Apollo, Aion, Chronos). "
                   "The returned frame count differs from the input by design.")

    def interpolate(self, images, model, input_fps, mode, target_fps, slowmo_factor,
                    replace_duplicate_threshold=0.01, engine=None):
        settings: EngineSettings = settings_from_input(engine)
        topaz = TopazEngine(settings)
        topaz.check_license()

        chosen = topaz.resolve_model(model, models.INTERPOLATE)

        in_height, in_width = int(images.shape[1]), int(images.shape[2])
        options = dict(topaz.base_options())
        options["model"] = chosen.short_code

        if mode == "slowmo":
            options["slowmo"] = float(slowmo_factor)
            out_fps = float(input_fps)
        else:
            options["fps"] = f"{float(target_fps):g}"
            out_fps = float(target_fps)

        if replace_duplicate_threshold is not None:
            options["rdt"] = float(replace_duplicate_threshold)

        logger.info("interpolate %s: %.3f fps -> %.3f fps (%s)",
                    chosen.label, float(input_fps), out_fps, mode)

        # Geometry is unchanged by interpolation; only the frame count moves.
        result = topaz.process(
            images,
            FilterSpec(models.INTERPOLATE, options),
            fps=float(input_fps),
            out_width=in_width,
            out_height=in_height,
            model=chosen,
            progress=make_progress(int(images.shape[0])),
            interrupt_check=interrupt_check,
        )
        logger.info("interpolate produced %d frames from %d",
                    len(result), int(images.shape[0]))
        return (result, out_fps)
