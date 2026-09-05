"""ComfyUI node registrations for Topaz Video Local."""

from .diagnostics import TopazDiagnostics
from .estimate_params import TopazParameterEstimate
from .resolution import TopazResolution
from .restore_nodes import TopazDeinterlace, TopazMotionDeblur
from .image_upscale import TopazImageUpscale
from .upscale_chain import TopazUpscaleStage
from .settings_nodes import (
    TopazEngineSettings,
    TopazHyperionParams,
    TopazUpscaleParams,
)
from .video_interpolate import TopazVideoInterpolate
from .video_stabilize import TopazVideoStabilize
from .video_upscale import TopazVideoUpscale

NODE_CLASS_MAPPINGS = {
    "TopazVideoLocalUpscale": TopazVideoUpscale,
    "TopazVideoLocalInterpolate": TopazVideoInterpolate,
    "TopazVideoLocalStabilize": TopazVideoStabilize,
    "TopazVideoLocalDeinterlace": TopazDeinterlace,
    "TopazVideoLocalMotionDeblur": TopazMotionDeblur,
    "TopazVideoLocalParameterEstimate": TopazParameterEstimate,
    "TopazVideoLocalImageUpscale": TopazImageUpscale,
    "TopazVideoLocalResolution": TopazResolution,
    "TopazVideoLocalEngineSettings": TopazEngineSettings,
    "TopazVideoLocalUpscaleParams": TopazUpscaleParams,
    "TopazVideoLocalUpscaleStage": TopazUpscaleStage,
    "TopazVideoLocalHyperionParams": TopazHyperionParams,
    "TopazVideoLocalDiagnostics": TopazDiagnostics,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "TopazVideoLocalUpscale": "Topaz Video Upscale",
    "TopazVideoLocalInterpolate": "Topaz Frame Interpolation",
    "TopazVideoLocalStabilize": "Topaz Video Stabilize",
    "TopazVideoLocalDeinterlace": "Topaz Deinterlace",
    "TopazVideoLocalMotionDeblur": "Topaz Motion Deblur",
    "TopazVideoLocalParameterEstimate": "Topaz Parameter Estimate",
    "TopazVideoLocalImageUpscale": "Topaz Image Upscale",
    "TopazVideoLocalResolution": "Topaz Resolution",
    "TopazVideoLocalEngineSettings": "Topaz Engine Settings",
    "TopazVideoLocalUpscaleParams": "Topaz Upscale Params",
    "TopazVideoLocalUpscaleStage": "Topaz Upscale Stage",
    "TopazVideoLocalHyperionParams": "Topaz Hyperion HDR Params",
    "TopazVideoLocalDiagnostics": "Topaz Diagnostics",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
