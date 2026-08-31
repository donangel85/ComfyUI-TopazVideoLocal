"""Parameter profiles: built-in ones, and Topaz's own presets."""

import json

import pytest

from topaz_studio import profiles


@pytest.fixture(autouse=True)
def clean_cache():
    profiles.clear_cache()
    yield
    profiles.clear_cache()


@pytest.fixture
def topaz_tree(tmp_path):
    """Mimics <ProgramData>/Topaz Video/{models,presets}."""
    models_dir = tmp_path / "models"
    presets_dir = tmp_path / "presets"
    models_dir.mkdir()
    presets_dir.mkdir()

    # Real shape, values taken from Topaz's shipped "Film 4K L" preset.
    (presets_dir / "Film 4K L.json").write_text(json.dumps({
        "author": "Topaz Labs", "name": "Film 4K L",
        "description": "Film look.",
        "settings": {"enhance": {
            "active": True, "auto": 1, "model": "prob-4",
            "compress": 25, "deblur": 0, "dehalo": 0,
            "denoise": -100, "detail": -100, "sharpen": 0,
        }},
    }), encoding="utf-8")

    # Model/output-only preset: nothing to tune, must be skipped.
    (presets_dir / "Upscale to 4K.json").write_text(json.dumps({
        "name": "Upscale to 4K",
        "settings": {"enhance": {
            "active": True, "auto": 0, "model": "prob-4",
            "compress": 0, "denoise": 0, "detail": 0, "sharpen": 0,
        }},
    }), encoding="utf-8")

    return models_dir


def test_manual_is_always_the_first_choice(topaz_tree):
    assert profiles.labels(topaz_tree)[0] == profiles.MANUAL


def test_manual_resolves_to_nothing(topaz_tree):
    assert profiles.resolve(profiles.MANUAL, topaz_tree) is None
    assert profiles.resolve("", topaz_tree) is None


def test_topaz_presets_are_prefixed(topaz_tree):
    assert "Topaz: Film 4K L" in profiles.labels(topaz_tree)


def test_builtin_profiles_are_not_prefixed(topaz_tree):
    labels = profiles.labels(topaz_tree)
    assert any(l.startswith("Auto") for l in labels)
    assert not any(l.startswith("Topaz: Auto") for l in labels)


def test_tuningless_presets_are_skipped(topaz_tree):
    """A dropdown full of identical all-zero entries helps nobody."""
    assert "Topaz: Upscale to 4K" not in profiles.labels(topaz_tree)


def test_topaz_gui_scale_is_converted(topaz_tree):
    """Topaz stores -100..100; the filter takes -1..1."""
    film = profiles.resolve("Topaz: Film 4K L", topaz_tree)
    resolved = film.resolve()
    assert resolved["compression"] == pytest.approx(0.25)
    assert resolved["noise"] == pytest.approx(-1.0)
    assert resolved["details"] == pytest.approx(-1.0)


def test_gui_field_names_map_to_filter_options(topaz_tree):
    film = profiles.resolve("Topaz: Film 4K L", topaz_tree)
    assert "compress" not in film.options
    assert "compression" in film.options


def test_auto_flag_enables_estimation(topaz_tree):
    film = profiles.resolve("Topaz: Film 4K L", topaz_tree)
    assert film.resolve()["estimate"] == profiles.AUTO_ESTIMATE_FRAMES


def test_suggested_model_is_kept(topaz_tree):
    assert profiles.resolve("Topaz: Film 4K L", topaz_tree).suggested_model == "prob-4"


def test_strength_scales_tuning_values(topaz_tree):
    film = profiles.resolve("Topaz: Film 4K L", topaz_tree)
    assert film.resolve(0.5)["compression"] == pytest.approx(0.125)
    assert film.resolve(0.0)["compression"] == pytest.approx(0.0)


def test_strength_cannot_push_values_out_of_range(topaz_tree):
    film = profiles.resolve("Topaz: Film 4K L", topaz_tree)
    resolved = film.resolve(2.0)
    assert resolved["noise"] >= -1.0
    assert all(-1.0 <= v <= 1.0 for v in resolved.values()
               if isinstance(v, float))


def test_strength_does_not_scale_the_estimate_frame_count(topaz_tree):
    film = profiles.resolve("Topaz: Film 4K L", topaz_tree)
    assert film.resolve(0.5)["estimate"] == profiles.AUTO_ESTIMATE_FRAMES


def test_builtin_profiles_stay_within_filter_range():
    for profile in profiles.load(None):
        for key, value in profile.resolve().items():
            if key == "estimate":
                continue
            assert -1.0 <= value <= 1.0, f"{profile.name}.{key} = {value}"


def test_builtins_available_without_any_topaz_install():
    assert len(profiles.load(None)) >= 8
    assert profiles.resolve("Pure upscale — clean source", None) is not None


def test_unknown_profile_resolves_to_none(topaz_tree):
    assert profiles.resolve("Topaz: Does Not Exist", topaz_tree) is None


def test_duplicate_preset_names_are_collapsed(tmp_path):
    """Topaz ships an old and a new copy of nearly every preset under the same name."""
    models_dir = tmp_path / "models"
    presets_dir = tmp_path / "presets"
    models_dir.mkdir()
    presets_dir.mkdir()

    payload = {
        "name": "Film 4K L",
        "settings": {"enhance": {"active": True, "auto": 1, "model": "prob-4",
                                 "compress": 25}},
    }
    (presets_dir / "Film 4K L.json").write_text(json.dumps(payload), encoding="utf-8")
    (presets_dir / "Film Stock 4K Light.json").write_text(json.dumps(payload),
                                                          encoding="utf-8")

    labels = profiles.labels(models_dir)
    assert labels.count("Topaz: Film 4K L") == 1


def test_a_preset_cannot_shadow_a_builtin(tmp_path):
    models_dir = tmp_path / "models"
    presets_dir = tmp_path / "presets"
    models_dir.mkdir()
    presets_dir.mkdir()
    (presets_dir / "clash.json").write_text(json.dumps({
        "name": "Photo restoration",
        "settings": {"enhance": {"active": True, "auto": 1, "compress": 10}},
    }), encoding="utf-8")

    labels = profiles.labels(models_dir)
    assert "Topaz: Photo restoration" not in labels
    assert labels.count("Photo restoration") == 1
