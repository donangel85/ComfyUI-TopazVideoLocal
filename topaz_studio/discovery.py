"""Locate the Topaz Video installation and its model directory.

A candidate is only accepted once ``ffmpeg -filters`` actually reports ``tvai_up``. That
matters: a plain system FFmpeg on PATH looks exactly like the real thing until the moment
a Topaz filter is requested, and would otherwise fail much later with a confusing message.
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .errors import TopazNotFoundError
from .logging_util import get_logger

logger = get_logger()

_APP_SUBDIR = os.path.join("Topaz Labs LLC", "Topaz Video")
_MODEL_SUBDIR = os.path.join("Topaz Labs LLC", "Topaz Video", "models")

_ENV_INSTALL_VARS = ("TOPAZ_STUDIO_VIDEO_DIR", "TVAI_DIR", "TOPAZ_VIDEO_DIR")
_ENV_MODEL_VARS = ("TOPAZ_STUDIO_MODEL_DIR", "TVAI_MODEL_DIR", "TVAI_MODEL_DATA_DIR")

_SUBPROCESS_FLAGS = 0
if os.name == "nt":  # keep console windows from flashing up during probes
    _SUBPROCESS_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class TopazInstall:
    """A validated Topaz Video installation."""

    root: Path
    ffmpeg: Path
    ffprobe: Path | None
    model_dir: Path | None
    ffmpeg_version: str = ""
    build_flags: str = ""
    filters: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_tvai(self) -> bool:
        return "tvai_up" in self.filters

    def env(self) -> dict:
        """Environment for a Topaz FFmpeg subprocess.

        ``TVAI_MODEL_DIR`` / ``TVAI_MODEL_DATA_DIR`` tell the filters where the weights
        live; the install root must be on PATH because Topaz ships its own DLLs there.
        """
        env = os.environ.copy()
        if self.model_dir:
            env["TVAI_MODEL_DIR"] = str(self.model_dir)
            env["TVAI_MODEL_DATA_DIR"] = str(self.model_dir)
        env["PATH"] = str(self.root) + os.pathsep + env.get("PATH", "")
        return env


def _run(cmd, timeout=30) -> str:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=_SUBPROCESS_FLAGS, errors="replace",
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("probe failed for %s: %s", cmd[0] if cmd else "?", exc)
        return ""


def _candidate_roots(explicit: str | None = None):
    """Search order, most specific first."""
    if explicit:
        yield Path(explicit)

    for var in _ENV_INSTALL_VARS:
        value = os.environ.get(var)
        if value:
            yield Path(value)

    # Everything below this point is a Windows location. Automatic detection is
    # Windows-only, deliberately: it is the only platform this has ever run on, and
    # guessing at an .app bundle nobody has opened would be worse than saying so. On
    # anything else the explicit path and the environment variables above are the way
    # in, and find_install's message says that.
    if os.name != "nt":
        return

    yield from _registry_roots()

    for env_var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(env_var)
        if base:
            yield Path(base) / _APP_SUBDIR

    # Installations moved to another drive keep the same relative layout.
    for drive in "CDEFGH":
        yield Path(f"{drive}:/Program Files") / _APP_SUBDIR


def _registry_roots():
    try:
        import winreg
    except ImportError:
        return

    hives = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, path in hives:
        try:
            with winreg.OpenKey(hive, path) as root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        name = winreg.EnumKey(root, i)
                        with winreg.OpenKey(root, name) as sub:
                            display = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                            if "topaz" not in display.lower() or "video" not in display.lower():
                                continue
                            for value in ("InstallLocation", "DisplayIcon"):
                                try:
                                    loc = str(winreg.QueryValueEx(sub, value)[0]).strip('"')
                                except OSError:
                                    continue
                                if loc:
                                    p = Path(loc)
                                    yield p if p.is_dir() else p.parent
                    except OSError:
                        continue
        except OSError:
            continue


def _model_dir_candidates(root: Path):
    for var in _ENV_MODEL_VARS:
        value = os.environ.get(var)
        if value:
            yield Path(value)
    program_data = os.environ.get("ProgramData")
    if program_data:
        yield Path(program_data) / _MODEL_SUBDIR
    yield Path("C:/ProgramData") / _MODEL_SUBDIR
    yield root / "models"


def _find_model_dir(root: Path) -> Path | None:
    for candidate in _model_dir_candidates(root):
        try:
            if candidate.is_dir() and any(candidate.glob("*.json")):
                return candidate
        except OSError:
            continue
    return None


def _inspect(root: Path) -> TopazInstall | None:
    """Validate a candidate root, or return None."""
    try:
        if not root.is_dir():
            return None
    except OSError:
        return None

    ffmpeg = root / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not ffmpeg.is_file():
        return None

    version_text = _run([str(ffmpeg), "-hide_banner", "-version"])
    if not version_text:
        return None

    filters_text = _run([str(ffmpeg), "-hide_banner", "-filters"], timeout=45)
    filters = tuple(sorted(set(re.findall(r"\b(tvai_[a-z]+)\b", filters_text))))
    if "tvai_up" not in filters:
        logger.debug("rejecting %s: ffmpeg has no tvai_up filter", root)
        return None

    version_line = version_text.splitlines()[0] if version_text else ""
    build_match = re.search(r"configuration:(.*)", version_text)

    ffprobe = root / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
    return TopazInstall(
        root=root,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe if ffprobe.is_file() else None,
        model_dir=_find_model_dir(root),
        ffmpeg_version=version_line.strip(),
        build_flags=(build_match.group(1).strip() if build_match else ""),
        filters=filters,
    )


@functools.lru_cache(maxsize=8)
def _find_cached(explicit: str | None) -> TopazInstall | None:
    seen = set()
    for candidate in _candidate_roots(explicit):
        try:
            key = str(candidate.resolve()).lower()
        except OSError:
            key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        install = _inspect(candidate)
        if install:
            logger.debug("using Topaz Video at %s", install.root)
            return install
    return None


def find_install(explicit_path: str | None = None, *, refresh: bool = False) -> TopazInstall:
    """Return a validated installation or raise :class:`TopazNotFoundError`."""
    if refresh:
        _find_cached.cache_clear()
    install = _find_cached(explicit_path or None)
    if install is None:
        searched = "\n  ".join(str(p) for p in _candidate_roots(explicit_path)) or "-"
        platform_note = "" if os.name == "nt" else (
            "\nNote: automatic detection is implemented for Windows only, so on this "
            "platform the path has to be given. Point it at the directory that holds "
            "Topaz's own ffmpeg binary."
        )
        raise TopazNotFoundError(
            "No usable Topaz Video installation found. A directory qualifies only if it "
            "contains an ffmpeg that provides the 'tvai_up' filter.\n"
            "Set the path explicitly in the Topaz Engine Settings node, or via the "
            "TOPAZ_STUDIO_VIDEO_DIR environment variable."
            f"{platform_note}\n"
            f"Searched:\n  {searched}"
        )
    return install


def clear_cache() -> None:
    _find_cached.cache_clear()


def has_software_h264_decoder(install: TopazInstall) -> bool:
    """Whether this build can decode H.264 without hardware.

    Topaz ships ``--disable-decoder=h264``, so this is expected to be False. It is the
    reason the pipe transport exists, and the diagnostics node reports it.
    """
    text = _run([str(install.ffmpeg), "-hide_banner", "-decoders"], timeout=45)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "h264":
            return True
    return False


def available_encoders(install: TopazInstall) -> set[str]:
    text = _run([str(install.ffmpeg), "-hide_banner", "-encoders"], timeout=45)
    found = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and re.fullmatch(r"[A-Z.]{6}", parts[0]):
            found.add(parts[1])
    return found
