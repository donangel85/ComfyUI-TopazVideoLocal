"""Model catalog, read from Topaz's own JSON metadata.

Everything here comes from ``<ProgramData>\\Topaz Labs LLC\\Topaz Video\\models\\*.json``
rather than a hand-maintained list, so models Topaz adds appear on their own.

Two details are load-bearing and were established experimentally (see
``docs/topaz-local-interfaces.md``):

* The readable name lives in ``displayName``. The ``name`` key also exists but belongs to
  nested *parameter* objects, so a naive text search returns things like "Add Noise" for
  every model.
* ``modelType`` is the filter discriminator. Guessing from the short code prefix would
  break on the next model family Topaz ships.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .logging_util import get_logger

logger = get_logger()

# Filenames in the models directory that are configuration, not models.
_NON_MODEL_STEMS = {
    "benchmarks", "audio-codecs", "video-encoders",
    "model-recommendation-rules", "neuroserver", "proxy",
}

UPSCALE = "tvai_up"
INTERPOLATE = "tvai_fi"
ESTIMATE = "tvai_pe"
CAMERA_POSE = "tvai_cpe"
STABILIZE = "tvai_stb"

# Verified across the full local catalog.
_TYPE_TO_FILTER = {
    1: UPSCALE,
    2: INTERPOLATE,
    3: ESTIMATE,
    4: CAMERA_POSE,
    5: STABILIZE,
    # 8 = Starlight Mini sub-variants (slmdl-1, slmes-1, ...). Topaz picks these itself
    # via the parent model's modelSelector; invoking them directly is not supported.
}

# Fallback labels for entries whose JSON carries no displayName.
_NAME_FALLBACKS = {
    "ref": "Stabilization",
    "cpe": "Camera Pose Estimation",
    "ash": "Shot Boundary Detection",
    "shtf": "Shot Features",
    "nap": "Noise & Artifact Estimation",
    "prap": "Parameter Estimation",
}


@dataclass(frozen=True)
class TopazModel:
    short_code: str            # what goes into model=...
    display_name: str
    filter_name: str
    scales: tuple[int, ...]
    min_app_version: str = ""
    changes_fps: bool = False
    frame_count: int = 0       # frames the model needs as context, 0 = unknown
    max_frames: int = 0
    weights_present: bool = False

    @property
    def label(self) -> str:
        """What the dropdown shows: 'Proteus (prob-4)'.

        Section 10 of the handover document asked for exactly this — readable names, with
        the short code kept visible so existing workflows remain recognisable.
        """
        suffix = "" if self.weights_present else "  [download required]"
        return f"{self.display_name} ({self.short_code}){suffix}"

    def supports_scale(self, scale: int) -> bool:
        return not self.scales or scale in self.scales


def _clean_display_name(raw, short_code: str) -> str:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    family = short_code.split("-")[0]
    if family in _NAME_FALLBACKS:
        return _NAME_FALLBACKS[family]
    return short_code


def _collect_scales(data: dict) -> tuple[int, ...]:
    scales: set[int] = set()
    for backend in (data.get("backends") or {}).values():
        if not isinstance(backend, dict):
            continue
        for key in (backend.get("scales") or {}):
            try:
                scales.add(int(key))
            except (TypeError, ValueError):
                continue
    return tuple(sorted(scales))


def _weight_stems(model_dir: Path) -> set[str]:
    """Short codes that actually have weight files on disk.

    Weight files are named ``<family>-v<version>-...``, e.g. ``apo-v8-fp16-256x352-ox.tz3``
    belongs to model ``apo-8``. Matching on the family alone is not enough: with only
    ``apo-v8`` present, ``apo-5`` would look installed and then fail with error -22.

    Without weights tvai_up fails unless download is enabled, so this drives the
    '[download required]' marker.
    """
    stems: set[str] = set()
    try:
        entries = list(model_dir.iterdir())
    except OSError:
        return stems

    for path in entries:
        if not path.suffix.startswith(".tz"):
            continue
        match = re.match(r"([a-zA-Z]+)-v([0-9]+(?:\.[0-9]+)?)", path.name)
        if match:
            stems.add(f"{match.group(1).lower()}-{match.group(2)}")
    return stems


def _parse_one(path: Path, weight_stems: set[str]) -> TopazModel | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug("skipping unreadable model json %s: %s", path.name, exc)
        return None
    if not isinstance(data, dict):
        return None

    short_code = path.stem

    # Neuroserver models (Astra, Starlight SLP-2.5, Hyperion-2) run inside Topaz's own
    # obfuscated runtime and cannot be reached through the tvai_* filters at all.
    if data.get("isNeuroserverModel"):
        return None

    if data.get("enabled") == 0:
        return None

    filter_name = _TYPE_TO_FILTER.get(data.get("modelType"))
    if filter_name is None:
        return None

    # Meta-models (e.g. slm-1 "Starlight Mini") declare no backends and delegate through
    # modelSelector. Invoking one directly crashes Topaz with an access violation.
    backends = data.get("backends") or {}
    if not backends or "modelSelector" in data:
        logger.debug("skipping meta-model %s (no backends / modelSelector)", short_code)
        return None

    return TopazModel(
        short_code=short_code,
        display_name=_clean_display_name(data.get("displayName"), short_code),
        filter_name=filter_name,
        scales=_collect_scales(data),
        min_app_version=str(data.get("minAppVersion") or ""),
        changes_fps=bool(data.get("changesFPS")),
        frame_count=int(data.get("frameCount") or 0),
        max_frames=int(data.get("maxFrames") or 0),
        weights_present=short_code.lower() in weight_stems,
    )


@functools.lru_cache(maxsize=4)
def _load_catalog(model_dir_str: str, stamp: float) -> tuple[TopazModel, ...]:
    model_dir = Path(model_dir_str)
    weight_stems = _weight_stems(model_dir)
    models = []
    try:
        entries = sorted(model_dir.glob("*.json"))
    except OSError:
        entries = []
    for path in entries:
        if path.stem in _NON_MODEL_STEMS:
            continue
        model = _parse_one(path, weight_stems)
        if model:
            models.append(model)
    logger.debug("model catalog: %d usable entries from %s", len(models), model_dir)
    return tuple(models)


def _dir_stamp(model_dir: Path) -> float:
    try:
        return model_dir.stat().st_mtime
    except OSError:
        return 0.0


def load_catalog(model_dir: Path | str | None) -> tuple[TopazModel, ...]:
    if not model_dir:
        return ()
    model_dir = Path(model_dir)
    return _load_catalog(str(model_dir), _dir_stamp(model_dir))


def models_for(model_dir: Path | str | None, filter_name: str,
               *, installed_first: bool = True) -> list[TopazModel]:
    models = [m for m in load_catalog(model_dir) if m.filter_name == filter_name]
    if installed_first:
        models.sort(key=lambda m: (not m.weights_present, m.display_name.lower(),
                                   m.short_code))
    else:
        models.sort(key=lambda m: (m.display_name.lower(), m.short_code))
    return models


def labels_for(model_dir: Path | str | None, filter_name: str) -> list[str]:
    return [m.label for m in models_for(model_dir, filter_name)]


def resolve(model_dir: Path | str | None, value: str,
            filter_name: str | None = None) -> TopazModel | None:
    """Accept a dropdown label, a bare short code, or a legacy value.

    Workflows saved with the old node stored raw short codes like ``prob-4``; those keep
    working.
    """
    if not value:
        return None
    catalog = load_catalog(model_dir)
    if filter_name:
        catalog = tuple(m for m in catalog if m.filter_name == filter_name)

    for model in catalog:
        if model.label == value:
            return model

    match = re.search(r"\(([^)]+)\)", value)
    code = (match.group(1) if match else value).strip()
    for model in catalog:
        if model.short_code == code:
            return model
    return None


def clear_cache() -> None:
    _load_catalog.cache_clear()
