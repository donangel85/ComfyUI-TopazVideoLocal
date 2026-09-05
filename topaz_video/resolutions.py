"""Named output resolutions, orientation, and divisibility snapping.

Two separate jobs that happen to belong together at the point where somebody picks an
output size:

*Naming*  — typing 3840 and 2160 into two boxes every time is slow and easy to get
wrong. The table below carries the sizes people actually mean, spelled out so the
ambiguous ones cannot be confused (see ``_TABLE`` for why 2K needed two entries).

*Snapping* — most latent-space video models only accept dimensions that are a multiple
of some number, because their encoder downsamples by that factor. MiniMax-H3 wants
multiples of 32, which is why Full HD is 1920x1088 there and not 1920x1080. Getting this
wrong surfaces much later as a tensor-shape error in a different node, so it is worth
fixing at the point the size is chosen.

Deliberately free of ComfyUI and of Topaz: this is arithmetic, and it is tested as such.
"""

from __future__ import annotations

from dataclasses import dataclass

LANDSCAPE = "landscape"
PORTRAIT = "portrait"
SQUARE = "square"
ORIENTATIONS = (LANDSCAPE, PORTRAIT, SQUARE)

UP = "up"
NEAREST = "nearest"
DOWN = "down"
ROUNDING_MODES = (UP, NEAREST, DOWN)

CUSTOM = "custom"

# Never snap below this. A dimension rounded down to 0 would be a far more confusing
# failure than a slightly-too-small frame.
MIN_DIMENSION = 16


@dataclass(frozen=True)
class Resolution:
    """One named size, always stored landscape. Portrait is the transpose."""

    name: str
    width: int
    height: int
    note: str = ""

    @property
    def label(self) -> str:
        suffix = f" — {self.note}" if self.note else ""
        return f"{self.name} ({self.width}x{self.height}){suffix}"


# Stored landscape; PORTRAIT swaps the pair. "2K" appears twice on purpose: DCI 2K is
# 2048x1080, but in common usage "2K" very often means QHD 2560x1440, and a single
# ambiguous entry would silently give half the people the size they did not want.
_TABLE: tuple[Resolution, ...] = (
    Resolution("SD 480p", 854, 480),
    Resolution("SD 576p", 1024, 576),
    Resolution("HD 720p", 1280, 720),
    Resolution("Full HD 1080p", 1920, 1080),
    Resolution("QHD 1440p", 2560, 1440, "often called 2K"),
    Resolution("DCI 2K", 2048, 1080, "cinema 2K"),
    Resolution("UHD 4K", 3840, 2160),
    Resolution("DCI 4K", 4096, 2160, "cinema 4K"),
    Resolution("UHD 8K", 7680, 4320),
)

_BY_NAME = {entry.name: entry for entry in _TABLE}
_BY_LABEL = {entry.label: entry for entry in _TABLE}


def table() -> tuple[Resolution, ...]:
    return _TABLE


def labels() -> list[str]:
    """Dropdown entries, with ``custom`` last so the named sizes come first."""
    return [entry.label for entry in _TABLE] + [CUSTOM]


def find(value: str) -> Resolution | None:
    """Look up by full label or by bare name; returns None for ``custom``."""
    if not value or value == CUSTOM:
        return None
    return _BY_LABEL.get(value) or _BY_NAME.get(value)


def snap(value: int, divisor: int, rounding: str = UP) -> int:
    """Round *value* to a multiple of *divisor*.

    ``divisor`` of 0 or 1 means no constraint. The result is never below
    ``MIN_DIMENSION`` and never below one whole divisor, so rounding down cannot
    collapse a dimension to nothing.
    """
    value = int(value)
    divisor = int(divisor)
    if divisor <= 1:
        return max(value, MIN_DIMENSION)

    if rounding == DOWN:
        snapped = (value // divisor) * divisor
    elif rounding == NEAREST:
        # Halfway goes up, matching the usual expectation and the UP default.
        snapped = ((value + divisor // 2) // divisor) * divisor
    else:
        snapped = -((-value) // divisor) * divisor  # ceiling division

    if snapped < divisor:
        snapped = divisor
    return max(snapped, MIN_DIMENSION)


def orient(width: int, height: int, orientation: str) -> tuple[int, int]:
    """Apply an orientation to a landscape pair.

    ``square`` takes the shorter edge, so 1920x1080 becomes 1080x1080 rather than
    stretching anything.
    """
    width, height = int(width), int(height)
    if orientation == PORTRAIT:
        return height, width
    if orientation == SQUARE:
        edge = min(width, height)
        return edge, edge
    return width, height


def resolve(preset: str, orientation: str = LANDSCAPE, *,
            custom_width: int = 1920, custom_height: int = 1080,
            divisor: int = 1, rounding: str = UP) -> tuple[int, int]:
    """Full pipeline: named size (or custom) -> orientation -> divisibility.

    Snapping happens last, so the result always satisfies the divisor no matter which
    orientation was applied.
    """
    entry = find(preset)
    if entry is None:
        width, height = int(custom_width), int(custom_height)
    else:
        width, height = entry.width, entry.height

    width, height = orient(width, height, orientation)
    return snap(width, divisor, rounding), snap(height, divisor, rounding)


def describe(width: int, height: int, divisor: int = 1) -> str:
    """One line for the log and for the node's info output."""
    text = f"{width}x{height}"
    ratio = _aspect_name(width, height)
    if ratio:
        text += f"  {ratio}"
    if divisor > 1:
        ok = width % divisor == 0 and height % divisor == 0
        text += f"  /{divisor}{'' if ok else '  NOT DIVISIBLE'}"
    return text


def _aspect_name(width: int, height: int) -> str:
    """Nearest common aspect ratio, or the plain decimal when nothing is close."""
    if not height:
        return ""
    ratio = width / height
    known = {"16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1.0, "21:9": 21 / 9,
             "9:16": 9 / 16, "3:4": 3 / 4, "2.39:1": 2.39, "3:2": 1.5}
    for name, value in known.items():
        # 1% covers the drift that snapping introduces: 1920x1088 is 1.765, not 1.778.
        if abs(ratio - value) <= value * 0.01:
            return name
    return f"{ratio:.3f}:1"
