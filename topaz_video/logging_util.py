"""Logging for the Topaz Video Local nodes.

One thing here is not cosmetic: Topaz writes an ``[TopazAuthManager]parseAuth got
details{"auth_studio":"<JWT>...`` blob to the child process' stdout. That blob carries a
real authentication token. It must never reach a log file, a ComfyUI console, or a bug
report, so every string that leaves this module goes through :func:`scrub` first.
"""

from __future__ import annotations

import logging
import re
import sys

LOGGER_NAME = "TopazVideoLocal"

# Anything that looks like the auth blob or a bare JWT. Kept deliberately broad: a false
# positive costs a redacted log line, a false negative leaks a credential.
_SECRET_PATTERNS = (
    re.compile(r"\[TopazAuthManager\][^\r\n]*", re.IGNORECASE),
    re.compile(r'"auth[_a-z]*"\s*:\s*"[^"]*"', re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.?[A-Za-z0-9_-]*"),
)

_REDACTED = "[redacted: Topaz auth data]"


def scrub(text: str) -> str:
    """Remove Topaz authentication material from *text*."""
    if not text:
        return text
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


class _ScrubbingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: scrub(v) if isinstance(v, str) else v
                               for k, v in record.args.items()}
            else:
                record.args = tuple(scrub(a) if isinstance(a, str) else a
                                    for a in record.args)
        return True


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not getattr(logger, "_topaz_configured", False):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[TopazVideoLocal] %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.addFilter(_ScrubbingFilter())
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger._topaz_configured = True  # type: ignore[attr-defined]
    return logger


def set_verbose(verbose: bool) -> None:
    get_logger().setLevel(logging.DEBUG if verbose else logging.INFO)


def quote_command(cmd) -> str:
    """Render an argv list as a copy-pasteable command line.

    Section 14.4 of the handover document asks for this: every FFmpeg call should be
    reproducible by hand from the log.
    """
    parts = []
    for arg in cmd:
        arg = str(arg)
        parts.append(f'"{arg}"' if (" " in arg or not arg) else arg)
    return " ".join(parts)
