"""Licence verification with caching.

The node this replaces ran a real Topaz render before every job, with a 120 second
timeout, and treated a timeout as "licence invalid" (handover document, error 2). On the
target machine that meant a two minute stall in front of every workflow run, on a
perfectly valid licence.

Three corrections:

* the check runs once and the result is cached in ``config.json`` across restarts,
* the timeout is 30 seconds and a timeout means *unknown*, never *invalid* — the real run
  is allowed to proceed and give the authoritative answer,
* the cache is keyed to the installation, so an update or a path change re-checks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from . import config
from .command import FFmpegCommand, build_filter, default_global_args
from .discovery import TopazInstall
from .errors import TopazLicenseError
from .logging_util import get_logger
from .runner import run

logger = get_logger()

CHECK_TIMEOUT = 30.0

VALID = "valid"
INVALID = "invalid"
UNKNOWN = "unknown"


@dataclass
class LicenseStatus:
    state: str
    message: str
    checked_at: float = 0.0
    cached: bool = False

    @property
    def usable(self) -> bool:
        """Anything but a definite 'invalid' is worth attempting."""
        return self.state != INVALID


def _install_key(install: TopazInstall) -> str:
    """Identity of this installation: path plus ffmpeg size and mtime.

    An update or reinstall changes the binary, which invalidates the cache on its own.
    """
    try:
        stat = install.ffmpeg.stat()
        return f"{install.root}|{stat.st_size}|{int(stat.st_mtime)}"
    except OSError:
        return str(install.root)


def cached_status(install: TopazInstall) -> LicenseStatus | None:
    entry = config.get("license", {}) or {}
    if not isinstance(entry, dict):
        return None
    if entry.get("key") != _install_key(install):
        return None
    state = entry.get("state")
    if state not in (VALID, INVALID, UNKNOWN):
        return None
    # Never cache a negative result for long: the user may simply have been logged out.
    if state != VALID:
        return None
    return LicenseStatus(state=state, message=entry.get("message", ""),
                         checked_at=float(entry.get("checked_at") or 0.0), cached=True)


def store_status(install: TopazInstall, status: LicenseStatus) -> None:
    config.set_("license", {
        "key": _install_key(install),
        "state": status.state,
        "message": status.message,
        "checked_at": status.checked_at,
    })


def invalidate() -> None:
    """Force the next check to run for real."""
    config.set_("license", {})


def verify(install: TopazInstall, *, mode: str = "cached",
           model: str = "prob-4") -> LicenseStatus:
    """Check the licence.

    ``mode``: ``cached`` (default), ``force`` (ignore the cache), ``skip`` (do not check;
    the actual processing run will surface any licence problem itself).
    """
    if mode == "skip":
        return LicenseStatus(UNKNOWN, "licence check skipped", cached=False)

    if mode != "force":
        cached = cached_status(install)
        if cached:
            logger.debug("licence: using cached result from %s",
                         time.strftime("%Y-%m-%d %H:%M", time.localtime(cached.checked_at)))
            return cached

    status = _probe(install, model)
    if status.state == VALID:
        store_status(install, status)
    return status


def _probe(install: TopazInstall, model: str) -> LicenseStatus:
    """Smallest possible real tvai_up run: one 64x64 synthetic frame, discarded output."""
    # Eight frames, not one: tvai_up crashes outright on fewer than four, so a
    # single-frame probe would report "unknown" on a perfectly valid licence.
    command = FFmpegCommand(
        binary=str(install.ffmpeg),
        global_args=default_global_args(),
        input_args=["-f", "lavfi", "-i", "testsrc2=size=64x64:rate=8:duration=1"],
        filter_args=["-vf", build_filter("tvai_up", {
            "model": model, "scale": 1, "device": "-2", "download": 0,
        })],
        encoder_args=[],
        output_args=["-frames:v", "8", "-f", "null", "-"],
    )

    started = time.time()
    try:
        result = run(command, env=install.env(), cwd=str(install.root),
                     timeout=CHECK_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        logger.debug("licence probe could not run: %s", exc)
        return LicenseStatus(UNKNOWN, f"licence check could not run ({exc})",
                             checked_at=started)

    if result.ok:
        return LicenseStatus(VALID, "Topaz licence accepted", checked_at=time.time())

    lowered = result.stderr.lower()
    for marker in ("no valid license", "license is invalid", "license has expired",
                   "not logged in", "please log in", "login required",
                   "authentication failed", "trial has expired"):
        if marker in lowered:
            return LicenseStatus(INVALID,
                                 "Topaz reports no valid licence. Open Topaz Video and "
                                 "sign in.", checked_at=time.time())

    # Anything else — a missing model, a timeout, a driver hiccup — is not evidence about
    # the licence. Say so plainly instead of blocking the workflow.
    return LicenseStatus(
        UNKNOWN,
        "Licence could not be confirmed; proceeding. Topaz itself will report a licence "
        "problem if there is one.",
        checked_at=started,
    )


def raise_if_invalid(status: LicenseStatus) -> None:
    if status.state == INVALID:
        raise TopazLicenseError(status.message)
