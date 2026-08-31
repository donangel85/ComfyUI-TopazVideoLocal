"""Model catalog parsing, against fixtures shaped like Topaz's real JSON files."""

import json
import sys
from pathlib import Path

import pytest


from topaz_studio import models  # noqa: E402


def write_model(directory: Path, stem: str, data: dict):
    (directory / f"{stem}.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def model_dir(tmp_path):
    models.clear_cache()

    backends = {"onnx": {"scales": {"1": {}, "2": {}, "4": {}}},
                "tensorrt": {"scales": {"1": {}, "2": {}, "4": {}}}}

    # Upscale model with weights on disk.
    write_model(tmp_path, "prob-4", {
        "displayName": "Proteus", "shortName": "prob", "modelType": 1,
        "backends": backends, "minAppVersion": "2.3.0",
    })
    (tmp_path / "prob-v4-fp16-256x256-ox.tz3").write_bytes(b"weights")

    # Upscale model without weights.
    write_model(tmp_path, "rhea-1", {
        "displayName": "Rhea", "shortName": "rhea", "modelType": 1,
        "backends": backends,
    })

    # Frame interpolation.
    write_model(tmp_path, "apo-8", {
        "displayName": "Apollo", "shortName": "apo", "modelType": 2,
        "backends": {"onnx": {"scales": {"1": {}}}},
        "changesFPS": 1, "frameCount": 4,
    })
    (tmp_path / "apo-v8-fp16-256x256-ox.tz3").write_bytes(b"weights")

    # Neuroserver-only: must not appear at all.
    write_model(tmp_path, "astra", {
        "shortName": "Astra", "name": "Astra", "category": "Starlight",
        "isNeuroserverModel": True, "backends": {"neuroserver": {}},
    })

    # Meta-model: no backends, delegates via modelSelector. Invoking it crashes Topaz.
    write_model(tmp_path, "slm-1", {
        "displayName": "Starlight Mini", "modelType": 1,
        "backends": {}, "modelSelector": {"variants": ["slmes-1"]},
    })

    # Stabilization, with no displayName — needs the fallback label.
    write_model(tmp_path, "ref-2", {"modelType": 5, "backends": backends})

    # Configuration files that live in the same directory.
    write_model(tmp_path, "benchmarks", {"anything": 1})
    write_model(tmp_path, "video-encoders", {"anything": 1})

    yield tmp_path
    models.clear_cache()


def codes(entries):
    return {m.short_code for m in entries}


def test_upscale_models_found(model_dir):
    assert codes(models.models_for(model_dir, models.UPSCALE)) == {"prob-4", "rhea-1"}


def test_interpolation_models_found(model_dir):
    assert codes(models.models_for(model_dir, models.INTERPOLATE)) == {"apo-8"}


def test_neuroserver_models_are_hidden(model_dir):
    every = {m.short_code for m in models.load_catalog(model_dir)}
    assert "astra" not in every


def test_meta_models_are_hidden(model_dir):
    """slm-1 has no backends; calling it directly is an access violation."""
    every = {m.short_code for m in models.load_catalog(model_dir)}
    assert "slm-1" not in every


def test_config_files_are_not_treated_as_models(model_dir):
    every = {m.short_code for m in models.load_catalog(model_dir)}
    assert "benchmarks" not in every
    assert "video-encoders" not in every


def test_label_is_readable_and_keeps_the_short_code(model_dir):
    proteus = models.resolve(model_dir, "prob-4", models.UPSCALE)
    assert proteus.label == "Proteus (prob-4)"


def test_missing_weights_are_marked(model_dir):
    rhea = models.resolve(model_dir, "rhea-1", models.UPSCALE)
    assert rhea.weights_present is False
    assert "download required" in rhea.label


def test_installed_models_sort_first(model_dir):
    entries = models.models_for(model_dir, models.UPSCALE)
    assert entries[0].short_code == "prob-4"


def test_resolve_accepts_label_and_short_code(model_dir):
    assert models.resolve(model_dir, "Proteus (prob-4)").short_code == "prob-4"
    assert models.resolve(model_dir, "prob-4").short_code == "prob-4"
    assert models.resolve(model_dir, "Proteus (prob-4)  [download required]") is not None


def test_resolve_rejects_wrong_filter(model_dir):
    assert models.resolve(model_dir, "apo-8", models.UPSCALE) is None


def test_scales_are_read_from_backends(model_dir):
    proteus = models.resolve(model_dir, "prob-4", models.UPSCALE)
    assert proteus.scales == (1, 2, 4)
    assert proteus.supports_scale(2)
    assert not proteus.supports_scale(3)


def test_fallback_display_name(model_dir):
    ref = models.resolve(model_dir, "ref-2", models.STABILIZE)
    assert ref is not None
    assert ref.display_name == "Stabilization"


def test_interpolation_frame_count_is_read(model_dir):
    apollo = models.resolve(model_dir, "apo-8", models.INTERPOLATE)
    assert apollo.frame_count == 4
    assert apollo.changes_fps is True


def test_missing_directory_is_not_an_error():
    assert models.load_catalog(None) == ()
    assert models.models_for(None, models.UPSCALE) == []
