"""Optional settings nodes.

Keeping these separate keeps the main nodes readable: a simple upscale needs three
widgets, while everything Topaz can do is still reachable by attaching a settings node.
"""

from __future__ import annotations

from ..topaz_video import config, parameters, profiles
from ..topaz_video.engine import EngineSettings
from ..topaz_video.logging_util import get_logger

from .common import CATEGORY, model_dir_or_none

logger = get_logger()


class TopazEngineSettings:
    """Execution options shared by every Topaz node."""

    @classmethod
    def INPUT_TYPES(cls):
        defaults = config.get("defaults", {}) or {}
        return {
            "required": {
                "device": ("STRING", {
                    "default": str(defaults.get("device", "-2")),
                    "tooltip": "GPU index. -2 = auto, -1 = CPU, 0 = first GPU. "
                               "Auto is strongly recommended: on mixed NVIDIA/AMD "
                               "systems an explicit index of 0 has been observed to "
                               "fail with 'Failed to configure output pad'.",
                }),
                "vram": ("FLOAT", {
                    "default": float(defaults.get("vram", 1.0)),
                    "min": 0.1, "max": 1.0, "step": 0.05,
                    "tooltip": "Fraction of video memory Topaz may use.",
                }),
                "instances": ("INT", {
                    "default": int(defaults.get("instances", 0)),
                    "min": 0, "max": 3,
                    "tooltip": "Extra parallel model instances. 0 is usually best.",
                }),
                "allow_model_download": ("BOOLEAN", {
                    "default": bool(defaults.get("allow_model_download", False)),
                    "tooltip": "Let Topaz fetch missing model weights from its servers. "
                               "Off by default so processing stays fully offline; your "
                               "images and video are never uploaded either way.",
                }),
                "transport": (["pipe", "file"], {
                    "default": str(defaults.get("transport", "pipe")),
                    "tooltip": "pipe: raw frames straight into Topaz, no decoder "
                               "involved (recommended). file: lossless intermediate "
                               "file, slower but easier to inspect when debugging.",
                }),
                "license_check": (["cached", "force", "skip"], {
                    "default": "cached",
                    "tooltip": "cached: verify once, then remember across restarts. "
                               "force: re-verify now. skip: don't check; Topaz will "
                               "report a licence problem itself if there is one.",
                }),
                "keep_temp_on_error": ("BOOLEAN", {
                    "default": bool(defaults.get("keep_temp_on_error", False)),
                    "tooltip": "Keep temporary frame data when a run fails.",
                }),
                "verbose": ("BOOLEAN", {
                    "default": bool(defaults.get("verbose", False)),
                    "tooltip": "Log the full FFmpeg command line for every call.",
                }),
            },
            "optional": {
                "install_path": ("STRING", {
                    "default": "",
                    "tooltip": "Override the Topaz Video folder. Leave empty to detect "
                               "it automatically.",
                }),
                "timeout_seconds": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 86400.0, "step": 30.0,
                    "tooltip": "Abort a run after this long. 0 = no limit.",
                }),
                "save_as_defaults": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Persist these values to config.json so they survive "
                               "ComfyUI restarts.",
                }),
            },
        }

    RETURN_TYPES = ("TOPAZ_ENGINE",)
    RETURN_NAMES = ("engine",)
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, device, vram, instances, allow_model_download, transport,
              license_check, keep_temp_on_error, verbose,
              install_path="", timeout_seconds=0.0, save_as_defaults=False):
        settings = EngineSettings(
            device=str(device).strip() or "-2",
            instances=int(instances),
            vram=float(vram),
            allow_model_download=bool(allow_model_download),
            transport=str(transport),
            keep_temp_on_error=bool(keep_temp_on_error),
            verbose=bool(verbose),
            license_check=str(license_check),
            install_path=str(install_path).strip(),
            timeout=float(timeout_seconds),
        )

        if save_as_defaults:
            config.set_("defaults", {
                "device": settings.device,
                "vram": settings.vram,
                "instances": settings.instances,
                "allow_model_download": settings.allow_model_download,
                "transport": settings.transport,
                "keep_temp_on_error": settings.keep_temp_on_error,
                "verbose": settings.verbose,
            }, persist=False)
            if settings.install_path:
                config.set_("video_install_path", settings.install_path, persist=False)
            config.save()

        return (settings,)


