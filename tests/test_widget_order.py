"""Widget order is a compatibility contract. New widgets may only be appended.

ComfyUI stores a node's widget values in a saved workflow as a plain array and maps them
back **by position**. Inserting a widget anywhere but the end therefore shifts every
later value in every workflow already saved. It surfaces as a validation error naming
widgets nobody touched:

    Failed to convert an input value to a FLOAT value: grain_size, default
    Value not in list: grain_type: 0 not in ['default', 'silver_rich', ...]

That is grain_size holding grain_type's old value and grain_type holding blend's, one
slot out. It happened for real: ``edit_preset_values`` went in at position 3 of
TopazUpscaleParams and ``scale_mode`` at position 2 of TopazUpscaleStage.

The baselines below are the widget order as published. **Only ever append to them.**
Reordering or inserting is what this file exists to prevent, so a failure here is not a
signal to edit the baseline to match — it is a signal that saved workflows will break.

These tests import the node layer, which the rest of the suite deliberately avoids (see
conftest.py). The layer needs no ComfyUI at import time, and the contract being checked
is exactly a ComfyUI one, so it can only be checked here.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]

# Input types that become widgets. Everything else is a link socket and carries no entry
# in widgets_values, so it does not affect the positions.
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"}

# Widget order as published, per node. Append only.
BASELINES = {
    "TopazStudioUpscaleParams": [
        "profile", "profile_strength",
        "preblur", "noise", "details", "halo", "blur", "compression",
        "prenoise", "grain", "grain_size", "grain_type", "blend",
        "color_correction", "auto_estimate_frames",
        # --- appended after the above shipped ---
        "edit_preset_values",
    ],
    "TopazStudioUpscaleStage": [
        "model", "scale_factor",
        # --- appended ---
        "scale_mode", "target_width", "target_height", "fit_mode",
    ],
    "TopazStudioUpscale": [
        "model", "scale_mode", "scale_factor", "fps",
        "target_width", "target_height",
        # --- appended ---
        "fit_mode",
    ],
    "TopazStudioImageUpscale": [
        "model", "scale_mode", "scale_factor", "batch_mode",
        "target_width", "target_height",
        # --- appended ---
        "fit_mode",
    ],
    # The one deliberate removal. A field_order widget sat between model and
    # scale_factor and did nothing at all: tvai_up documents no interlacing parameter,
    # the dictionary option swallows unknown keys in silence, and both settings measured
    # identical on genuinely interlaced material. A control that silently has no effect
    # sends anyone with stuttering output chasing the wrong thing, so it went. Taken
    # while the package was unpublished and the node had never run in a graph -- that
    # is the only reason a removal was acceptable. Append from here.
    "TopazStudioDeinterlace": [
        "model", "scale_factor", "fps",
    ],
}


@pytest.fixture(scope="module")
def node_classes():
    spec = importlib.util.spec_from_file_location(
        "cts_widget_order", PACKAGE / "__init__.py",
        submodule_search_locations=[str(PACKAGE)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["cts_widget_order"] = module
    spec.loader.exec_module(module)
    return module.NODE_CLASS_MAPPINGS


def widget_names(node_class) -> list[str]:
    """Widget names in the order ComfyUI creates them: required first, then optional."""
    spec = node_class.INPUT_TYPES()
    names = []
    for section in ("required", "optional"):
        for name, declaration in (spec.get(section) or {}).items():
            kind = declaration[0]
            # A list of choices is a combo widget; a bare custom type is a link socket.
            if isinstance(kind, (list, tuple)) or kind in WIDGET_TYPES:
                names.append(name)
    return names


@pytest.mark.parametrize("node_key", sorted(BASELINES))
def test_widget_order_matches_the_published_baseline(node_classes, node_key):
    assert widget_names(node_classes[node_key]) == BASELINES[node_key], (
        f"{node_key}: widget order changed. ComfyUI maps saved workflows onto this list "
        "by position, so anything but appending at the end shifts the values in every "
        "workflow already saved. Move the new widget to the end rather than editing the "
        "baseline."
    )


@pytest.mark.parametrize("node_key", sorted(BASELINES))
def test_every_widget_has_a_baseline_entry(node_classes, node_key):
    """A widget added without touching the baseline would slip through the test above
    only if it happened to land at the end. Naming them all keeps the record honest."""
    assert set(widget_names(node_classes[node_key])) == set(BASELINES[node_key])


@pytest.mark.parametrize("node_key", sorted(BASELINES))
def test_the_function_accepts_every_widget_by_keyword(node_classes, node_key):
    """ComfyUI passes widget values by keyword, so a rename that misses the signature
    fails at run time rather than at load time."""
    import inspect

    node_class = node_classes[node_key]
    signature = inspect.signature(getattr(node_class, node_class.FUNCTION))
    accepted = set(signature.parameters)
    missing = [n for n in widget_names(node_class) if n not in accepted]
    assert not missing, f"{node_key}: {missing} declared but not accepted by build()"


def test_optional_widgets_have_defaults_in_the_signature(node_classes):
    """An optional widget that ComfyUI omits must not make the call fail."""
    import inspect

    for node_key in BASELINES:
        node_class = node_classes[node_key]
        optional = (node_class.INPUT_TYPES().get("optional") or {})
        signature = inspect.signature(getattr(node_class, node_class.FUNCTION))
        for name in optional:
            parameter = signature.parameters.get(name)
            if parameter is None:
                continue
            assert parameter.default is not inspect.Parameter.empty, (
                f"{node_key}.{name} is optional but has no default"
            )
