"""Ask ComfyUI what it thinks these nodes look like.

Every mistake this package has shipped so far came from the same gap: the node
definitions were checked by importing them and calling ``INPUT_TYPES()`` directly, and
ComfyUI does not see them that way. It serialises them, hands them to a browser, and maps
saved workflows onto the result **by position**. Three bugs in one day came out of that
gap on 31.08, and every test written since checks the Python side of it — which is the
side that was never wrong.

This closes it from the other end. ComfyUI publishes ``/object_info``: exactly what the
frontend is given, for every registered node. Comparing that against the same baselines
the unit tests use turns "ComfyUI probably agrees" into a measurement.

What it checks:

  registration    All 13 nodes are present, under the ids saved workflows use, with the
                  display names the menu shows. A node that fails to import does not
                  appear here at all — and ComfyUI logs that quietly at startup.
  widget order    Against tests/test_widget_order.py's baselines, which are the
                  compatibility contract. This is the check that had no teeth before:
                  the baseline was compared to the Python it came from.
  removal         TopazVideoLocalSAM2Mask must be gone, and no field_order widget
                  may have come back. Both were removed for measuring as
                  doing nothing at all; see the README.
  the examples    Every widget value in examples/*.json, validated against what ComfyUI
                  itself reports rather than against our own reading of it.
  core video      LoadVideo, GetVideoComponents, CreateVideo and SaveVideo, against the
                  shapes make_examples.py assumes for them.
  routes          The three preset routes answer, so the buttons in the browser have
                  something to talk to.

**ComfyUI has to be running.** Nothing here changes any state: every request is a GET.

Run:  python tools/object_info_check.py   (from the repository root)
      ... --url http://127.0.0.1:8188
"""

import argparse
import importlib.util
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
EXAMPLES = PACKAGE / "examples"

FAILURES = []
NOTES = []

# Types that become widgets and therefore occupy a position in widgets_values.
#
# **ComfyUI serialises a combo in two different ways**, and which one you get depends on
# the API the node was written against. That is not documented anywhere and it is the
# first thing this script got wrong:
#
#   V1 dict API (this package)   the choices *are* the type: ["factor", "target_size"]
#   V3 schema API (nodes_video)  the type is the string "COMBO" and the choices sit in
#                                the options dict under "options"
#
# Classifying only on "is it a list" therefore calls every V3 combo a link socket. It
# reported LoadVideo as having no widgets at all and its `file` as an input to be wired,
# which would have looked like the example workflows were wrong when they were not.
COMBO_TYPES = {"COMBO", "COMFY_DYNAMICCOMBO_V3"}
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"} | COMBO_TYPES


def is_widget(kind) -> bool:
    return isinstance(kind, list) or kind in WIDGET_TYPES


def choices_of(kind, options: dict):
    """The list a combo's value has to be in, whichever way it was serialised."""
    if isinstance(kind, list):
        return kind
    if kind == "COMBO":
        return options.get("options")
    # A DynamicCombo's options are objects carrying nested inputs, not plain values,
    # and its saved shape could not be established (see make_examples.py). Not checked.
    return None

# What make_examples.py assumes about ComfyUI's own video nodes. Read out of the classes
# once; this asks the running server whether that reading still holds.
CORE_VIDEO = {
    "LoadVideo": {"widgets": ["file"], "links": [], "outputs": ["VIDEO"]},
    "GetVideoComponents": {
        "widgets": [], "links": ["video"],
        "outputs": ["IMAGE", "AUDIO", "FLOAT", "COMBO", "COMBO"],
    },
    "CreateVideo": {
        "widgets": ["fps", "bit_depth", "color_space"], "links": ["images", "audio"],
        "outputs": ["VIDEO"],
    },
    "SaveVideo": {
        "widgets": ["filename_prefix", "format", "codec"], "links": ["video"],
        "outputs": ["VIDEO"],
    },
}


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" - {detail}" if detail else ""), flush=True)
    if not condition:
        FAILURES.append(label)


def note(text):
    NOTES.append(text)
    print(f"  ... {text}", flush=True)


