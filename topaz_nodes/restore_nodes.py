"""Deinterlace (Dione) and Motion Deblur (Themis).

Both run through ``tvai_up`` and are therefore reachable from the general Upscale node
already — but only if you happen to know which cryptic short code does what, and which
scale factors it tolerates. As dedicated nodes the purpose is visible and the constraints
are enforced rather than discovered through a failed render.

Two model-specific facts, read from Topaz's own JSON metadata:

* Themis (``thm-2``) supports **scale 1 only**. ``thm-1`` carries ``enabled: 0`` and is
  correctly absent from the catalog.
* Dione models split by ``interlacedFrames``: ``1`` for genuinely interlaced sources
  (Dione DV/TV/Dehalo), ``0`` for the progressive-input variants (Dione Robust). The
  field order is a model *parameter* named ``interlacing`` — an int, 0 = top field
  first, 1 = bottom field first — not a filter option of its own.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..topaz_studio import models
from ..topaz_studio.command import render_parameters_dict
from ..topaz_studio.engine import EngineSettings, FilterSpec, TopazEngine
from ..topaz_studio.logging_util import get_logger

from .common import (
    CATEGORY,
    interrupt_check,
    make_progress,
    model_dir_or_none,
    settings_from_input,
)
from .video_upscale import _RawSpec

logger = get_logger()

_DEINTERLACE_FAMILIES = ("ddv", "dtv", "dtd", "dtvs", "dtds")
_DEBLUR_FAMILIES = ("thm",)

_NO_MODELS = ["<no matching model found>"]


def _family(short_code: str) -> str:
    return short_code.split("-")[0].lower()


def _filtered_choices(families) -> list:
    entries = [m for m in models.models_for(model_dir_or_none(), models.UPSCALE)
               if _family(m.short_code) in families]
    return [m.label for m in entries] or list(_NO_MODELS)


def _default_of(families, preferred: str) -> str:
    choices = _filtered_choices(families)
    for label in choices:
        if f"({preferred})" in label:
            return label
    return choices[0]


def _is_interlaced_model(model_dir, short_code: str) -> bool:
    """Whether the model expects genuinely interlaced input.

    Read from the model's own JSON rather than guessed from the name, so a new Dione
    variant is classified correctly without a code change.
    """
    if not model_dir:
        return False
    path = Path(model_dir) / f"{short_code}.json"
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("interlacedFrames"))
    except (OSError, ValueError):
        return False


class TopazDeinterlace:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "model": (_filtered_choices(_DEINTERLACE_FAMILIES), {
                    "default": _default_of(_DEINTERLACE_FAMILIES, "ddv-3"),
                    "tooltip": "Dione DV/TV/Dehalo expect interlaced input; "
                               "Dione Robust variants take progressive input.",
                }),
                "field_order": (["top_first", "bottom_first"], {
                    "default": "top_first",
                    "tooltip": "Which field comes first in the source. Getting this "
                               "wrong makes motion stutter. Ignored by models that do "
                               "not take interlaced input.",
                }),
                "scale_factor": ([1, 2, 4], {
                    "default": 1,
                    "tooltip": "Deinterlacing alone is scale 1. Higher values "
                               "deinterlace and upscale in the same pass.",
                }),
                "fps": ("FLOAT", {
                    "default": 25.0, "min": 1.0, "max": 480.0, "step": 0.001,
                    "tooltip": "Interlaced material is usually 25 or 29.97.",
                }),
            },
            "optional": {
                "params": ("TOPAZ_UPSCALE_PARAMS",),
                "engine": ("TOPAZ_ENGINE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "deinterlace"
    CATEGORY = CATEGORY
    DESCRIPTION = "Deinterlace with Topaz's Dione models, optionally upscaling as well."

    def deinterlace(self, images, model, field_order, scale_factor, fps,
                    params=None, engine=None):
        settings: EngineSettings = settings_from_input(engine)
        topaz = TopazEngine(settings)
        topaz.check_license()
        chosen = topaz.resolve_model(model, models.UPSCALE)

        scale = int(scale_factor)
        if not chosen.supports_scale(scale):
            supported = ", ".join(str(s) for s in chosen.scales) or "unknown"
            raise ValueError(
                f"{chosen.display_name} ({chosen.short_code}) does not support scale "
                f"{scale}. Supported: {supported}."
            )

        in_height, in_width = int(images.shape[1]), int(images.shape[2])
        options = dict(topaz.base_options())
        options["model"] = chosen.short_code
        options["scale"] = scale

        extra = {}
        if params:
            tuning = dict(params)
            extra = dict(tuning.pop("_extra_parameters", {}) or {})
            options.update(tuning)
        else:
            options.setdefault("estimate", 0)

        interlaced = _is_interlaced_model(topaz.model_dir, chosen.short_code)
        if interlaced:
            extra["interlacing"] = 0 if field_order == "top_first" else 1
        else:
            logger.info("%s takes progressive input; field order not applied",
                        chosen.label)
        if extra:
            options["parameters"] = render_parameters_dict(extra)

        out_width, out_height = in_width * scale, in_height * scale
        logger.info("deinterlace %dx%d -> %dx%d using %s (%s%s)",
                    in_width, in_height, out_width, out_height, chosen.label,
                    "interlaced input" if interlaced else "progressive input",
                    f", {field_order}" if interlaced else "")

        result = topaz.process(
            images, _RawSpec(FilterSpec(models.UPSCALE, options).render()),
            fps=float(fps), out_width=out_width, out_height=out_height,
            model=chosen, progress=make_progress(int(images.shape[0])),
            interrupt_check=interrupt_check,
        )
        return (result,)


class TopazMotionDeblur:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "model": (_filtered_choices(_DEBLUR_FAMILIES), {
                    "default": _default_of(_DEBLUR_FAMILIES, "thm-2"),
                }),
                "fps": ("FLOAT", {
                    "default": 24.0, "min": 1.0, "max": 480.0, "step": 0.001,
                }),
            },
            "optional": {
                "params": ("TOPAZ_UPSCALE_PARAMS",),
                "engine": ("TOPAZ_ENGINE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "deblur"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Reduce motion blur with Topaz's Themis model. Resolution is "
                   "unchanged — Themis supports scale 1 only; chain an Upscale node "
                   "afterwards if you also want more resolution.")

    def deblur(self, images, model, fps, params=None, engine=None):
        settings: EngineSettings = settings_from_input(engine)
        topaz = TopazEngine(settings)
        topaz.check_license()
        chosen = topaz.resolve_model(model, models.UPSCALE)

        in_height, in_width = int(images.shape[1]), int(images.shape[2])
        options = dict(topaz.base_options())
        options["model"] = chosen.short_code
        # Fixed at 1: Themis declares only scale 1, and offering a widget that can only
        # hold one value is worse than not offering it.
        options["scale"] = 1

        extra = {}
        if params:
            tuning = dict(params)
            extra = tuning.pop("_extra_parameters", {}) or {}
            options.update(tuning)
        else:
            options.setdefault("estimate", 0)
        if extra:
            options["parameters"] = render_parameters_dict(extra)

        logger.info("motion deblur %dx%d using %s", in_width, in_height, chosen.label)

        result = topaz.process(
            images, _RawSpec(FilterSpec(models.UPSCALE, options).render()),
            fps=float(fps), out_width=in_width, out_height=in_height,
            model=chosen, progress=make_progress(int(images.shape[0])),
            interrupt_check=interrupt_check,
        )
        return (result,)
