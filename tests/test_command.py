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
    render_filter_path,
    render_parameters_dict,
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


class TestParametersDict:
    """The tvai_* ``parameters`` option is a nested dictionary, so its separators have
    to survive the filtergraph parser before the dictionary parser ever sees them.

    Measured against Topaz' ffmpeg 8.1 with hyp-1: quoting alone yields
    ``Error applying option 'hdr_ip_adjust' to filter 'tvai_up': Option not found``,
    escaping alone fails the same way, and the two combined run cleanly.
    """

    def test_multiple_entries_are_quoted_and_escaped(self):
        rendered = render_parameters_dict({
            "sdr_ip": "0.65", "hdr_ip_adjust": "0.5", "saturate": "0.5",
        })
        assert rendered == r"'sdr_ip=0.65\:hdr_ip_adjust=0.5\:saturate=0.5'"

    def test_separator_is_escaped_not_bare(self):
        rendered = render_parameters_dict({"a": "1", "b": "2"})
        assert ":" in rendered
        # A bare colon would be eaten by the filtergraph parser and turn 'b' into an
        # unknown top-level filter option.
        assert "1:b" not in rendered
        assert r"1\:b" in rendered

    def test_single_entry_still_quoted(self):
        # Deinterlace passes exactly one entry. It happened to work before this fix
        # precisely because it has no inner separator; it must keep working after it.
        assert render_parameters_dict({"interlacing": 0}) == "'interlacing=0'"

    def test_empty_dict(self):
        assert render_parameters_dict({}) == "''"

    def test_backslash_in_value_is_doubled(self):
        assert render_parameters_dict({"k": "a" + "\\" + "b"}) == r"'k=a\\b'"

    def test_render_survives_build_filter(self):
        rendered = build_filter("tvai_up", {
            "model": "hyp-1",
            "scale": 1,
            "parameters": render_parameters_dict({"sdr_ip": "0.65", "saturate": "0.5"}),
        })
        assert rendered == (
            "tvai_up=model=hyp-1:scale=1:"
            r"parameters='sdr_ip=0.65\:saturate=0.5'"
        )


class TestFilterPath:
    """Stabilization hands tvai_cpe and tvai_stb a path to its cpe.json side file.

    On Windows that path starts with a drive letter, and the bare form
    ``filename=C:/tmp/cpe.json`` makes the filtergraph parser stop at the colon and
    report ``No option name near '/tmp/cpe.json'``. Verified against ffmpeg 8.1:
    quoting alone and escaping alone both still fail; together they work.
    """

    def test_drive_letter_colon_is_quoted_and_escaped(self):
        assert render_filter_path("C:/tmp/cpe.json") == r"'C\:/tmp/cpe.json'"

    def test_backslash_separators_become_forward_slashes(self):
        # A backslash separator would otherwise read as an escape character.
        assert render_filter_path("C:\\tmp\\cpe.json") == r"'C\:/tmp/cpe.json'"

    def test_accepts_a_path_object(self):
        assert render_filter_path(Path("C:/tmp") / "cpe.json") == r"'C\:/tmp/cpe.json'"

    def test_relative_path_needs_no_escape_but_is_still_quoted(self):
        assert render_filter_path("cpe.json") == "'cpe.json'"

    def test_survives_build_filter(self):
        rendered = build_filter("tvai_cpe", {
            "model": "cpe-2",
            "filename": render_filter_path("C:/tmp/cpe.json"),
            "download": 1,
        })
        assert rendered == r"tvai_cpe=model=cpe-2:filename='C\:/tmp/cpe.json':download=1"
