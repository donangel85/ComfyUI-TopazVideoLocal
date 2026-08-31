"""Structured FFmpeg command construction.

The failure this design exists to prevent (handover document, section 4/17): the previous
node located the output encoder by calling ``cmd.index("-c:v")`` on the finished argument
list. Once an explicit input decoder was added, the *first* ``-c:v`` belonged to the input,
so the encoder fallback rewrote the input section and produced

    Option b:v (video bitrate) cannot be applied to input url ...

Here the sections are separate lists and are only flattened at the very end.
:meth:`FFmpegCommand.with_encoder` replaces ``encoder_args`` and nothing else, so that
class of bug cannot recur — there is no search step to get wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .logging_util import quote_command


def escape_filter_value(value: str) -> str:
    """Escape a value used inside an FFmpeg filter argument."""
    return str(value).replace("\\", "\\\\").replace(":", "\\:").replace(",", "\\,")


def render_parameters_dict(extra: dict) -> str:
    """Render the tvai_* ``parameters`` dictionary option.

    Quoted, so the inner separators are not mistaken for the filter's own.
    """
    inner = ":".join(f"{k}={v}" for k, v in extra.items())
    return "'" + inner + "'"


def build_filter(name: str, options: dict) -> str:
    """Render ``name=key=value:key=value``, skipping empty values."""
    parts = []
    for key, value in options.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            value = 1 if value else 0
        if isinstance(value, float):
            value = f"{value:g}"
        parts.append(f"{key}={value}")
    return f"{name}={':'.join(parts)}" if parts else name


@dataclass
class FFmpegCommand:
    """An FFmpeg invocation kept in labelled sections.

    Order is fixed: global, input, filter, encoder, output.
    """

    binary: str
    global_args: list[str] = field(default_factory=list)
    input_args: list[str] = field(default_factory=list)
    filter_args: list[str] = field(default_factory=list)
    encoder_args: list[str] = field(default_factory=list)
    output_args: list[str] = field(default_factory=list)

    def build(self) -> list[str]:
        return [
            str(self.binary),
            *map(str, self.global_args),
            *map(str, self.input_args),
            *map(str, self.filter_args),
            *map(str, self.encoder_args),
            *map(str, self.output_args),
        ]

    def with_encoder(self, encoder_args: list[str]) -> "FFmpegCommand":
        """Return a copy with a different encoder section.

        The only supported way to apply an encoder fallback.
        """
        return replace(self, encoder_args=list(encoder_args))

    @property
    def output_encoder(self) -> str | None:
        """The encoder actually selected, read from the encoder section only.

        Error classification uses this instead of grepping stderr, so a decoder problem
        can never be mistaken for an encoder problem.
        """
        args = self.encoder_args
        for i, arg in enumerate(args):
            if arg in ("-c:v", "-codec:v", "-vcodec") and i + 1 < len(args):
                return args[i + 1]
        return None

    def pretty(self) -> str:
        return quote_command(self.build())


# --- section builders --------------------------------------------------------------

def raw_input_args(width: int, height: int, fps: float, *,
                   pix_fmt: str = "rgb24", source: str = "pipe:0") -> list[str]:
    """Feed raw frames in.

    This is the whole point of the package's transport: with rawvideo there is no input
    decoder, so FFmpeg never has to choose one. Topaz's build has no software H.264
    decoder at all (``--disable-decoder=h264``), which is why the previous node ended up
    on ``h264_qsv`` and failed with ``MFX session -9`` on a machine without Intel
    graphics. No decoder, no decoder bug.
    """
    return [
        "-f", "rawvideo",
        "-pix_fmt", pix_fmt,
        "-s", f"{int(width)}x{int(height)}",
        "-r", _fps_str(fps),
        "-i", source,
    ]


def file_input_args(path: str, *, decoder: str | None = None) -> list[str]:
    """Read from a file, for the lossless fallback transport.

    ``decoder`` must name a decoder this build actually has. Note that plain ``h264`` is
    NOT one of them, which is why the fallback uses a lossless intermediate
    (utvideo/ffv1) whose decoder is present.
    """
    args: list[str] = []
    if decoder:
        args += ["-codec:v", decoder]
    args += ["-i", str(path)]
    return args


def raw_output_args(path: str, *, pix_fmt: str = "rgb24") -> list[str]:
    """Write raw frames to a file.

    Deliberately a file rather than ``pipe:1``: Topaz prints an
    ``[TopazAuthManager]parseAuth got details{"auth_studio":"<JWT>...`` blob to the child
    process' stdout. It is variable in length and contains a real credential, so mixing it
    with pixel data is both fragile and a leak. stdout is discarded instead.
    """
    return ["-f", "rawvideo", "-pix_fmt", pix_fmt, "-y", str(path)]


def lossless_encoder_args(codec: str = "utvideo") -> list[str]:
    """Encoder section for the file-based fallback.

    ``utvideo`` and ``ffv1`` are both present as encoder *and* decoder in Topaz's build,
    unlike H.264.
    """
    if codec == "ffv1":
        return ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "gbrp"]
    return ["-c:v", "utvideo", "-pix_fmt", "gbrp"]


def default_global_args(*, overwrite: bool = True) -> list[str]:
    args = ["-hide_banner", "-nostdin"]
    if overwrite:
        args.insert(0, "-y")
    return args


def _fps_str(fps: float) -> str:
    fps = float(fps)
    if abs(fps - round(fps)) < 1e-6:
        return str(int(round(fps)))
    # Preserve the usual broadcast rates exactly rather than as rounded decimals.
    for num, den in ((24000, 1001), (30000, 1001), (60000, 1001), (120000, 1001)):
        if abs(fps - num / den) < 1e-4:
            return f"{num}/{den}"
    return f"{fps:g}"
