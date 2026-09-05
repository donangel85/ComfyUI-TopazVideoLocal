"""Shared helpers for the node layer.

The nodes stay thin: gather widget values, call the backend, turn a failure into a
message a user can act on. All Topaz knowledge lives in ``topaz_video``.
"""

from __future__ import annotations

from ..topaz_video import TopazError
from ..topaz_video import config, models
from ..topaz_video.discovery import find_install
from ..topaz_video.engine import EngineSettings
from ..topaz_video.logging_util import get_logger

logger = get_logger()

CATEGORY = "Topaz Video Local"

# Shown when Topaz cannot be found, so the dropdown is never empty and the node still
# loads. ComfyUI hides nodes whose INPUT_TYPES raises.
_NO_MODELS = ["<no Topaz Video installation found>"]


def model_dir_or_none():
    """Model directory for dropdown population, or None.

    Never raises: a missing installation must not stop the node from appearing in the
    menu, otherwise the Diagnostics node cannot be used to find out why.
    """
    try:
        override = str(config.get("model_dir", "") or "")
        if override:
            return override
        install = find_install(str(config.get("video_install_path", "") or "") or None)
        return install.model_dir
    except Exception as exc:  # noqa: BLE001
        logger.debug("model directory unavailable: %s", exc)
        return None


def model_choices(filter_name: str) -> list[str]:
    labels = models.labels_for(model_dir_or_none(), filter_name)
    return labels or list(_NO_MODELS)


def default_model(filter_name: str, preferred: str) -> str:
    """Pick a sensible default, preferring an installed model.

    ``preferred`` is a short code such as ``prob-4``.
    """
    available = models.models_for(model_dir_or_none(), filter_name)
    for model in available:
        if model.short_code == preferred:
            return model.label
    for model in available:
        if model.weights_present:
            return model.label
    return available[0].label if available else _NO_MODELS[0]


def settings_from_input(engine_settings) -> EngineSettings:
    if isinstance(engine_settings, EngineSettings):
        return engine_settings
    return EngineSettings.from_config()


def interrupt_check():
    """Bridge to ComfyUI's interrupt mechanism, if present."""
    try:
        import comfy.model_management as mm
        mm.throw_exception_if_processing_interrupted()
    except ImportError:
        return False
    except Exception:
        return True
    return False


def make_progress(total: int):
    """Return a callback that drives ComfyUI's progress bar, if available."""
    try:
        from comfy.utils import ProgressBar
        bar = ProgressBar(max(total, 1))
    except Exception:  # noqa: BLE001
        return None

    state = {"last": 0}

    def report(frames_done: int, _line: str):
        step = max(0, min(frames_done, total) - state["last"])
        if step:
            state["last"] += step
            try:
                bar.update(step)
            except Exception:
                pass

    return report


def surface(exc: BaseException) -> str:
    """Turn an exception into a message worth showing in the ComfyUI error box."""
    if isinstance(exc, TopazError):
        return exc.detailed()
    return f"{type(exc).__name__}: {exc}"
