"""The processing pipeline: IMAGE batch in, IMAGE batch out.

    IMAGE tensor
      -> rgb24 bytes
      -> ffmpeg stdin  (rawvideo — no decoder involved)
      -> tvai_* filter (Topaz AI on the GPU)
      -> rawvideo file (stdout is unusable, it carries the auth blob)
      -> IMAGE tensor

There is no container, no H.264 generation, and no decoder anywhere on the input side,
which is what makes the QSV failure from the handover document structurally impossible
rather than merely worked around.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import config, frames as frame_utils
from .command import (
    FFmpegCommand,
    build_filter,
    default_global_args,
    file_input_args,
    lossless_encoder_args,
    raw_input_args,
    raw_output_args,
)
from .discovery import TopazInstall, find_install
from .errors import TopazError, TopazModelError
from .license import raise_if_invalid, verify
from .logging_util import get_logger, set_verbose
from .models import TopazModel, resolve
from .runner import run_checked

logger = get_logger()


@dataclass
class EngineSettings:
    """Shared execution options, supplied by the Engine Settings node."""

    device: str = "-2"                 # -2 auto. device=0 is known to fail here.
    instances: int = 0
    vram: float = 1.0
    allow_model_download: bool = False
    transport: str = "pipe"            # "pipe" or "file"
    keep_temp_on_error: bool = False
    verbose: bool = False
    license_check: str = "cached"      # cached | force | skip
    install_path: str = ""
    model_dir: str = ""
    timeout: float = 0.0               # 0 = no timeout

    @classmethod
    def from_config(cls) -> "EngineSettings":
        defaults = config.get("defaults", {}) or {}
        return cls(
            device=str(defaults.get("device", "-2")),
            instances=int(defaults.get("instances", 0)),
            vram=float(defaults.get("vram", 1.0)),
            allow_model_download=bool(defaults.get("allow_model_download", False)),
            transport=str(defaults.get("transport", "pipe")),
            keep_temp_on_error=bool(defaults.get("keep_temp_on_error", False)),
            verbose=bool(defaults.get("verbose", False)),
            install_path=str(config.get("video_install_path", "") or ""),
            model_dir=str(config.get("model_dir", "") or ""),
        )


@dataclass
class FilterSpec:
    """One tvai_* filter invocation."""

    name: str
    options: dict = field(default_factory=dict)

    def render(self) -> str:
        return build_filter(self.name, self.options)


class TopazEngine:
    def __init__(self, settings: EngineSettings | None = None):
        self.settings = settings or EngineSettings.from_config()
        set_verbose(self.settings.verbose)
        self.install: TopazInstall = find_install(self.settings.install_path or None)
        self.model_dir = Path(self.settings.model_dir) if self.settings.model_dir \
            else self.install.model_dir

    # -- public ---------------------------------------------------------------

    def resolve_model(self, value: str, filter_name: str) -> TopazModel:
        model = resolve(self.model_dir, value, filter_name)
        if model is None:
            raise TopazModelError(
                f"Model '{value}' is not available for {filter_name}. "
                f"Re-open the model dropdown to refresh the list."
            )
        if not model.weights_present and not self.settings.allow_model_download:
            raise TopazModelError(
                f"Model '{model.display_name} ({model.short_code})' has no weights "
                f"installed on this machine. Either process it once in the Topaz Video "
                f"app so it downloads, or enable 'allow_model_download' in the Topaz "
                f"Engine Settings node."
            )
        return model

    def check_license(self) -> None:
        status = verify(self.install, mode=self.settings.license_check)
        raise_if_invalid(status)
        if not status.cached and status.state != "skip":
            logger.info("licence: %s", status.message)

    def analyze(self, images, spec, *, fps: float, model=None,
                interrupt_check=None) -> str:
        """Run an analysis-only filter and return its (scrubbed) stderr.

        ``tvai_pe`` writes its findings as text rather than to a file — one
        ``Parameter values:[...]`` line per frame, on stderr. Nothing is rendered, so the
        output goes to the null muxer.
        """
        payload, count, width, height = frame_utils.tensor_to_rgb24(images)
        if count == 0:
            raise TopazError("empty IMAGE batch")

        min_frames = max(frame_utils.MIN_FRAMES, model.frame_count if model else 0)
        payload, _ = frame_utils.pad_to_minimum(payload, count, width, height, min_frames)

        command = FFmpegCommand(
            binary=str(self.install.ffmpeg),
            global_args=default_global_args(),
            input_args=raw_input_args(width, height, fps),
            filter_args=["-vf", spec.render()],
            encoder_args=[],
            output_args=["-f", "null", "-"],
        )
        result = run_checked(
            command, env=self.install.env(), cwd=str(self.install.root),
            stdin_payload=payload, timeout=self.settings.timeout or None,
            interrupt_check=interrupt_check,
            model=model.short_code if model else None,
            frame_count=count, min_frames=min_frames,
        )
        return result.stderr

    def process(self, images, spec, *, fps: float,
                out_width: int, out_height: int,
                model: TopazModel | None = None,
                progress=None, interrupt_check=None):
        """Run one tvai_* filter over an IMAGE batch.

        ``spec`` is a :class:`FilterSpec`, or a callable taking the run directory and
        returning ``(pre_pass_spec_or_None, main_spec)``. The callable form exists for
        two-pass filters: stabilization first runs ``tvai_cpe`` to write a ``cpe.json``
        into the run directory, then ``tvai_stb`` reads it back.
        """
        payload, count, width, height = frame_utils.tensor_to_rgb24(images)
        if count == 0:
            raise TopazError("empty IMAGE batch")

        min_frames = max(frame_utils.MIN_FRAMES, model.frame_count if model else 0)
        payload, padding = frame_utils.pad_to_minimum(payload, count, width, height,
                                                      min_frames)
        padded_count = count + padding
        if padding:
            logger.info("batch of %d padded to %d frames (Topaz needs at least %d)",
                        count, padded_count, min_frames)

        work_dir = Path(tempfile.gettempdir()) / "comfyui_topaz_studio" / uuid.uuid4().hex
        work_dir.mkdir(parents=True, exist_ok=True)
        raw_out = work_dir / "out.raw"
        failed = False
        try:
            pre_spec = None
            if callable(spec):
                pre_spec, spec = spec(work_dir)
            if pre_spec is not None:
                self._run_analysis_pass(payload, width, height, fps, pre_spec,
                                        model, interrupt_check)

            if self.settings.transport == "file":
                result_bytes = self._run_file_transport(
                    payload, padded_count, width, height, fps, spec, work_dir, raw_out,
                    model, progress, interrupt_check)
            else:
                result_bytes = self._run_pipe_transport(
                    payload, padded_count, width, height, fps, spec, raw_out,
                    model, progress, interrupt_check)

            result = frame_utils.rgb24_to_tensor(result_bytes, out_width, out_height)
            # Frame interpolation legitimately changes the count, so only trim padding
            # when the filter preserves it.
            if padding and len(result) == padded_count:
                result = frame_utils.trim_padding(result, padding)
            return result
        except BaseException:
            failed = True
            raise
        finally:
            self._cleanup(work_dir, failed)

    # -- transports -----------------------------------------------------------

    def _run_pipe_transport(self, payload, count, width, height, fps, spec, raw_out,
                            model, progress, interrupt_check) -> bytes:
        command = FFmpegCommand(
            binary=str(self.install.ffmpeg),
            global_args=default_global_args(),
            input_args=raw_input_args(width, height, fps),
            filter_args=["-vf", spec.render()],
            encoder_args=[],                       # rawvideo needs no encoder options
            output_args=raw_output_args(str(raw_out)),
        )
        run_checked(
            command,
            env=self.install.env(),
            cwd=str(self.install.root),
            stdin_payload=payload,
            timeout=self.settings.timeout or None,
            progress=progress,
            interrupt_check=interrupt_check,
            model=model.short_code if model else None,
            frame_count=count,
            min_frames=max(frame_utils.MIN_FRAMES, model.frame_count if model else 0),
        )
        return raw_out.read_bytes()

    def _run_file_transport(self, payload, count, width, height, fps, spec, work_dir,
                            raw_out, model, progress, interrupt_check) -> bytes:
        """Lossless intermediate file instead of a pipe.

        Kept as a debugging aid and a safety net. Uses utvideo because Topaz's build has
        it as both encoder and decoder — unlike H.264, whose decoder is compiled out.
        """
        staged = work_dir / "in.mkv"
        stage = FFmpegCommand(
            binary=str(self.install.ffmpeg),
            global_args=default_global_args(),
            input_args=raw_input_args(width, height, fps),
            filter_args=[],
            encoder_args=lossless_encoder_args("utvideo"),
            output_args=["-y", str(staged)],
        )
        run_checked(stage, env=self.install.env(), cwd=str(self.install.root),
                    stdin_payload=payload, timeout=self.settings.timeout or None)

        command = FFmpegCommand(
            binary=str(self.install.ffmpeg),
            global_args=default_global_args(),
            input_args=file_input_args(str(staged), decoder="utvideo"),
            filter_args=["-vf", spec.render()],
            encoder_args=[],
            output_args=raw_output_args(str(raw_out)),
        )
        run_checked(
            command, env=self.install.env(), cwd=str(self.install.root),
            timeout=self.settings.timeout or None, progress=progress,
            interrupt_check=interrupt_check,
            model=model.short_code if model else None,
            frame_count=count,
            min_frames=max(frame_utils.MIN_FRAMES, model.frame_count if model else 0),
        )
        return raw_out.read_bytes()

    def _run_analysis_pass(self, payload, width, height, fps, spec, model,
                           interrupt_check) -> None:
        """First pass of a two-pass filter. Produces a side file, no video output."""
        command = FFmpegCommand(
            binary=str(self.install.ffmpeg),
            global_args=default_global_args(),
            input_args=raw_input_args(width, height, fps),
            filter_args=["-vf", spec.render()],
            encoder_args=[],
            output_args=["-f", "null", "-"],
        )
        logger.info("analysis pass: %s", spec.render())
        run_checked(
            command, env=self.install.env(), cwd=str(self.install.root),
            stdin_payload=payload, timeout=self.settings.timeout or None,
            interrupt_check=interrupt_check,
            model=model.short_code if model else None,
        )

    # -- helpers --------------------------------------------------------------

    def base_options(self) -> dict:
        """Options every tvai_* filter accepts."""
        options = {
            "device": self.settings.device or "-2",
            "download": 1 if self.settings.allow_model_download else 0,
        }
        if self.settings.instances:
            options["instances"] = int(self.settings.instances)
        if self.settings.vram and abs(self.settings.vram - 1.0) > 1e-6:
            options["vram"] = float(self.settings.vram)
        return options

    def _cleanup(self, work_dir: Path, failed: bool) -> None:
        if failed and self.settings.keep_temp_on_error:
            logger.warning("temporary files kept for inspection: %s", work_dir)
            return
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except OSError:
            pass