class TopazUpscaleParams:
    """Fine-tuning parameters for tvai_up.

    Values are relative to what the model detects in the input, which is why they run
    from -1 to 1 with 0 meaning "leave it to the model".
    """

    @classmethod
    def INPUT_TYPES(cls):
        # Limits come from topaz_video.parameters so they cannot drift from what
        # profiles and the preset routes clamp to. A widget whose range disagrees with
        # them refuses a value the preset legitimately holds, and the whole prompt
        # fails: "Value 0.3 bigger than max of 0.1: prenoise".
        def rel(tooltip, key="preblur"):
            return parameters.widget_spec(key, tooltip)

        return {
            "required": {
                "profile": (profiles.labels(model_dir_or_none()), {
                    "default": profiles.MANUAL,
                    "tooltip": "manual: use the sliders below. Picking anything else "
                               "copies that preset's values into the sliders, where you "
                               "can adjust them. Entries prefixed 'Topaz:' come from "
                               "Topaz Video's own presets, 'My:' are your own saved "
                               "ones, and the rest ship with this package.",
                }),
                "profile_strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05,
                    "tooltip": "Scales a profile's intensity. 0.5 is half as "
                               "aggressive, 0 disables its tuning. No effect in manual "
                               "mode. Change this before picking the profile, or press "
                               "'Reload preset into sliders' afterwards.",
                }),
                "preblur": rel("Negative for aliasing/moire in the source, positive for "
                               "lens blur."),
                "noise": rel("Remove ISO noise. Too high also removes fine detail."),
                "details": rel("Recover texture lost to in-camera noise suppression."),
                "halo": rel("Reduce ringing around strong edges from oversharpening."),
                "blur": rel("Additional sharpening for soft sources."),
                "compression": rel("Reduce blockiness and mosquito noise from codecs."),
            },
            "optional": {
                "prenoise": parameters.widget_spec(
                    "prenoise", "Noise added before processing.", step=0.005),
                "grain": parameters.widget_spec(
                    "grain", "Film grain added to the output."),
                # The filter calls this gsize; the widget spells it out.
                "grain_size": parameters.widget_spec(
                    "gsize", "Size of the added grain.", step=0.1),
                "grain_type": (["default", "silver_rich", "gaussian", "grey"],
                               {"default": "default"}),
                "blend": parameters.widget_spec(
                    "blend", "Blend the original back into the result."),
                "color_correction": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Extra colour correction where the model needs it.",
                }),
                "auto_estimate_frames": ("INT", {
                    "default": 0, "min": 0, "max": 100,
                    "tooltip": "Analyse this many frames to estimate the parameters "
                               "above automatically. 0 disables estimation and uses the "
                               "values as given.",
                }),
                # Last on purpose. ComfyUI maps a saved workflow's widgets_values onto
                # this list by position, so a widget inserted anywhere but the end
                # shifts every later value in every workflow already saved. This one
                # belongs beside `profile` by meaning and cannot go there.
                "edit_preset_values": ("BOOLEAN", {
                    "default": False,
                    "label_on": "sliders (edited)",
                    "label_off": "preset as-is",
                    "tooltip": "Which values actually run. Off: the profile at the top "
                               "is applied as authored and the sliders are ignored. On: "
                               "the sliders are used, so your adjustments count.\n\n"
                               "Picking a profile in the browser fills the sliders and "
                               "turns this on for you. Turn it off to go back to the "
                               "untouched preset — your slider values are kept.",
                }),
            },
        }

    RETURN_TYPES = ("TOPAZ_UPSCALE_PARAMS",)
    RETURN_NAMES = ("params",)
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, profile, profile_strength, preblur, noise,
              details, halo, blur, compression, prenoise=0.0, grain=0.0,
              grain_size=0.0, grain_type="default", blend=0.0, color_correction=True,
              auto_estimate_frames=0, edit_preset_values=False):
        chosen = profiles.resolve(profile, model_dir_or_none())
        # edit_preset_values is what the browser turns on after copying a preset into
        # the sliders. Without it the profile wins and the sliders are ignored, which is
        # what an API caller with no frontend gets — and what this node always did.
        if chosen is not None and edit_preset_values:
            logger.info("profile '%s' was copied into the sliders; using the slider "
                        "values", profile)
            chosen = None
        if chosen is not None:
            options = chosen.resolve(profile_strength)
            options["kcolor"] = 1 if color_correction else 0
            if prenoise:
                options["prenoise"] = float(prenoise)
            if grain:
                options["grain"] = float(grain)
            if grain_size:
                options["gsize"] = float(grain_size)
            if blend:
                options["blend"] = float(blend)
            readable = ", ".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}"
                                 for k, v in sorted(options.items()))
            logger.info("profile '%s' at strength %g -> %s", profile,
                        profile_strength, readable)
            if chosen.suggested_model:
                logger.info("  this profile was authored for model '%s'",
                            chosen.suggested_model)
            extra = {}
            if grain and grain_type != "default":
                extra["grain_type"] = grain_type
            if extra:
                options["_extra_parameters"] = extra
            return (options,)

        options = {
            "preblur": float(preblur),
            "noise": float(noise),
            "details": float(details),
            "halo": float(halo),
            "blur": float(blur),
            "compression": float(compression),
            "estimate": int(auto_estimate_frames),
            "kcolor": 1 if color_correction else 0,
        }
        if prenoise:
            options["prenoise"] = float(prenoise)
        if grain:
            options["grain"] = float(grain)
        if grain_size:
            options["gsize"] = float(grain_size)
        if blend:
            options["blend"] = float(blend)

        extra = {}
        if grain and grain_type != "default":
            extra["grain_type"] = grain_type
        if extra:
            options["_extra_parameters"] = extra
        return (options,)


