"""The shipped example workflows have to stay loadable.

A workflow file stores widget values as a plain array and ComfyUI maps them back **by
position**, so an example goes wrong the same way a saved workflow does: silently, until
somebody opens it and gets a validation error naming a widget they never touched. The
files are generated from the live definitions by ``research/make_examples.py``, but they
are also opened in ComfyUI and rearranged by hand, and a hand-edited file is exactly the
kind that drifts. Hence a check that ships with the package and runs in the normal suite.

What is checked, and why each one has bitten:

  widget count        Too few values means every widget after the gap silently keeps
                      its default; too many means a value lands on a widget that does
                      not exist.
  combo membership    ``Value not in list: grain_type`` is what a shifted array looks
                      like from the user's side.
  numeric range       ``Value 0.3 bigger than max of 0.1: prenoise`` likewise.
  link endpoints      A link into a slot the node does not have, or of the wrong type,
                      fails at load with a message pointing somewhere else.
  node membership     Examples may use this package and ComfyUI's own nodes, nothing
                      else. A third-party node's widget layout cannot be verified from
                      here, and an example carrying guessed values for one fails at
                      load in a way that reads as our bug.

Like ``test_widget_order.py`` this imports the node layer, which the rest of the suite
avoids. No ComfyUI is needed at import time, and the contract being checked is a ComfyUI
one, so this is the only place it can be checked.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
EXAMPLES = PACKAGE / "examples"

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"}

# ComfyUI's own nodes, plus the frontend-only ones. Anything outside this set and
# NODE_CLASS_MAPPINGS means an example grew a dependency on a third-party pack.
CORE_NODES = {
    "LoadImage", "SaveImage", "PreviewImage",
    "LoadVideo", "SaveVideo", "CreateVideo", "GetVideoComponents",
    # comfy_extras.nodes_preview_any, shown in the menu as "Preview as Text". The
    # examples use it to display the Diagnostics report on the canvas.
    "PreviewAny",
    "Note", "MarkdownNote", "Reroute", "PrimitiveNode",
}

# Inputs declared as "*" take any type. Comparing a link's type against one is a
# category error: the socket has no type to disagree with. Missing this made every
# example fail the moment a Diagnostics report was wired into a Preview as Text.
WILDCARD_TYPES = {"*", "ANY", "any"}

# What model_choices() returns when no Topaz installation is present. The catalogue is
# read from Topaz's own files, so on a machine without it every model dropdown holds
# this one entry and the values in the examples cannot be checked against it.
NO_INSTALL = "<no Topaz Video installation found>"


@pytest.fixture(scope="module")
def node_classes():
    spec = importlib.util.spec_from_file_location(
        "cts_examples_test", PACKAGE / "__init__.py",
        submodule_search_locations=[str(PACKAGE)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["cts_examples_test"] = module
    spec.loader.exec_module(module)
    return module.NODE_CLASS_MAPPINGS


def example_files():
    return sorted(EXAMPLES.glob("*.json"))


def widget_specs(node_class):
    """(name, declaration) for each widget, in the order ComfyUI creates them."""
    spec = node_class.INPUT_TYPES()
    out = []
    for section in ("required", "optional"):
        for name, declaration in (spec.get(section) or {}).items():
            kind = declaration[0]
            if isinstance(kind, (list, tuple)) or kind in WIDGET_TYPES:
                out.append((name, declaration))
    return out


def link_inputs(node_class):
    """(name, type, required) for each input that is a socket rather than a widget."""
    spec = node_class.INPUT_TYPES()
    out = []
    for section in ("required", "optional"):
        for name, declaration in (spec.get(section) or {}).items():
            kind = declaration[0]
            if not isinstance(kind, (list, tuple)) and kind not in WIDGET_TYPES:
                out.append((name, kind, section == "required"))
    return out


@pytest.fixture(scope="module")
def workflows():
    files = example_files()
    assert files, f"no example workflows found in {EXAMPLES}"
    return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in files}


def test_there_are_examples():
    assert example_files(), f"no example workflows in {EXAMPLES}"


@pytest.mark.parametrize("name", [p.name for p in example_files()])
def test_file_is_a_workflow(workflows, name):
    data = workflows[name]
    for key in ("nodes", "links"):
        assert key in data, f"{name}: no '{key}' key — this is not a workflow file"
    assert data["nodes"], f"{name}: no nodes"


@pytest.mark.parametrize("name", [p.name for p in example_files()])
def test_only_this_package_and_comfyui(workflows, name, node_classes):
    """No third-party nodes: their widget layout cannot be verified from here."""
    allowed = CORE_NODES | set(node_classes)
    used = {node["type"] for node in workflows[name]["nodes"]}
    assert used <= allowed, (
        f"{name}: uses {sorted(used - allowed)}, which this repository cannot check. "
        "Examples ship with this package plus ComfyUI's own nodes only.")


@pytest.mark.parametrize("name", [p.name for p in example_files()])
def test_widget_values_fit_the_nodes(workflows, name, node_classes):
    """Every value in range, in its combo, and in the right slot."""
    problems = []
    for node in workflows[name]["nodes"]:
        node_class = node_classes.get(node["type"])
        if node_class is None:
            continue  # a ComfyUI node; checked for membership above, not for values
        values = node.get("widgets_values") or []
        specs = widget_specs(node_class)
        where = f"{name}: {node['type']} (id {node.get('id')})"

        if len(values) < len(specs):
            problems.append(f"{where}: {len(values)} widget values, {len(specs)} "
                            "declared — later widgets silently keep their defaults")
            continue
        if len(values) > len(specs):
            problems.append(f"{where}: {len(values)} widget values, {len(specs)} "
                            "declared — a value lands on a widget that does not exist")
            continue

        for value, (widget, declaration) in zip(values, specs):
            kind = declaration[0]
            options = declaration[1] if len(declaration) > 1 else {}
            if isinstance(kind, (list, tuple)):
                if NO_INSTALL in kind:
                    continue  # dropdown comes from a Topaz install that is not here
                if value not in kind:
                    problems.append(f"{where}.{widget}: {value!r} is not one of "
                                    f"{list(kind)[:6]}{'...' if len(kind) > 6 else ''}")
            elif kind in ("INT", "FLOAT"):
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    problems.append(f"{where}.{widget}: {value!r} is not a number")
                    continue
                low, high = options.get("min"), options.get("max")
                if low is not None and value < low:
                    problems.append(f"{where}.{widget}: {value} below min {low}")
                if high is not None and value > high:
                    problems.append(f"{where}.{widget}: {value} above max {high}")
            elif kind == "BOOLEAN":
                if not isinstance(value, bool):
                    problems.append(f"{where}.{widget}: {value!r} is not a boolean")
            elif kind == "STRING":
                if not isinstance(value, str):
                    problems.append(f"{where}.{widget}: {value!r} is not a string")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("name", [p.name for p in example_files()])
def test_links_land_where_they_claim(workflows, name):
    """Both ends of every link exist and agree on the type being carried.

    **Checked from the input side, on purpose.** A workflow records a connection twice:
    as an entry in the top-level ``links`` array carrying a destination slot index, and
    as a ``link`` id on the destination node's own input. Those two can disagree, and in
    ComfyUI-saved files they routinely do: opening a workflow expands every widget into
    the inputs array, which shifts the real slot indices, while the link entries keep the
    index they were created with.

    ComfyUI believes the input side. Verified against the running frontend rather than
    reasoned about: a graph whose ``links`` entry pointed at slot 4 (a combo) while
    ``inputs[8].link`` pointed at ``target_width`` loaded with the connection on
    ``target_width``, and ``graphToPrompt`` sent ``target_width: ["1", 0]`` with the
    combo keeping its literal value.

    An earlier version of this test compared the ``links`` array's slot index against the
    inputs array and failed every example the first time somebody saved one from ComfyUI
    — which is exactly the wrong way round for a test whose job is to catch real
    breakage.
    """
    data = workflows[name]
    by_id = {node["id"]: node for node in data["nodes"]}
    links = {}
    problems = []

    for link in data["links"]:
        link_id, src_id, src_slot, _dst_id, _dst_slot, link_type = link[:6]
        if link_id in links:
            problems.append(f"{name}: duplicate link id {link_id}")
        links[link_id] = (src_id, src_slot, link_type)
        if src_id not in by_id:
            problems.append(f"{name}: link {link_id} comes from a node that is not here")
            continue
        outputs = by_id[src_id].get("outputs") or []
        if src_slot >= len(outputs):
            problems.append(f"{name}: link {link_id} leaves output slot {src_slot}, "
                            f"which {by_id[src_id]['type']} does not have")
        elif outputs[src_slot].get("type") != link_type:
            problems.append(f"{name}: link {link_id} says {link_type} but "
                            f"{by_id[src_id]['type']} output {src_slot} is "
                            f"{outputs[src_slot].get('type')}")

    for node in data["nodes"]:
        for index, slot in enumerate(node.get("inputs") or []):
            link_id = slot.get("link")
            if link_id is None:
                continue
            if link_id not in links:
                problems.append(f"{name}: {node['type']}.{slot.get('name')} is wired to "
                                f"link {link_id}, which the file does not define")
                continue
            _src_id, _src_slot, link_type = links[link_id]
            declared = slot.get("type")
            if declared not in WILDCARD_TYPES and declared != link_type:
                problems.append(f"{name}: {node['type']}.{slot.get('name')} "
                                f"(input {index}) is {declared} but link {link_id} "
                                f"carries {link_type}")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("name", [p.name for p in example_files()])
def test_required_inputs_are_connected(workflows, name, node_classes):
    """An unconnected required socket fails the prompt, not the load — worse, because
    it looks like a runtime problem."""
    problems = []
    for node in workflows[name]["nodes"]:
        node_class = node_classes.get(node["type"])
        if node_class is None:
            continue
        required = {n for n, _, is_required in link_inputs(node_class) if is_required}
        connected = {slot["name"] for slot in (node.get("inputs") or [])
                     if slot.get("link") is not None}
        for missing in sorted(required - connected):
            problems.append(f"{name}: {node['type']} (id {node.get('id')}) needs "
                            f"'{missing}' connected")
    assert not problems, "\n".join(problems)


def test_a_video_example_exists(workflows):
    """Video is what this pack is for. The image examples are the quick way in, so at
    least one graph has to show the real thing end to end."""
    video = {name: data for name, data in workflows.items()
             if any(node["type"] == "LoadVideo" for node in data["nodes"])}
    assert video, ("no example loads a video. Topaz Video AI is a video product; an "
                   "examples folder that only shows stills misrepresents the pack.")
    for name, data in video.items():
        types = {node["type"] for node in data["nodes"]}
        assert "SaveVideo" in types, f"{name}: loads a video but never saves one"
        assert "GetVideoComponents" in types, (
            f"{name}: a VIDEO has to be split into frames before a Topaz node sees it")


@pytest.mark.parametrize("name", [p.name for p in example_files()])
def test_every_example_carries_a_note(workflows, name):
    """The README is not what somebody has in front of them when they open a graph."""
    notes = [node for node in workflows[name]["nodes"]
             if node["type"] in ("Note", "MarkdownNote")]
    assert notes, f"{name}: no note on the canvas explaining what it shows"
    text = " ".join(str(node.get("widgets_values", [""])[0]) for node in notes)
    assert len(text) > 80, f"{name}: the note says almost nothing"
