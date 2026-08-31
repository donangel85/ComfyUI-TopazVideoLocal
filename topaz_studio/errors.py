"""Stage-aware error classification for Topaz FFmpeg runs.

The node this package replaces decided "the encoder failed" by searching the whole stderr
for substrings like ``"not support"``. That misfired on the QSV *decoder* message
``The current mfx implementation is not supported``, so a decoder failure triggered an
encoder fallback that could never help (handover document, section 5).

The rule here: a failure is only attributed to a stage when the evidence names that stage.
Everything else stays :class:`TopazProcessError` with the full stderr attached, which is
honest and debuggable, rather than a confident wrong guess.
"""

from __future__ import annotations

import re

from .logging_util import scrub

# Windows STATUS_ACCESS_VIOLATION, seen when tvai_up gets fewer frames than a temporal
# model needs. Python surfaces it as an unsigned exit code.
ACCESS_VIOLATION = 0xC0000005
UNSIGNED_ACCESS_VIOLATION = 3221225477


class TopazError(RuntimeError):
    """Base class. ``stderr`` is already scrubbed of auth material."""

    def __init__(self, message: str, *, stderr: str = "", exit_code: int | None = None,
                 command: str = ""):
        super().__init__(message)
        self.message = message
        self.stderr = scrub(stderr or "")
        self.exit_code = exit_code
        self.command = command

    def detailed(self) -> str:
        parts = [self.message]
        if self.exit_code is not None:
            parts.append(f"exit code: {self.exit_code}")
        if self.command:
            parts.append(f"command:\n{self.command}")
        if self.stderr:
            tail = "\n".join(self.stderr.strip().splitlines()[-25:])
            parts.append(f"ffmpeg output (tail):\n{tail}")
        return "\n\n".join(parts)


class TopazNotFoundError(TopazError):
    """Topaz Video installation could not be located or is not usable."""


class TopazLicenseError(TopazError):
    """Topaz reports a licensing or login problem."""


class TopazModelError(TopazError):
    """The requested model is unusable: missing weights, bad scale, or meta-model."""


class TopazDecodeError(TopazError):
    """Input decoding failed. Only reachable on the file-based fallback path."""


class TopazEncodeError(TopazError):
    """The output encoder failed. Only raised when the encoder is actually named."""


class TopazProcessError(TopazError):
    """Anything else. Deliberately not guessed at."""


# --- signatures -------------------------------------------------------------------
# Each entry must name its stage unambiguously. Generic words such as "Unsupported" or
# "not support" are intentionally absent: that was the original bug.

_LICENSE_SIGNATURES = (
    "no valid license",
    "license is invalid",
    "license has expired",
    "not logged in",
    "please log in",
    "login required",
    "authentication failed",
    "failed to authenticate",
    "trial has expired",
)

_MODEL_SIGNATURES = (
    "failed to configure output pad",
    "could not load model",
    "model not found",
    "failed to load model",
    "unknown model",
    "invalid model",
)

_ENCODER_SIGNATURES = (
    "no capable devices found",
    "error while opening encoder",
    "cannot load nvcuda",
    "openencodesessionex failed",
)

_DECODER_SIGNATURES = (
    "error creating a mfx session",
    "error initializing an mfx session",
    "error decoding header",
    "no decoder for stream",
    "decoder not found",
)


def _contains(haystack: str, needles) -> str | None:
    low = haystack.lower()
    for needle in needles:
        if needle in low:
            return needle
    return None


def classify(exit_code: int, stderr: str, *, command: str = "",
             output_encoder: str | None = None,
             model: str | None = None,
             frame_count: int | None = None,
             min_frames: int | None = None) -> TopazError:
    """Turn a failed run into the most specific error the evidence supports.

    ``output_encoder`` is passed in from the command that was actually built, so an
    encoder failure is only ever claimed when we know which encoder was in play — never
    inferred by grepping the log.
    """
    text = scrub(stderr or "")

    def make(cls, msg):
        return cls(msg, stderr=text, exit_code=exit_code, command=command)

    # A crash rather than a reported error. With tvai_* this almost always means the
    # filter got fewer frames than the model needs, which we can say plainly.
    if exit_code in (ACCESS_VIOLATION, UNSIGNED_ACCESS_VIOLATION, -1073741819):
        if frame_count is not None and min_frames is not None and frame_count < min_frames:
            return make(
                TopazModelError,
                f"Topaz crashed because the batch is too short: {frame_count} frame(s) "
                f"given, model '{model or '?'}' needs at least {min_frames}. "
                f"This is a known Topaz limitation, not a workflow error.",
            )
        return make(
            TopazProcessError,
            "Topaz crashed (access violation). This usually means the input batch was too "
            "short for a temporal model, or the selected model is a meta-model that cannot "
            "be invoked directly.",
        )

    if _contains(text, _LICENSE_SIGNATURES):
        return make(TopazLicenseError,
                    "Topaz reports a license or login problem. Open the Topaz Video "
                    "desktop app and sign in, then retry.")

    if _contains(text, _MODEL_SIGNATURES):
        hint = ""
        if model:
            hint = (f" Model '{model}': check that the scale factor is supported and that "
                    f"its weights are installed (enable 'allow_model_download' to let "
                    f"Topaz fetch them).")
        return make(TopazModelError, f"Topaz could not use the requested model.{hint}")

    if _contains(text, _DECODER_SIGNATURES):
        return make(TopazDecodeError,
                    "Input decoding failed. Topaz's FFmpeg has no software H.264/HEVC "
                    "decoder, so it falls back to hardware decoders that may be absent. "
                    "Use the pipe transport, which needs no decoder at all.")

    # Only now, and only if we know the encoder, may this be called an encoder failure.
    if output_encoder and _contains(text, _ENCODER_SIGNATURES):
        return make(TopazEncodeError,
                    f"The output encoder '{output_encoder}' failed to open.")

    return make(TopazProcessError, "Topaz FFmpeg failed.")


def is_encoder_failure(stderr: str, output_encoder: str | None) -> bool:
    """Whether an encoder fallback is justified.

    Requires both a known encoder and an unambiguous encoder message. The QSV decoder
    error deliberately does not satisfy this.
    """
    if not output_encoder:
        return False
    return _contains(scrub(stderr or ""), _ENCODER_SIGNATURES) is not None
