"""ComfyUI node registrations for Topaz Studio."""

from .diagnostics import TopazDiagnostics
from .estimate_params import TopazParameterEstimate
from .restore_nodes import TopazDeinterlace, TopazMotionDeblur
from .image_upscale import TopazImageUpscale
from .upscale_chain import TopazUpscaleStage
from .settings_nodes import (
    TopazEngineSettings,
    TopazHyperionParams,
    TopazSAM2Mask,
    TopazUpscaleParams,
)
from .video_interpolate import TopazVideoInterpolate
from .video_stabilize import TopazVideoStabilize
from .video_upscale import TopazVideoUpscale

NODE_CLASS_MAPPINGS = {
    "TopazStudioUpscale": TopazVideoUpscale,
    "TopazStudioInterpolate": TopazVideoInterpolate,
    "TopazStudioStabilize": TopazVideoStabilize,
    "TopazStudioDeinterlace": TopazDeinterlace,
    "TopazStudioMotionDeblur": TopazMotionDeblur,
    "TopazStudioParameterEstimate": TopazParameterEstimate,
    "TopazStudioImageUpscale": TopazImageUpscale,
    "TopazStudioEngineSettings": TopazEngineSettings,
    "TopazStudioUpscaleParams": TopazUpscaleParams,
    "TopazStudioUpscaleStage": TopazUpscaleStage,
    "TopazStudioHyperionParams": TopazHyperionParams,
    "TopazStudioSAM2Mask": TopazSAM2Mask,
    "TopazStudioDiagnostics": TopazDiagnostics,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "TopazStudioUpscale": "Topaz Video Upscale",
    "TopazStudioInterpolate": "Topaz Frame Interpolation",
    "TopazStudioStabilize": "Topaz Video Stabilize",
    "TopazStudioDeinterlace": "Topaz Deinterlace",
    "TopazStudioMotionDeblur": "Topaz Motion Deblur",
    "TopazStudioParameterEstimate": "Topaz Parameter Estimate",
    "TopazStudioImageUpscale": "Topaz Image Upscale",
    "TopazStudioEngineSettings": "Topaz Engine Settings",
    "TopazStudioUpscaleParams": "Topaz Upscale Params",
    "TopazStudioUpscaleStage": "Topaz Upscale Stage",
    "TopazStudioHyperionParams": "Topaz Hyperion HDR Params",
    "TopazStudioSAM2Mask": "Topaz SAM2 Mask",
    "TopazStudioDiagnostics": "Topaz Diagnostics",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