class TopazHyperionParams:
    """SDR to HDR parameters for the Hyperion model (hyp-1)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "sdr_ip": ("FLOAT", {"default": 0.65, "min": 0.45, "max": 0.85,
                                     "step": 0.01,
                                     "tooltip": "SDR highlight threshold."}),
                "hdr_ip_adjust": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0,
                                            "step": 0.01,
                                            "tooltip": "Exposure adjustment amount."}),
                "saturate": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0,
                                       "step": 0.01,
                                       "tooltip": "Saturation adjustment amount."}),
            }
        }

    RETURN_TYPES = ("TOPAZ_UPSCALE_PARAMS",)
    RETURN_NAMES = ("params",)
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, sdr_ip, hdr_ip_adjust, saturate):
        return ({
            "_extra_parameters": {
                "sdr_ip": f"{float(sdr_ip):g}",
                "hdr_ip_adjust": f"{float(hdr_ip_adjust):g}",
                "saturate": f"{float(saturate):g}",
            }
        },)


# There was a TopazSAM2Mask node here, feeding a Segment-Anything-2 click expression
# into `tvai_up`'s `parameters` dictionary. It was removed because it could not work,
# and this is the second time the same trap has caught this package.
#
# `ffmpeg -h filter=tvai_up` documents a parameter group headed "Segment-Anything-2
# (vsam) parameters", with a `clicks` key and a grammar for it. That heading names a
# *model*, and this Topaz build does not have one:
#
#   model=vsam            ->  "Invalid value vsam for model, model should be in the
#                              following list:" followed by all 51 accepted models.
#                             Byte for byte the same rejection as a name invented on
#                             the spot, and a different error from the -22 that a
#                             model with no local weights gives.
#   clicks on prob-4      ->  exits 0, output unchanged.
#   nonsense=42 on prob-4 ->  exits 0, output unchanged. The control.
#
# `parameters` is an AV_OPT_TYPE_DICT, so `clicks` on a model that has no use for it is
# swallowed in silence exactly like a key that does not exist — the same thing that made
# the `field_order` switch look like it worked (see TopazDeinterlace). A node that
# quietly does nothing is worse than no node: someone wires it up, sees no mask, and
# looks everywhere except at the control itself.
#
# Removed while the package is unpublished, as `field_order` was. `research/probe_sam2.py`
# holds the measurements and fails if a future Topaz release starts accepting `vsam`,
# at which point the node can come back.