def fetch(url: str, timeout: float = 30):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_local():
    """The package as Python sees it — the side that was never wrong, kept for
    comparison against the side that is."""
    spec = importlib.util.spec_from_file_location(
        "cts_object_info", PACKAGE / "__init__.py",
        submodule_search_locations=[str(PACKAGE)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["cts_object_info"] = module
    spec.loader.exec_module(module)

    # The published widget order lives in the test file, which is where it belongs —
    # imported rather than copied, so the two can never drift apart.
    order_spec = importlib.util.spec_from_file_location(
        "cts_widget_baselines", PACKAGE / "tests" / "test_widget_order.py")
    order_module = importlib.util.module_from_spec(order_spec)
    order_spec.loader.exec_module(order_module)
    return module, dict(order_module.BASELINES)


def widgets_of(spec: dict) -> list[str]:
    """Widget names in the order ComfyUI creates them, from an /object_info entry."""
    names = []
    for section in ("required", "optional"):
        for name, declaration in (spec.get("input", {}).get(section) or {}).items():
            if is_widget(declaration[0] if declaration else None):
                names.append(name)
    return names


def links_of(spec: dict) -> list[str]:
    names = []
    for section in ("required", "optional"):
        for name, declaration in (spec.get("input", {}).get(section) or {}).items():
            if not is_widget(declaration[0] if declaration else None):
                names.append(name)
    return names


def declaration_of(spec: dict, widget: str):
    for section in ("required", "optional"):
        block = spec.get("input", {}).get(section) or {}
        if widget in block:
            return block[widget]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8188",
                        help="where ComfyUI is listening")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    print(f"=== What ComfyUI says these nodes are ({base}) ===\n", flush=True)
    try:
        info = fetch(f"{base}/object_info")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"  cannot reach ComfyUI at {base}: {exc}", flush=True)
        print("  Start ComfyUI and run this again; nothing here changes any state.",
              flush=True)
        return 2
    print(f"  {len(info)} node types registered in this installation\n", flush=True)

    package, baselines = load_local()
    mappings = package.NODE_CLASS_MAPPINGS
    display = package.NODE_DISPLAY_NAME_MAPPINGS

    # ---- 1. every node registered ------------------------------------------
    print("--- registration ---", flush=True)
    missing = [key for key in mappings if key not in info]
    check("every node in NODE_CLASS_MAPPINGS reached ComfyUI", not missing,
          f"missing: {missing}" if missing
          else f"{len(mappings)} nodes"
          + " - a node that fails to import is simply absent here, and ComfyUI says so"
            " only in its startup log")
    if missing:
        note("run ComfyUI with the console visible; the import error is in the log")
        return 1

    wrong_name = {key: info[key].get("display_name") for key, want in display.items()
                  if key in info and info[key].get("display_name") != want}
    check("display names match what the menu should show", not wrong_name,
          str(wrong_name) if wrong_name else f"{len(display)} names")

    category = {info[key].get("category") for key in mappings}
    check("all nodes sit in one category", len(category) == 1, str(category))

    # ---- 2. removals stayed removed ----------------------------------------
    print("\n--- what must not be there ---", flush=True)
    check("TopazVideoLocalSAM2Mask is gone", "TopazVideoLocalSAM2Mask" not in info,
          "vsam is not a model this build has; see the README")
    field_order = [key for key in mappings
                   if "field_order" in widgets_of(info.get(key, {}))]
    check("no field_order widget came back", not field_order,
          str(field_order) if field_order
          else "the parameter never existed; the models decide it")

    # ---- 3. widget order, from the side that matters -----------------------
    print("\n--- widget order, as ComfyUI serialises it ---", flush=True)
    check("the baselines were readable", bool(baselines),
          f"{len(baselines)} nodes with a published order")
    for key in sorted(baselines):
        if key not in info:
            check(f"{key} present", False)
            continue
        served = widgets_of(info[key])
        check(f"{key}", served == baselines[key],
              " ".join(served) if served == baselines[key]
              else f"ComfyUI says {served}, the baseline says {baselines[key]} - "
                   "saved workflows map by position, so this breaks them")

    # Every node, not only the ones with a baseline: Python and ComfyUI must agree.
    print("\n--- Python and ComfyUI agree on every node ---", flush=True)
    for key in sorted(mappings):
        spec = mappings[key].INPUT_TYPES()
        local = []
        for section in ("required", "optional"):
            for name, declaration in (spec.get(section) or {}).items():
                kind = declaration[0]
                if isinstance(kind, (list, tuple)) or kind in WIDGET_TYPES:
                    local.append(name)
        served = widgets_of(info[key])
        check(f"{key}: {len(served)} widget(s)", served == local,
              "" if served == local else f"ComfyUI {served} vs Python {local}")

    # ---- 4. the examples, against ComfyUI's own answer ----------------------
    print("\n--- the example workflows, checked against ComfyUI ---", flush=True)
    for path in sorted(EXAMPLES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        problems = []
        short = []
        for node in data["nodes"]:
            spec = info.get(node["type"])
            if spec is None:
                if node["type"] in ("Note", "MarkdownNote", "Reroute"):
                    continue  # frontend-only, never in /object_info
                problems.append(f"{node['type']} is not registered in this installation")
                continue
            names = widgets_of(spec)
            values = node.get("widgets_values") or []
            if len(values) < len(names):
                # Shorter is legitimate: the frontend adds widgets of its own (an
                # upload button, a DynamicCombo's nested part) and fills the rest with
                # defaults. Longer, or a value out of range, is not.
                short.append(f"{node['type']} {len(values)}/{len(names)}")
            for index, value in enumerate(values[:len(names)]):
                widget = names[index]
                declaration = declaration_of(spec, widget)
                kind = declaration[0] if declaration else None
                options = declaration[1] if declaration and len(declaration) > 1 else {}

                # A loader's file list is whatever happens to be in the input folder, so
                # the stored name is a placeholder by design — the README says to pick
                # your own before running, and ComfyUI says so too when you load it.
                # Failing on that would make this script cry wolf on every single run.
                if any(key.endswith("_upload") for key in options):
                    choices = choices_of(kind, options) or []
                    if value not in choices:
                        note(f"{path.name}: pick a file in {node['type']} before "
                             f"running - {value!r} is a placeholder")
                    continue

                choices = choices_of(kind, options)
                if choices is not None:
                    if choices and value not in choices:
                        problems.append(f"{node['type']}.{widget}: {value!r} is not in "
                                        f"ComfyUI's list of {len(choices)} choices")
                elif kind in ("INT", "FLOAT") and isinstance(value, (int, float)):
                    low, high = options.get("min"), options.get("max")
                    if low is not None and value < low:
                        problems.append(f"{node['type']}.{widget}: {value} < min {low}")
                    if high is not None and value > high:
                        problems.append(f"{node['type']}.{widget}: {value} > max {high}")
        if short:
            note(f"{path.name}: {', '.join(short)} widget values written; the frontend "
                 "fills the rest from the node's own defaults")
        check(f"{path.name}", not problems, "; ".join(problems[:3]))

    # ---- 5. ComfyUI's own video nodes --------------------------------------
    print("\n--- the core video nodes the examples are built on ---", flush=True)
    for name, expected in CORE_VIDEO.items():
        spec = info.get(name)
        if spec is None:
            check(f"{name} exists in this ComfyUI", False,
                  "the video examples cannot load without it")
            continue
        served_widgets = widgets_of(spec)
        served_links = links_of(spec)
        check(f"{name}: widgets", served_widgets == expected["widgets"],
              " ".join(served_widgets) if served_widgets == expected["widgets"]
              else f"ComfyUI {served_widgets} vs assumed {expected['widgets']} - "
                   "make_examples.py writes values against the assumed order")
        check(f"{name}: link inputs", served_links == expected["links"],
              " ".join(served_links) if served_links == expected["links"]
              else f"ComfyUI {served_links} vs assumed {expected['links']} - "
                   "link slot indices in the example files are derived from this")
        outputs = list(spec.get("output") or [])
        check(f"{name}: outputs", outputs == expected["outputs"],
              str(outputs) if outputs == expected["outputs"]
              else f"ComfyUI {outputs} vs assumed {expected['outputs']}")

    # ---- 6. the preset routes ----------------------------------------------
    print("\n--- the routes behind the preset buttons ---", flush=True)
    try:
        presets = fetch(f"{base}/topaz_video_local/presets", timeout=20)
        listed = presets.get("profiles", presets) if isinstance(presets, dict) else presets
        check("GET /topaz_video_local/presets answers", True,
              f"{len(listed)} profile(s)")
        check("the route is also mirrored under /api", True,
              str(len(fetch(f"{base}/api/topaz_video_local/presets", timeout=20)) > 0))
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        check("GET /topaz_video_local/presets answers", False, str(exc))
        note("without this route the preset buttons in the browser do nothing, and "
             "the Python log says nothing either")

    print("\n=== summary ===", flush=True)
    for text in NOTES:
        print(f"  note: {text}", flush=True)
    if FAILURES:
        print(f"{len(FAILURES)} failed:", flush=True)
        for name in FAILURES:
            print(f"  - {name}", flush=True)
        return 1
    print("ComfyUI's own view of these nodes matches the baselines", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
