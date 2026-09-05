"""Topaz Diagnostics — answer "why doesn't it work" without running a workflow.

Requested as section 14.7 of the handover document. It also reports the Photo and
Gigapixel CLI lock status, so that finding does not have to be rediscovered.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..topaz_video import config, models
from ..topaz_video.discovery import (
    TopazInstall,
    available_encoders,
    clear_cache,
    find_install,
    has_software_h264_decoder,
)
from ..topaz_video.license import verify
from ..topaz_video.logging_util import scrub

from .common import CATEGORY

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

_OTHER_APPS = {
    "Topaz Photo": ("tpai.exe", ["--cli", "--help"]),
    "Topaz Gigapixel": ("gigapixel.exe", ["--help"]),
}


class TopazDiagnostics:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "check_license": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Run a real one-frame Topaz job to verify the licence. "
                               "Takes a few seconds.",
                }),
                "refresh": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Re-scan for the installation and rebuild the model list.",
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("report",)
    FUNCTION = "run"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True
    DESCRIPTION = "Report Topaz installation, models, GPU support and licence status."

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")  # always re-run; it is a diagnostic

    def run(self, check_license, refresh):
        if refresh:
            clear_cache()
            models.clear_cache()

        lines: list[str] = ["=== Topaz Video Local diagnostics ==="]

        try:
            install = find_install(str(config.get("video_install_path", "") or "") or None)
        except Exception as exc:  # noqa: BLE001
            lines += ["", "Topaz Video: NOT FOUND", "", scrub(str(exc))]
            lines += ["", *self._other_apps()]
            return ("\n".join(lines),)

        lines += self._install_section(install)
        lines += self._codec_section(install)
        lines += self._model_section(install)
        lines += self._license_section(install, check_license)
        lines += ["", *self._other_apps()]
        lines += ["", f"Config file: {config.CONFIG_PATH}"]

        return ("\n".join(lines),)

    # -- sections -------------------------------------------------------------

    def _install_section(self, install: TopazInstall) -> list[str]:
        return [
            "",
            "-- Installation --",
            f"Topaz Video:  {install.root}",
            f"ffmpeg:       {install.ffmpeg}",
            f"ffprobe:      {install.ffprobe or 'not found'}",
            f"model dir:    {install.model_dir or 'NOT FOUND'}",
            f"version:      {install.ffmpeg_version or 'unknown'}",
            f"tvai filters: {', '.join(install.filters) or 'none'}",
        ]

    def _codec_section(self, install: TopazInstall) -> list[str]:
        encoders = available_encoders(install)
        sw_h264 = has_software_h264_decoder(install)
        lines = [
            "",
            "-- Codecs --",
            f"software H.264 decoder: {'yes' if sw_h264 else 'no (expected)'}",
        ]
        if not sw_h264:
            lines.append("  Topaz builds ffmpeg with --disable-decoder=h264. This node")
            lines.append("  package feeds raw frames through a pipe, so no decoder is")
            lines.append("  needed and the Intel QSV failure cannot occur.")
        for name in ("h264_nvenc", "hevc_nvenc", "av1_nvenc", "h264_mf",
                     "h264_qsv", "utvideo", "ffv1"):
            lines.append(f"  {name:<12} {'available' if name in encoders else '-'}")
        return lines

    def _model_section(self, install: TopazInstall) -> list[str]:
        lines = ["", "-- Models --"]
        if not install.model_dir:
            return lines + ["  model directory not found"]

        titles = {
            models.UPSCALE: "Upscale (tvai_up)",
            models.INTERPOLATE: "Frame interpolation (tvai_fi)",
            models.STABILIZE: "Stabilization (tvai_stb)",
            models.CAMERA_POSE: "Camera pose (tvai_cpe)",
            models.ESTIMATE: "Parameter estimation (tvai_pe)",
        }
        for filter_name, title in titles.items():
            entries = models.models_for(install.model_dir, filter_name)
            ready = [m for m in entries if m.weights_present]
            lines.append(f"  {title}: {len(entries)} available, {len(ready)} installed")
            for model in entries[:12]:
                mark = "installed" if model.weights_present else "needs download"
                lines.append(f"    {model.display_name} ({model.short_code}) "
                             f"[{mark}]")
            if len(entries) > 12:
                lines.append(f"    ... and {len(entries) - 12} more")

        lines.append("  Hidden: Astra / Starlight SLP-2.5 / Hyperion-2 run inside "
                     "Topaz's")
        lines.append("  neuroserver runtime and cannot be reached through ffmpeg.")
        return lines

    def _license_section(self, install: TopazInstall, check: bool) -> list[str]:
        lines = ["", "-- Licence --"]
        if not check:
            from ..topaz_video.license import cached_status
            cached = cached_status(install)
            if cached:
                lines.append(f"  cached: {cached.state} ({cached.message})")
            else:
                lines.append("  not verified yet (enable check_license to test)")
            return lines
        status = verify(install, mode="force")
        lines.append(f"  {status.state}: {status.message}")
        return lines

    def _other_apps(self) -> list[str]:
        """Report the CLI lock on Photo and Gigapixel.

        Both refuse automation without an enterprise licence, which is why this package
        covers Topaz Video only.
        """
        lines = ["-- Topaz Photo / Gigapixel --"]
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        for app, (exe, args) in _OTHER_APPS.items():
            path = Path(program_files) / "Topaz Labs LLC" / app / exe
            if not path.is_file():
                lines.append(f"  {app}: not installed")
                continue
            verdict = self._probe_cli(path, args)
            lines.append(f"  {app}: {verdict}")
        lines.append("  CLI automation of these two requires a Topaz enterprise licence.")
        return lines

    def _probe_cli(self, path: Path, args: list[str]) -> str:
        try:
            proc = subprocess.run(
                [str(path), *args], capture_output=True, text=True, timeout=45,
                creationflags=_CREATE_NO_WINDOW, errors="replace",
            )
            text = ((proc.stdout or "") + (proc.stderr or "")).lower()
        except (OSError, subprocess.SubprocessError) as exc:
            return f"probe failed ({exc})"
        if "enterprise" in text or "has been disabled" in text:
            return "installed, CLI locked (enterprise licence required)"
        if not text.strip():
            return "installed, CLI gave no output"
        return "installed, CLI responded (may be usable)"
