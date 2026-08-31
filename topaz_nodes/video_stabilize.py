"""Topaz Video Stabilize — two-pass camera stabilization.

Stabilization in Topaz is genuinely two passes and cannot be collapsed into one:

  1. ``tvai_cpe`` analyses camera motion and writes a ``cpe.json``
  2. ``tvai_stb`` reads that file and warps the frames

Both passes see the same input, so the engine feeds the raw payload twice from memory.
"""

from __future__ import annotations

from pathlib import Path

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


def _dof_value(rotation: bool, pan_x: bool, pan_y: bool, zoom: bool) -> int:
    """Topaz encodes the stabilized axes as four digits, e.g. 1111 = all of them."""
    digits = "".join("1" if flag else "0"
                     for flag in (rotation, pan_x, pan_y, zoom))
    return int(digits)


class TopazVideoStabilize:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "model": (model_choices(models.STABILIZE), {
                    "default": default_model(models.STABILIZE, "ref-2"),
                }),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 480.0,
                                  "step": 0.001}),
                "mode": (["full_frame", "auto_crop"], {
                    "default": "auto_crop",
                    "tooltip": "auto_crop: crop into the frame to hide the edges "
                               "stabilization exposes — keeps the output size. "
                               "full_frame: synthesise the exposed edges instead. "
                               "Slower and more memory-hungry.",
                }),
                "smoothness": ("FLOAT", {
                    "default": 6.0, "min": 0.0, "max": 16.0, "step": 0.5,
                    "tooltip": "How much the camera path is smoothed.",
                }),
            },
            "optional": {
                "stabilize_rotation": ("BOOLEAN", {"default": True}),
                "stabilize_pan_horizontal": ("BOOLEAN", {"default": True}),
                "stabilize_pan_vertical": ("BOOLEAN", {"default": True}),
                "stabilize_zoom": ("BOOLEAN", {"default": True}),
                "rolling_shutter_correction": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Correct the skew rolling-shutter sensors produce on fast "
                               "pans.",
                }),
                "reduce_jitter": ("INT", {"default": 0, "min": 0, "max": 5}),
                "canvas_scale": ("FLOAT", {
                    "default": 2.0, "min": 1.0, "max": 8.0, "step": 0.5,
                    "tooltip": "Working canvas size relative to the input, used by "
                               "full_frame mode.",
                }),
                "engine": ("TOPAZ_ENGINE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "stabilize"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Stabilize camera motion with Topaz Video. Runs camera-pose "
                   "estimation first, then stabilization.")

    def stabilize(self, images, model, fps, mode, smoothness,
                  stabilize_rotation=True, stabilize_pan_horizontal=True,
                  stabilize_pan_vertical=True, stabilize_zoom=True,
                  rolling_shutter_correction=False, reduce_jitter=0,
                  canvas_scale=2.0, engine=None):
        settings: EngineSettings = settings_from_input(engine)
        topaz = TopazEngine(settings)
        topaz.check_license()

        chosen = topaz.resolve_model(model, models.STABILIZE)

        # Camera pose estimation needs its own model; pick the newest installed one.
        cpe_candidates = models.models_for(topaz.model_dir, models.CAMERA_POSE)
        cpe_ready = [m for m in cpe_candidates if m.short_code.startswith("cpe")]
        if not cpe_ready:
            raise RuntimeError(
                "Stabilization needs a camera-pose-estimation model (cpe-*), and none "
                "was found. Run a stabilization job once in the Topaz Video app so the "
                "model downloads."
            )
        cpe = topaz.resolve_model(cpe_ready[-1].label, models.CAMERA_POSE)

        in_height, in_width = int(images.shape[1]), int(images.shape[2])
        base = topaz.base_options()

        def specs(work_dir: Path):
            cpe_file = (work_dir / "cpe.json").as_posix()
            analysis = FilterSpec(models.CAMERA_POSE, {
                "model": cpe.short_code,
                "filename": cpe_file,
                "download": base.get("download", 0),
            })
            stabilize = FilterSpec(models.STABILIZE, {
                **base,
                "model": chosen.short_code,
                "filename": cpe_file,
                "full": 1 if mode == "full_frame" else 0,
                "smoothness": float(smoothness),
                "dof": _dof_value(stabilize_rotation, stabilize_pan_horizontal,
                                  stabilize_pan_vertical, stabilize_zoom),
                "roll": 1 if rolling_shutter_correction else 0,
                "reduce": int(reduce_jitter),
                "csx": float(canvas_scale),
                "csy": float(canvas_scale),
            })
            return analysis, stabilize

        logger.info("stabilize %dx%d with %s (%s), cpe model %s",
                    in_width, in_height, chosen.label, mode, cpe.short_code)

        result = topaz.process(
            images, specs, fps=float(fps),
            out_width=in_width, out_height=in_height, model=chosen,
            progress=make_progress(int(images.shape[0])),
            interrupt_check=interrupt_check,
        )
        return (result,)
