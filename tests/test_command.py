"""Regression tests for the command builder.

The bug being guarded against (handover document, sections 4 and 17): the previous node
found the output encoder with ``cmd.index("-c:v")``, which returned the *input* decoder
once one was specified, so the encoder fallback rewrote the input section and FFmpeg
reported ``Option b:v cannot be applied to input url``.
"""

import sys
from pathlib import Path


from topaz_studio.command import (  # noqa: E402
    FFmpegCommand,
    build_filter,
    file_input_args,
    lossless_encoder_args,
    raw_input_args,
    raw_output_args,
)


def make_command():
    return FFmpegCommand(
        binary="ffmpeg.exe",
        global_args=["-y", "-hide_banner", "-nostdin"],
        input_args=file_input_args("in.mkv", decoder="utvideo"),
        filter_args=["-vf", "tvai_up=model=prob-4:scale=2"],
        encoder_args=["-c:v", "h264_nvenc", "-preset", "fast"],
        output_args=["-y", "out.mkv"],
    )


def test_sections_appear_in_order():
    argv = make_command().build()
    assert argv[0] == "ffmpeg.exe"
    assert argv.index("-i") < argv.index("-vf")
    assert argv.index("-vf") < argv.index("h264_nvenc")
    assert argv.index("h264_nvenc") < argv.index("out.mkv")


def test_output_encoder_ignores_input_decoder():
    """The input uses -codec:v utvideo; the encoder must still be reported correctly."""
    command = make_command()
    assert "-codec:v" in command.input_args
    assert command.output_encoder == "h264_nvenc"


def test_encoder_fallback_leaves_input_untouched():
    """This is the exact regression: -b:v must never land before -i."""
    command = make_command()
    fallback = command.with_encoder(["-c:v", "h264_mf", "-b:v", "10M"])

    assert fallback.input_args == command.input_args
    assert fallback.filter_args == command.filter_args
    assert fallback.output_encoder == "h264_mf"

    argv = fallback.build()
    assert argv.index("-b:v") > argv.index("-i"), \
        "-b:v ended up before the input; this is the bug from section 17"


def test_encoder_fallback_does_not_mutate_original():
    command = make_command()
    command.with_encoder(["-c:v", "h264_mf"])
    assert command.output_encoder == "h264_nvenc"


def test_pipe_command_has_no_decoder_at_all():
    """The pipe transport is the structural fix for the QSV failure."""
    command = FFmpegCommand(
        binary="ffmpeg.exe",
        global_args=["-y"],
        input_args=raw_input_args(320, 240, 24),
        filter_args=["-vf", "tvai_up=model=prob-4:scale=2"],
        encoder_args=[],
        output_args=raw_output_args("out.raw"),
    )
    argv = command.build()
    assert "-hwaccel" not in argv
    assert "-c:v" not in command.input_args
    assert "-codec:v" not in command.input_args
    assert command.output_encoder is None
    assert "rawvideo" in argv


def test_raw_input_preserves_fractional_frame_rates():
    assert "24000/1001" in raw_input_args(320, 240, 23.976)
    assert "24" in raw_input_args(320, 240, 24.0)


def test_lossless_codecs_are_decodable_by_topaz():
    """utvideo and ffv1 exist as both encoder and decoder in Topaz's ffmpeg build,
    unlike h264 whose decoder is compiled out."""
    assert lossless_encoder_args("utvideo")[1] == "utvideo"
    assert lossless_encoder_args("ffv1")[1] == "ffv1"


def test_build_filter_skips_empty_values():
    rendered = build_filter("tvai_up", {"model": "prob-4", "scale": 2, "w": None,
                                        "h": "", "vram": 0.5})
    assert rendered == "tvai_up=model=prob-4:scale=2:vram=0.5"


def test_build_filter_renders_bare_name_without_options():
    assert build_filter("tvai_up", {}) == "tvai_up"
