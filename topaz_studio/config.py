"""Persistent configuration.

Stored next to the package as ``config.json`` (git-ignored) so it survives ComfyUI
restarts. A corrupt file is replaced rather than raised: a broken settings file should
never be the reason a workflow cannot run.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .logging_util import get_logger

logger = get_logger()

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

_DEFAULTS: dict[str, Any] = {
    "version": 1,
    "video_install_path": "",     # empty => auto-detect
    "model_dir": "",              # empty => auto-detect
    "license": {},                # cache written by license.py
    "defaults": {
        "device": "-2",           # auto; device=0 is known to fail on mixed-GPU systems
        "vram": 1.0,
        "instances": 0,
        "allow_model_download": False,
        "transport": "pipe",      # "pipe" or "file"
        "keep_temp_on_error": False,
        "verbose": False,
    },
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None


def _merge_defaults(data: dict) -> dict:
    merged = json.loads(json.dumps(_DEFAULTS))
    for key, value in (data or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def load(*, refresh: bool = False) -> dict:
    global _cache
    with _lock:
        if _cache is not None and not refresh:
            return _cache
        data = {}
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("config root is not an object")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("config.json unreadable (%s); falling back to defaults", exc)
                data = {}
        _cache = _merge_defaults(data)
        return _cache


def save(data: dict | None = None) -> None:
    """Write atomically so an interrupted save cannot corrupt the file."""
    global _cache
    with _lock:
        if data is not None:
            _cache = _merge_defaults(data)
        if _cache is None:
            return
        payload = json.dumps(_cache, indent=2, sort_keys=True)
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(CONFIG_PATH.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                os.replace(tmp, CONFIG_PATH)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
        except OSError as exc:
            logger.warning("could not write config.json: %s", exc)


def get(path: str, default=None):
    """Read a dotted key, e.g. ``get("defaults.device")``."""
    node: Any = load()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def set_(path: str, value, *, persist: bool = True) -> None:
    node = load()
    parts = path.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            return
    node[parts[-1]] = value
    if persist:
        save()


def reset() -> None:
    global _cache
    with _lock:
        _cache = None
    if CONFIG_PATH.exists():
        try:
            CONFIG_PATH.unlink()
        except OSError as exc:
            logger.warning("could not delete config.json: %s", exc)
    load(refresh=True)
