"""Parameter profiles for tvai_up.

Two sources, deliberately kept distinguishable:

* **Topaz's own presets**, read from ``<ProgramData>\\Topaz Labs LLC\\Topaz Video\\presets``.
  Authored by Topaz Labs, shown with a ``Topaz:`` prefix. Their GUI stores values on a
  -100..100 scale while the filter takes -1..1, so everything is divided by 100.
* **Purpose profiles** written for this package, shown without a prefix. These are
  informed starting points derived from what each parameter is documented to do — not
  official Topaz values. Say so in the UI rather than implying authority they lack.

Most of Topaz's shipped presets set no tuning at all; they only select a model and output
settings. Those are skipped here, since a dropdown full of identical all-zero entries
helps nobody.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass, field
from pathlib import Path

from .logging_util import get_logger

logger = get_logger()

MANUAL = "manual"

# Topaz GUI field -> tvai_up filter option. Verified against the filter's own help text:
#   preblur  "adjusts both the antialiasing and deblurring strength"  <- deblur
#   blur     "additional sharpening of the video"                     <- sharpen
_GUI_TO_FILTER = {
    "compress": "compression",
    "deblur": "preblur",
    "dehalo": "halo",
    "denoise": "noise",
    "detail": "details",
    "sharpen": "blur",
}

# Frames used for auto parameter estimation when a profile asks for it.
AUTO_ESTIMATE_FRAMES = 8


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    options: dict = field(default_factory=dict)
    estimate: int = 0
    suggested_model: str = ""
    source: str = "builtin"

    def resolve(self, strength: float = 1.0) -> dict:
        """Parameter dict for the filter, with every tuning value scaled by *strength*."""
        scaled = {}
        for key, value in self.options.items():
            if isinstance(value, (int, float)):
                scaled[key] = max(-1.0, min(1.0, float(value) * float(strength)))
            else:
                scaled[key] = value
        scaled["estimate"] = int(self.estimate)
        return scaled


# --- purpose profiles ---------------------------------------------------------------
# Starting points, not gospel. Every value is relative to what the model detects in the
# input, so 0 means "leave it alone" and 1 is maximum intervention.

_BUILTIN: tuple[Profile, ...] = (
    Profile(
        "Auto — let Topaz decide",
        "Topaz analyses the first frames and picks the tuning itself. The safest choice "
        "for unfamiliar material, and what most of Topaz's own presets do.",
        options={}, estimate=AUTO_ESTIMATE_FRAMES,
    ),
    Profile(
        "Pure upscale — clean source",
        "Resolution only, no correction. For sources that are already clean: renders, "
        "screen captures, well-lit modern footage.",
        options={"compression": 0.0, "noise": 0.0, "details": 0.0,
                 "halo": 0.0, "blur": 0.0, "preblur": 0.0},
    ),
    Profile(
        "AI-generated video",
        "For diffusion output, which tends to be soft and slightly over-smoothed but "
        "carries no sensor noise. Recovers texture and sharpens gently.",
        options={"details": 0.35, "blur": 0.15, "compression": 0.10,
                 "noise": 0.0, "halo": 0.0, "preblur": 0.0},
    ),
    Profile(
        "Compressed / web video",
        "For streaming and re-encoded sources: blockiness and mosquito noise are the "
        "main problem.",
        options={"compression": 0.60, "noise": 0.25, "details": 0.30,
                 "halo": 0.10, "blur": 0.0, "preblur": 0.0},
    ),
    Profile(
        "Noisy footage — high ISO",
        "Heavy denoise, with detail recovery to put back what the denoise removes.",
        options={"noise": 0.60, "details": 0.40, "compression": 0.15,
                 "halo": 0.0, "blur": 0.0, "preblur": 0.0},
    ),
    Profile(
        "Old film / archive",
        "Grain, softness and age. Loosely follows Topaz's own 'Film 4K' preset, which "
        "raises compression handling and leans on auto estimation.",
        options={"compression": 0.35, "noise": 0.40, "details": 0.50,
                 "blur": 0.20, "halo": 0.15, "preblur": 0.0},
    ),
    Profile(
        "Oversharpened source",
        "For material that already went through a sharpening pass: suppress ringing "
        "and halos, and back off the sharpening.",
        options={"halo": 0.60, "blur": -0.30, "preblur": 0.20,
                 "noise": 0.0, "details": 0.0, "compression": 0.0},
    ),
    Profile(
        "Aliased / CGI render",
        "For staircase edges and moire. Negative preblur is what the filter documents "
        "for aliasing artefacts.",
        options={"preblur": -0.50, "details": 0.20, "halo": 0.10,
                 "noise": 0.0, "blur": 0.0, "compression": 0.0},
    ),
    Profile(
        "Photo restoration",
        "For stills: scans, old photographs, damaged originals. Balanced correction "
        "across the board.",
        options={"compression": 0.30, "noise": 0.45, "details": 0.50,
                 "blur": 0.20, "halo": 0.20, "preblur": 0.0},
    ),
    Profile(
        "Photo — maximum detail",
        "For stills that are already sharp and clean, where the goal is resolution and "
        "texture rather than repair.",
        options={"details": 0.55, "blur": 0.25, "noise": 0.0,
                 "compression": 0.0, "halo": 0.05, "preblur": 0.0},
    ),
)


def _load_topaz_presets(presets_dir: Path) -> list[Profile]:
    """Read Topaz's shipped presets, newest file first, one entry per name.

    Topaz keeps an older and a newer copy of nearly every preset under different
    filenames but the same display name — "Film 4K L.json" and
    "Film Stock 4K Light.json", for instance. Duplicated names in a dropdown are
    indistinguishable and only the first would ever be selectable, so keep the most
    recently written file of each name and drop the rest.
    """
    profiles = []
    seen: set[str] = set()
    try:
        files = sorted(presets_dir.glob("*.json"),
                       key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return profiles

    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        enhance = ((data.get("settings") or {}).get("enhance")) or {}
        if not enhance or not enhance.get("active", True):
            continue

        options = {}
        for gui_key, filter_key in _GUI_TO_FILTER.items():
            raw = enhance.get(gui_key)
            if isinstance(raw, (int, float)) and raw:
                options[filter_key] = max(-1.0, min(1.0, float(raw) / 100.0))

        auto = bool(enhance.get("auto"))
        if not options and not auto:
            # Model/output-only preset — nothing to offer as a parameter profile.
            continue

        name = str(data.get("name") or path.stem)
        if name in seen or any(b.name == name for b in _BUILTIN):
            continue
        seen.add(name)

        profiles.append(Profile(
            name=name,
            description=str(data.get("description") or "").strip()
                        or "Preset shipped with Topaz Video.",
            options=options,
            estimate=AUTO_ESTIMATE_FRAMES if auto else 0,
            suggested_model=str(enhance.get("model") or ""),
            source="topaz",
        ))
    return profiles


def _load_user_presets() -> list[Profile]:
    """Presets the user saved. Never raises — see :mod:`user_profiles`."""
    from . import user_profiles

    return [
        Profile(
            name=entry["name"],
            description=entry.get("description") or "Saved on this machine.",
            options=dict(entry.get("options") or {}),
            estimate=int(entry.get("estimate") or 0),
            suggested_model=entry.get("suggested_model") or "",
            source="user",
        )
        for entry in user_profiles.load()
    ]


@functools.lru_cache(maxsize=4)
def _catalog(presets_dir_str: str, stamp: float, user_stamp: float) -> tuple[Profile, ...]:
    entries = list(_BUILTIN)
    if presets_dir_str:
        found = _load_topaz_presets(Path(presets_dir_str))
        logger.debug("loaded %d Topaz presets with tuning values", len(found))
        entries.extend(found)
    entries.extend(_load_user_presets())
    return tuple(entries)


def _stamp(presets_dir: Path | None) -> float:
    try:
        return presets_dir.stat().st_mtime if presets_dir else 0.0
    except OSError:
        return 0.0


def presets_dir_for(model_dir) -> Path | None:
    """Topaz keeps presets beside the models directory."""
    if not model_dir:
        return None
    candidate = Path(model_dir).parent / "presets"
    return candidate if candidate.is_dir() else None


def load(model_dir=None) -> tuple[Profile, ...]:
    from . import user_profiles

    presets = presets_dir_for(model_dir)
    # The user file's timestamp is part of the cache key, so a saved preset shows up
    # without waiting for the cache to be cleared.
    try:
        user_stamp = user_profiles.USER_PRESETS_PATH.stat().st_mtime
    except OSError:
        user_stamp = 0.0
    return _catalog(str(presets) if presets else "", _stamp(presets), user_stamp)


def label_for(profile: Profile) -> str:
    """Dropdown text for one profile, prefixed by where it came from."""
    from . import user_profiles

    if profile.source == "topaz":
        return f"Topaz: {profile.name}"
    if profile.source == "user":
        return f"{user_profiles.PREFIX}{profile.name}"
    return profile.name


def labels(model_dir=None) -> list[str]:
    """Dropdown entries: ``manual``, then purpose profiles, Topaz's own, then saved."""
    return [MANUAL] + [label_for(profile) for profile in load(model_dir)]


def resolve(label: str, model_dir=None) -> Profile | None:
    from . import user_profiles

    if not label or label == MANUAL:
        return None
    wanted = label
    for prefix in ("Topaz: ", user_profiles.PREFIX):
        if wanted.startswith(prefix):
            wanted = wanted[len(prefix):]
            break
    # Match on the full label first: a saved preset may legitimately carry the same bare
    # name as a built-in one, and the prefix is what tells them apart.
    for profile in load(model_dir):
        if label_for(profile) == label:
            return profile
    for profile in load(model_dir):
        if profile.name == wanted:
            return profile
    return None


def clear_cache() -> None:
    _catalog.cache_clear()
