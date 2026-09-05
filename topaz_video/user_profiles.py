"""Presets the user saves themselves.

Kept in ``user_presets.json`` next to the package, alongside ``config.json`` and
git-ignored for the same reason: it is this machine's data, not the project's.

Separate from :mod:`profiles` on purpose. That module reads two read-only sources — the
values built into this package and Topaz's own shipped presets — and it is imported by
node definitions at startup. Writing belongs somewhere it cannot make loading fragile: a
corrupt or unwritable file here must cost the user their custom presets and nothing
else, never the ability to open a workflow.
"""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from . import parameters
from .logging_util import get_logger

logger = get_logger()

USER_PRESETS_PATH = Path(__file__).resolve().parent.parent / "user_presets.json"

# Distinguishes user entries in the dropdown from the built-in ones (no prefix) and
# Topaz's own ("Topaz: ").
PREFIX = "My: "

MAX_NAME_LENGTH = 64
MAX_PRESETS = 200

_lock = threading.Lock()


def sanitize_name(name: str) -> str:
    """A name safe to show in a dropdown and to match on.

    Control characters are stripped and the length is capped. Names are not used as
    filenames — everything lives in one JSON file — so path separators are merely
    cosmetic here, not a traversal risk.
    """
    text = "".join(ch for ch in str(name or "") if ch.isprintable()).strip()
    return text[:MAX_NAME_LENGTH]


def sanitize_options(options) -> dict:
    """Keep only known tuning keys, coerced to float and clamped to their own range."""
    return parameters.clamp_all(options)


def load() -> list[dict]:
    """Every saved preset. Never raises — a broken file yields an empty list."""
    if not USER_PRESETS_PATH.exists():
        return []
    try:
        data = json.loads(USER_PRESETS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("user presets could not be read (%s); treating as empty", exc)
        return []

    entries = data.get("presets") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []

    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = sanitize_name(entry.get("name"))
        if not name:
            continue
        result.append({
            "name": name,
            "description": str(entry.get("description") or "").strip()[:400],
            "options": sanitize_options(entry.get("options")),
            "estimate": max(0, min(100, int(entry.get("estimate") or 0))),
            "suggested_model": str(entry.get("suggested_model") or "")[:64],
        })
    return result


def _write(entries: list[dict]) -> None:
    """Replace the file atomically, so an interrupted write cannot truncate it."""
    payload = json.dumps({"version": 1, "presets": entries}, indent=2)
    directory = USER_PRESETS_PATH.parent
    handle, temp_name = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
    try:
        with open(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
        Path(temp_name).replace(USER_PRESETS_PATH)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def save(name: str, options: dict, *, description: str = "",
         estimate: int = 0, suggested_model: str = "") -> dict:
    """Add or replace one preset. Returns the stored entry.

    Saving under an existing name overwrites it — that is what someone adjusting a
    preset and saving it again expects, and a silently ignored save would be worse.
    """
    clean_name = sanitize_name(name)
    if not clean_name:
        raise ValueError("a preset needs a name")

    entry = {
        "name": clean_name,
        "description": str(description or "").strip()[:400],
        "options": sanitize_options(options),
        "estimate": max(0, min(100, int(estimate or 0))),
        "suggested_model": str(suggested_model or "")[:64],
    }

    with _lock:
        entries = [e for e in load() if e["name"] != clean_name]
        if len(entries) >= MAX_PRESETS:
            raise ValueError(
                f"there are already {MAX_PRESETS} saved presets; delete one first"
            )
        entries.append(entry)
        entries.sort(key=lambda e: e["name"].lower())
        _write(entries)

    logger.info("saved user preset '%s' with %d value(s)", clean_name,
                len(entry["options"]))
    return entry


def delete(name: str) -> bool:
    """Remove one preset. Returns whether anything was removed."""
    clean_name = sanitize_name(name)
    with _lock:
        entries = load()
        remaining = [e for e in entries if e["name"] != clean_name]
        if len(remaining) == len(entries):
            return False
        _write(remaining)
    logger.info("deleted user preset '%s'", clean_name)
    return True
