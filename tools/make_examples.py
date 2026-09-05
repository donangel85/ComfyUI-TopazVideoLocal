"""Generate the example workflows in ComfyUI-TopazVideoLocal/examples/.

Written by a generator rather than by hand on purpose. A workflow file stores widget
values as a positional array, exactly like a saved workflow does, so a hand-written
example drifts the moment a node gains a widget — and drifts silently, since nothing
reads these files until somebody loads one and gets a validation error. Deriving them
from the live ``INPUT_TYPES`` makes that impossible: the count, the order and the
defaults all come from the node itself.

Third-party nodes are deliberately absent. Their signatures cannot be verified from here
without booting ComfyUI, and an example built on guessed widget values would be worse
than no example. Every workflow here uses this package plus ComfyUI's own nodes —
LoadImage, SaveImage, PreviewImage and, for the video examples, LoadVideo,
GetVideoComponents, CreateVideo and SaveVideo, whose schemas were read out of
comfy_extras/nodes_video.py.

**Hand-placed layout survives regeneration.** The files were opened in ComfyUI and moved
around by hand, and ComfyUI wrote them back in its own normalised form. Regenerating
therefore carries each node's position, size, title, colour and collapsed state over
from the file on disk, matched by id and type, along with the saved canvas offset. Only
values, links and node membership come from this script. Without that, running the
generator would silently undo somebody's afternoon.

Run:  python tools/make_examples.py   (from the repository root)
      ... --check    compare the files on disk against the live definitions, write
                     nothing, and exit non-zero if they disagree
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
EXAMPLES = PACKAGE / "examples"

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"}

# ComfyUI's own nodes, read out of its nodes.py and comfy_extras/nodes_video.py.
# Kept minimal: only what is needed to make every example loadable and runnable without
# a third-party pack.
#
# A note on the video four. They are declared with the newer schema API, where a node's
# widgets are whichever of its inputs are not link types, in declaration order. The
# entries below were not read by eye: each class's own INPUT_TYPES() was called with
# ComfyUI's interpreter and the result copied here.
#
#   LoadVideo           required file(COMBO)                       -> VIDEO
#   GetVideoComponents  required video(VIDEO)                      -> images, audio,
#                                                                     fps, bit_depth,
#                                                                     color_space
#   CreateVideo         required images(IMAGE), fps(FLOAT=30.0),
#                       optional audio(AUDIO), bit_depth('auto'),
#                                color_space('sRGB')               -> VIDEO
#   SaveVideo           required video(VIDEO),
#                                filename_prefix('video/ComfyUI'),
#                                format(COMFY_DYNAMICCOMBO_V3),
#                       optional codec(COMFY_DYNAMICCOMBO_V3)      -> video
#
# Only the leading widgets are written; the rest are left off the end for the frontend
# to fill with its defaults, which is what these examples want anyway and avoids
# guessing how a DynamicCombo serialises. That is safe in the direction that matters: a
# short widgets_values leaves later widgets at their defaults, while a value in the
# wrong slot corrupts them. The generated LoadImage proves it — it shipped one value
# where the node has two, loaded fine, and ComfyUI wrote the second one back.
CORE = {
    "LoadImage": {
        "widgets": [("image", "example.png")],
        "inputs": [],
        "outputs": [("IMAGE", "IMAGE"), ("MASK", "MASK")],
    },
    "SaveImage": {
        "widgets": [("filename_prefix", "TopazVideoLocal")],
        "inputs": [("images", "IMAGE", True)],
        "outputs": [],
    },
    "PreviewImage": {
        "widgets": [],
        "inputs": [("images", "IMAGE", True)],
        "outputs": [],
    },
    "LoadVideo": {
        "widgets": [("file", "example.mp4")],
        "inputs": [],
        "outputs": [("VIDEO", "VIDEO")],
    },
    "GetVideoComponents": {
        "widgets": [],
        "inputs": [("video", "VIDEO", True)],
        "outputs": [("images", "IMAGE"), ("audio", "AUDIO"), ("fps", "FLOAT"),
                    ("bit_depth", "COMBO"), ("color_space", "COMBO")],
    },
    "CreateVideo": {
        # fps only; bit_depth and color_space follow it and keep their defaults
        # ("auto" and "sRGB"), which is what these examples want anyway.
        "widgets": [("fps", 24.0)],
        "inputs": [("images", "IMAGE", True), ("audio", "AUDIO", False)],
        "outputs": [("VIDEO", "VIDEO")],
    },
    "SaveVideo": {
        # filename_prefix only. `format` and `codec` are COMFY_DYNAMICCOMBO_V3 — a combo
        # with further widgets nested inside the chosen option — and how the frontend
        # writes that into widgets_values cannot be read off the Python class. Left off
        # the end, so both keep their defaults, which is MP4/H.264.
        "widgets": [("filename_prefix", "video/TopazVideoLocal")],
        "inputs": [("video", "VIDEO", True)],
        "outputs": [("video", "VIDEO")],
    },
    # comfy_extras.nodes_preview_any, "Preview as Text" in the menu. Its input takes
    # any type at all, which is why it is declared "*" here.
    "PreviewAny": {
        "widgets": [],
        "inputs": [("source", "*", True)],
        "outputs": [("STRING", "STRING")],
    },
    # Frontend-only node: litegraph draws it, no Python class is involved, so it is
    # present in every installation and cannot fail to load.
    "MarkdownNote": {
        "widgets": [("text", "")],
        "inputs": [],
        "outputs": [],
    },
}

# Sockets declared "*" accept anything, so there is no type for a link to disagree with.
WILDCARD_TYPES = {"*", "ANY", "any"}

# Every example says this, in the workflow itself rather than only in the README —
# the README is not what somebody has in front of them when they open a graph.
# The same opening on every canvas: what this pack is, and the three things worth knowing
# before the first run. It is repeated rather than referenced because a note is read by
# whoever opened *this* graph, and they have no reason to go looking at another one.
PACK_HEADER = """# ComfyUI-TopazVideoLocal

Drives **your own installed Topaz Video AI** through its ffmpeg filters. Nothing is
uploaded, no API key, no credits. A licensed local Topaz Video installation is required.

### Before the first run

1. Run the **Topaz Diagnostics** node once. It reports the installation, the models it
   found and the licence status, without running a workflow.
2. **Pick your own file in the loader.** The stored filename is a placeholder.
3. Missing models are downloaded only if you allow it — **Topaz Engine Settings** →
   `allow_model_download`, off by default so processing stays offline.

### If something goes wrong

Turn on `verbose` in **Topaz Engine Settings**. Every ffmpeg command then lands in the
ComfyUI console, ready to paste into a terminal.
"""

VIDEO_NOTE = PACK_HEADER + """
---

### Video is the main job here

Topaz Video AI is a **video** product, and so is this pack. This example starts from
`Load Image` only because a still is the quickest thing to try.

**To run it on video, change the two ends — nothing in between:**

| Replace | With |
|---|---|
| `Load Image` | `Load Video` → `Get Video Components` |
| `Save Image` | `Create Video` → `Save Video` |

Every Topaz node takes a plain IMAGE batch and does not care where the frames came from.
Three wires are easy to miss:

- **`fps`** from `Get Video Components` into the Topaz node — the motion models use it.
- **`fps`** into `Create Video`, or the clip plays at the wrong speed.
- **`audio`** straight across. An IMAGE batch carries no sound, so it goes *around* the
  Topaz node and is reattached at the end, untouched.

`07_video_upscale.json` is that graph already built."""


def load_package():
    spec = importlib.util.spec_from_file_location(
        "cts_examples", PACKAGE / "__init__.py",
        submodule_search_locations=[str(PACKAGE)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["cts_examples"] = module
    spec.loader.exec_module(module)
    return module


class Definitions:
    """Node shapes, from the live class for our nodes and from CORE for ComfyUI's."""

    def __init__(self, mappings):
        self.mappings = mappings

    def shape(self, node_type: str) -> dict:
        if node_type in CORE:
            return CORE[node_type]
        node_class = self.mappings[node_type]
        spec = node_class.INPUT_TYPES()
        widgets, inputs = [], []
        for section in ("required", "optional"):
            for name, declaration in (spec.get(section) or {}).items():
                kind = declaration[0]
                options = declaration[1] if len(declaration) > 1 else {}
                if isinstance(kind, (list, tuple)):
                    default = options.get("default")
                    if default is None or default not in kind:
                        default = kind[0] if kind else None
                    widgets.append((name, default))
                elif kind in WIDGET_TYPES:
                    widgets.append((name, options.get("default")))
                else:
                    inputs.append((name, kind, section == "required"))
        names = getattr(node_class, "RETURN_NAMES", None) or node_class.RETURN_TYPES
        outputs = list(zip(names, node_class.RETURN_TYPES))
        return {"widgets": widgets, "inputs": inputs, "outputs": outputs}


class Workflow:
    def __init__(self, definitions: Definitions, title: str, note: str):
        self.defs = definitions
        self.title = title
        self.note = note
        self.nodes = {}
        self.order = []
        self.links = []
        self._next_link = 1

    def add_note(self, key: str, text: str, pos, size=(560, 420)):
        """A MarkdownNote on the canvas.

        Always added last, so the executable nodes keep the ids they already have in
        the files on disk and the layout carried over still matches.
        """
        self.add(key, "MarkdownNote", pos, {"text": text})
        node = self.nodes[key]
        node["size"] = list(size)
        node["color"] = "#432"
        node["bgcolor"] = "#653"
        return key

    def add(self, key: str, node_type: str, pos, overrides=None, title=None):
        shape = self.defs.shape(node_type)
        values = []
        for name, default in shape["widgets"]:
            value = (overrides or {}).get(name, default)
            values.append(value)
        unknown = set(overrides or {}) - {n for n, _ in shape["widgets"]}
        if unknown:
            raise KeyError(f"{node_type}: no such widget(s): {sorted(unknown)}")

        node_id = len(self.nodes) + 1
        self.nodes[key] = {
            "id": node_id,
            "type": node_type,
            "pos": list(pos),
            "size": [330, 26 + 24 * max(len(values), 1) + 26 * len(shape["inputs"])],
            "flags": {},
            "order": len(self.order),
            "mode": 0,
            "inputs": [{"name": n, "type": t, "link": None}
                       for n, t, _ in shape["inputs"]],
            "outputs": [{"name": n, "type": t, "links": [], "slot_index": i}
                        for i, (n, t) in enumerate(shape["outputs"])],
            "properties": {"Node name for S&R": node_type},
            "widgets_values": values,
        }
        if title:
            self.nodes[key]["title"] = title
        self.order.append(key)
        return key

    def connect(self, from_key: str, from_slot, to_key: str, to_input: str,
                as_widget: bool = False):
        source = self.nodes[from_key]
        target = self.nodes[to_key]

        if isinstance(from_slot, str):
            index = next(i for i, o in enumerate(source["outputs"])
                         if o["name"] == from_slot)
        else:
            index = from_slot
        link_type = source["outputs"][index]["type"]

        slot = next((i for i, s in enumerate(target["inputs"])
                     if s["name"] == to_input), None)
        if slot is None:
            if not as_widget:
                raise KeyError(f"{target['type']}: no input named {to_input}")
            # A widget being driven by a link. ComfyUI represents that as an input slot
            # carrying a `widget` marker; the value stays in widgets_values as a
            # fallback for when the link is removed.
            target["inputs"].append({
                "name": to_input, "type": link_type, "link": None,
                "widget": {"name": to_input},
            })
            slot = len(target["inputs"]) - 1

        link_id = self._next_link
        self._next_link += 1
        source["outputs"][index]["links"].append(link_id)
        target["inputs"][slot]["link"] = link_id
        self.links.append([link_id, source["id"], index, target["id"], slot, link_type])

    def to_json(self) -> dict:
        nodes = [self.nodes[key] for key in self.order]
        return {
            "id": self.title.lower().replace(" ", "-"),
            "revision": 0,
            "last_node_id": len(nodes),
            "last_link_id": self._next_link - 1,
            "nodes": nodes,
            "links": self.links,
            "groups": [
                {
                    "id": 1,
                    "title": self.note,
                    "bounding": [-20, -80, 1500, 60],
                    "color": "#3f789e",
                    "font_size": 20,
                    "flags": {},
                },
                # The diagnostics pair sits in its own box above the graph, so it reads
                # as a first-run check rather than part of the pipeline.
                {
                    "id": 2,
                    "title": "Before the first run",
                    "bounding": [-20, -560, 920, 360],
                    "color": "#3f789e",
                    "font_size": 20,
                    "flags": {},
                },
            ],
            "config": {},
            "extra": {"ds": {"scale": 0.85, "offset": [120, 200]}},
            "version": 0.4,
        }


# --- the workflows ------------------------------------------------------------------

def build_all(defs: Definitions) -> dict:
    built = {}

    # 1 -------------------------------------------------------------------------
    w = Workflow(defs, "01 basic upscale",
                 "Simplest case: 2x with Proteus. Start here.")
    w.add("load", "LoadImage", (0, 0))
    w.add("up", "TopazVideoLocalImageUpscale", (420, 0),
          {"scale_mode": "factor", "scale_factor": 2})
    w.add("save", "SaveImage", (840, 0), {"filename_prefix": "topaz/upscaled"})
    w.connect("load", "IMAGE", "up", "images")
    w.connect("up", 0, "save", "images")
    built["01_basic_upscale"] = w

    # 2 -------------------------------------------------------------------------
    w = Workflow(defs, "02 output resolution",
                 "Named output size. fit keeps the aspect ratio and pads; "
                 "try fill and stretch to compare.")
    w.add("load", "LoadImage", (0, 0))
    w.add("res", "TopazVideoLocalResolution", (420, 0),
          {"preset": "Full HD 1080p (1920x1080)", "orientation": "landscape",
           "divisible_by": 1, "rounding": "up"})
    w.add("up", "TopazVideoLocalImageUpscale", (840, 0),
          {"scale_mode": "target_size", "fit_mode": "fit"})
    w.add("save", "SaveImage", (1260, 0), {"filename_prefix": "topaz/1080p"})
    w.connect("load", "IMAGE", "up", "images")
    w.connect("res", "width", "up", "target_width", as_widget=True)
    w.connect("res", "height", "up", "target_height", as_widget=True)
    w.connect("up", 0, "save", "images")
    built["02_output_resolution"] = w

    # 3 -------------------------------------------------------------------------
    w = Workflow(defs, "03 divisible by 32",
                 "For latent video models: MiniMax-H3 needs multiples of 32, so "
                 "Full HD is 1920x1088 here, not 1920x1080.")
    w.add("load", "LoadImage", (0, 0))
    w.add("res", "TopazVideoLocalResolution", (420, 0),
          {"preset": "Full HD 1080p (1920x1080)", "orientation": "landscape",
           "divisible_by": 32, "rounding": "up"},
          title="Topaz Resolution (1920x1088)")
    w.add("up", "TopazVideoLocalImageUpscale", (840, 0),
          {"scale_mode": "target_size", "fit_mode": "fit"})
    w.add("save", "SaveImage", (1260, 0), {"filename_prefix": "topaz/for_minimax"})
    w.connect("load", "IMAGE", "up", "images")
    w.connect("res", "width", "up", "target_width", as_widget=True)
    w.connect("res", "height", "up", "target_height", as_widget=True)
    w.connect("up", 0, "save", "images")
    built["03_divisible_by_32"] = w

    # 4 -------------------------------------------------------------------------
    w = Workflow(defs, "04 multi pass chain",
                 "Two models in one ffmpeg call: repair first, resolution second. "
                 "The frames never leave the process in between.")
    w.add("load", "LoadImage", (0, 0))
    w.add("p1", "TopazVideoLocalUpscaleParams", (420, -260),
          {"profile": "Compressed / web video"}, title="Params: repair pass")
    w.add("stage", "TopazVideoLocalUpscaleStage", (420, 120),
          {"scale_mode": "factor", "scale_factor": 2}, title="Stage 1: repair")
    w.add("p2", "TopazVideoLocalUpscaleParams", (840, -260),
          {"profile": "Pure upscale — clean source"}, title="Params: detail pass")
    w.add("up", "TopazVideoLocalImageUpscale", (860, 120),
          {"scale_mode": "factor", "scale_factor": 2}, title="Stage 2: detail")
    w.add("save", "SaveImage", (1280, 120), {"filename_prefix": "topaz/chained_4x"})
    w.connect("load", "IMAGE", "up", "images")
    w.connect("p1", 0, "stage", "params")
    w.connect("stage", 0, "up", "upscale_chain")
    w.connect("p2", 0, "up", "params")
    w.connect("up", 0, "save", "images")
    built["04_multi_pass_chain"] = w

    # 5 -------------------------------------------------------------------------
    w = Workflow(defs, "05 presets and tuning",
                 "Pick a profile: its values land in the sliders and "
                 "edit_preset_values switches on, so you can adjust from there.")
    w.add("load", "LoadImage", (0, 0))
    w.add("params", "TopazVideoLocalUpscaleParams", (420, -200),
          {"profile": "AI-generated video", "profile_strength": 1.0})
    w.add("engine", "TopazVideoLocalEngineSettings", (420, 320), {"verbose": True})
    w.add("up", "TopazVideoLocalImageUpscale", (860, 0),
          {"scale_mode": "factor", "scale_factor": 2})
    w.add("save", "SaveImage", (1280, 0), {"filename_prefix": "topaz/tuned"})
    w.connect("load", "IMAGE", "up", "images")
    w.connect("params", 0, "up", "params")
    w.connect("engine", 0, "up", "engine")
    w.connect("up", 0, "save", "images")
    built["05_presets_and_tuning"] = w

    # 6 -------------------------------------------------------------------------
    w = Workflow(defs, "06 restore",
                 "Repair passes. Deinterlace has no field-order control on purpose: "
                 "the Dione models decide that themselves.")
    w.add("load", "LoadImage", (0, 0))
    w.add("deint", "TopazVideoLocalDeinterlace", (420, -280), {"scale_factor": 1})
    w.add("deblur", "TopazVideoLocalMotionDeblur", (420, 60))
    w.add("stab", "TopazVideoLocalStabilize", (420, 380),
          {"mode": "auto_crop", "smoothness": 6.0})
    w.add("pv1", "PreviewImage", (860, -280), title="Deinterlaced")
    w.add("pv2", "PreviewImage", (860, 60), title="Deblurred")
    w.add("pv3", "PreviewImage", (860, 380), title="Stabilized")
    w.connect("load", "IMAGE", "deint", "images")
    w.connect("load", "IMAGE", "deblur", "images")
    w.connect("load", "IMAGE", "stab", "images")
    w.connect("deint", 0, "pv1", "images")
    w.connect("deblur", 0, "pv2", "images")
    w.connect("stab", 0, "pv3", "images")
    built["06_restore"] = w

    # --- video ------------------------------------------------------------------
    # These are what the pack is actually for. The image examples above are the same
    # graphs with a quicker thing to load, which is why every one of them carries a note
    # pointing here.

    # 7 -------------------------------------------------------------------------
    w = Workflow(defs, "07 video upscale",
                 "The main case: a whole clip through Topaz, audio carried around the "
                 "outside and put back at the end.")
    w.add("load", "LoadVideo", (0, 0))
    w.add("parts", "GetVideoComponents", (380, 0))
    w.add("params", "TopazVideoLocalUpscaleParams", (760, -300),
          {"profile": "AI-generated video"}, title="Params: pick a preset here")
    w.add("up", "TopazVideoLocalUpscale", (760, 60),
          {"scale_mode": "factor", "scale_factor": 2})
    w.add("make", "CreateVideo", (1180, 60))
    w.add("save", "SaveVideo", (1560, 60), {"filename_prefix": "video/topaz_2x"})
    w.connect("load", 0, "parts", "video")
    w.connect("parts", "images", "up", "images")
    # The clip's own frame rate, rather than a number typed twice. tvai_fi and the
    # motion models read fps, and Create Video has to be handed the same one or the
    # result plays at the wrong speed.
    w.connect("parts", "fps", "up", "fps", as_widget=True)
    w.connect("params", 0, "up", "params")
    w.connect("up", 0, "make", "images")
    w.connect("parts", "fps", "make", "fps", as_widget=True)
    # Audio goes around the Topaz node, not through it: an IMAGE batch carries no
    # sound, so it is picked up before and reattached after.
    w.connect("parts", "audio", "make", "audio")
    w.connect("make", 0, "save", "video")
    built["07_video_upscale"] = w

    # 8 -------------------------------------------------------------------------
    w = Workflow(defs, "08 video interpolate",
                 "24 to 48 fps. output_fps drives Create Video, so the clip keeps its "
                 "running time instead of playing at double speed.")
    w.add("load", "LoadVideo", (0, 0))
    w.add("parts", "GetVideoComponents", (380, 0))
    w.add("interp", "TopazVideoLocalInterpolate", (760, 0),
          {"mode": "target_fps", "target_fps": 48.0})
    w.add("make", "CreateVideo", (1180, 0))
    w.add("save", "SaveVideo", (1560, 0), {"filename_prefix": "video/topaz_48fps"})
    w.connect("load", 0, "parts", "video")
    w.connect("parts", "images", "interp", "images")
    w.connect("parts", "fps", "interp", "input_fps", as_widget=True)
    w.connect("interp", "images", "make", "images")
    # output_fps, not the input rate: the node returns the rate its own output is at,
    # which is the whole reason it has a second output.
    w.connect("interp", "output_fps", "make", "fps", as_widget=True)
    w.connect("parts", "audio", "make", "audio")
    w.connect("make", 0, "save", "video")
    built["08_video_interpolate"] = w

    # 9 -------------------------------------------------------------------------
    w = Workflow(defs, "09 video restore chain",
                 "Deinterlace, then stabilise, then enlarge - in that order, and only "
                 "the passes the footage actually needs.")
    w.add("load", "LoadVideo", (0, 0))
    w.add("parts", "GetVideoComponents", (380, 0))
    w.add("deint", "TopazVideoLocalDeinterlace", (760, 0), {"scale_factor": 1})
    w.add("stab", "TopazVideoLocalStabilize", (1140, 0),
          {"mode": "auto_crop", "smoothness": 6.0})
    w.add("up", "TopazVideoLocalUpscale", (1520, 0),
          {"scale_mode": "factor", "scale_factor": 2})
    w.add("make", "CreateVideo", (1900, 0))
    w.add("save", "SaveVideo", (2280, 0), {"filename_prefix": "video/topaz_restored"})
    w.connect("load", 0, "parts", "video")
    w.connect("parts", "images", "deint", "images")
    w.connect("parts", "fps", "deint", "fps", as_widget=True)
    w.connect("deint", 0, "stab", "images")
    w.connect("parts", "fps", "stab", "fps", as_widget=True)
    w.connect("stab", 0, "up", "images")
    w.connect("parts", "fps", "up", "fps", as_widget=True)
    w.connect("up", 0, "make", "images")
    w.connect("parts", "fps", "make", "fps", as_widget=True)
    w.connect("parts", "audio", "make", "audio")
    w.connect("make", 0, "save", "video")
    built["09_video_restore_chain"] = w

    # --- notes and the first-run check, last of all ------------------------------
    # Appended after every executable node so the pipeline nodes keep the ids they
    # already have in the files on disk; the layout carried over on regeneration is
    # matched on those ids first.
    for name, workflow in built.items():
        workflow.add_note("note", NOTES.get(name, VIDEO_NOTE), (-620, 0))

        # Topaz Diagnostics wired into Preview as Text, in its own group above the
        # graph. It answers the first question anybody has -- is Topaz found, are the
        # models there, is the licence good -- without running the pipeline, and it
        # reports rather than processes, so it costs nothing to leave in place.
        workflow.add("diag", "TopazVideoLocalDiagnostics", (0, -460),
                     {"check_license": False, "refresh": True})
        workflow.add("diag_view", "PreviewAny", (330, -470))
        workflow.nodes["diag_view"]["size"] = [558, 260]
        workflow.connect("diag", "report", "diag_view", "source")

    return built


# Per-file notes. Anything not listed gets VIDEO_NOTE, which is the point that needed
# making: this is a video pack, and the still-image examples are only the quick way in.
NOTES = {
    "06_restore": VIDEO_NOTE + """

---

**Deinterlace has no field-order switch**, on purpose. `tvai_up` documents no such
parameter, and its `parameters` option is a dictionary that swallows unknown keys
without a word — a switch was there once and measurably did nothing. The Dione models
work it out themselves, in both directions.

**Motion deblur is a repair pass, not a sharpener.** Measured on real footage: it gives
back about a fifth of what a real motion blur destroys, and costs roughly 8% of the
gradient energy when run on a picture that was sharp already. Use it where there is blur
to remove.""",

    "07_video_upscale": PACK_HEADER + """
---

### The graph this pack was built for

```
Load Video -> Get Video Components -> Topaz Video Upscale -> Create Video -> Save Video
                     |  fps ------------------^                  ^  ^
                     |  audio -------------------------------------  |
                     +--fps ----------------------------------------+
```

**To change what it does, change the preset** in *Topaz Upscale Params* — that is the
one knob most work needs. Picking a profile copies its values into the sliders and
switches `edit_preset_values` on, so you can adjust from there; switch it off to compare
against the untouched preset.

**Three wires are easy to miss:**

- `fps` into the Topaz node. The motion models use it. Wiring it from the clip beats
  typing a number that then disagrees with the source.
- `fps` into *Create Video*, or the result plays at the wrong speed.
- `audio` straight from *Get Video Components* into *Create Video*. An IMAGE batch
  carries no sound, so it goes around the Topaz node rather than through it.

**Memory.** The whole clip is decoded into an IMAGE batch before anything runs. At 1080p
a few hundred frames is already several gigabytes, and the 2x output is four times that
again. Cut long clips into pieces, or work at a lower resolution and enlarge last.""",

    "08_video_interpolate": PACK_HEADER + """
---

### Frame rate up, running time unchanged

*Topaz Frame Interpolation* has a second output, **`output_fps`**. Wire that into
*Create Video*, not the original rate — otherwise twice as many frames go out at the old
rate and the clip plays at half speed.

The frame count is not the round number you expect. At factor *k* it comes back as
**N x k - (k-1)**: interpolation makes the frames *between* the ones it was given, and
there is no gap after the last one. Measured on apo-8, from 24 frames:

| Target | Frames out |
|---|---|
| 2x (48 fps) | 47 |
| 3x (72 fps) | 70 |
| 4x (96 fps) | 93 |

`slowmo` mode is the other way round: the rate stays put and the clip gets longer. Wire
the **input** fps into *Create Video* for that, and be aware the audio no longer matches
the picture — pull it off *Create Video* and stretch it separately, or leave it out.

Measured on real footage: 24 frames at 24 fps came back as 47 at 48 fps, and the
frame-to-frame difference dropped from 0.083 to 0.050 — the motion really is spread
across twice the frames, not padded with duplicates.""",

    "09_video_restore_chain": PACK_HEADER + """
---

### Order matters, and so does leaving passes out

**Deinterlace, then stabilise, then enlarge.** Each pass wants the one before it done:
combing confuses motion estimation, and enlarging first means everything after it works
on four times the pixels for no gain.

**Run only the passes the footage needs.** Every one of these is a model rebuilding the
picture, and a rebuild is never free. Measured on real, already-sharp frames, motion
deblur alone costs about 8% of the gradient energy. Deinterlace on progressive footage
and stabilisation on a locked-off shot are the same kind of waste.

Bypass a node you do not need (**Ctrl+B**) rather than deleting it, and the graph stays
readable.

**Stabilisation resamples back to the input size.** `auto_crop` cuts into the picture by
however much the camera actually moved — 320x240 came back as 312x232 on a gentle shake
and 252x188 on a strong one — so the node scales the result back to the size it was
handed. An IMAGE batch has to be one size throughout.""",
}


# --- validation ---------------------------------------------------------------------

def validate(name: str, data: dict, defs: Definitions) -> list[str]:
    """Catch the mistakes that only show up when somebody loads the file."""
    problems = []
    by_id = {n["id"]: n for n in data["nodes"]}

    for node in data["nodes"]:
        shape = defs.shape(node["type"])
        expected = len(shape["widgets"])
        actual = len(node["widgets_values"])
        if expected != actual:
            problems.append(
                f"{name}: {node['type']} has {actual} widget values, node declares "
                f"{expected}")
        for index, (widget_name, _) in enumerate(shape["widgets"]):
            value = node["widgets_values"][index]
            declared = shape["widgets"][index]
            if value is None and declared[1] is not None:
                problems.append(f"{name}: {node['type']}.{widget_name} is null")

    seen = set()
    for link in data["links"]:
        link_id, src_id, src_slot, dst_id, dst_slot, link_type = link
        if link_id in seen:
            problems.append(f"{name}: duplicate link id {link_id}")
        seen.add(link_id)
        if src_id not in by_id or dst_id not in by_id:
            problems.append(f"{name}: link {link_id} points at a missing node")
            continue
        source, target = by_id[src_id], by_id[dst_id]
        if src_slot >= len(source["outputs"]):
            problems.append(f"{name}: link {link_id} leaves a slot "
                            f"{source['type']} does not have")
        elif source["outputs"][src_slot]["type"] != link_type:
            problems.append(f"{name}: link {link_id} type {link_type} does not match "
                            f"{source['type']} output "
                            f"{source['outputs'][src_slot]['type']}")
        if dst_slot >= len(target["inputs"]):
            problems.append(f"{name}: link {link_id} enters a slot "
                            f"{target['type']} does not have")
        elif (target["inputs"][dst_slot]["type"] not in WILDCARD_TYPES
                and target["inputs"][dst_slot]["type"] != link_type):
            problems.append(f"{name}: link {link_id} type {link_type} does not match "
                            f"{target['type']} input "
                            f"{target['inputs'][dst_slot]['type']}")

    # Only required link inputs. An optional one left open is the normal case -- that
    # is what optional means -- and flagging it would bury the real problems.
    for node in data["nodes"]:
        required = {n for n, _, is_required in defs.shape(node["type"])["inputs"]
                    if is_required}
        for slot in node["inputs"]:
            if (slot["link"] is None and "widget" not in slot
                    and slot["name"] in required):
                problems.append(
                    f"{name}: {node['type']}.{slot['name']} is required but unconnected")
    return problems


# --- keeping hand-placed layout -----------------------------------------------------

# What a person changes by dragging a node about, as opposed to what this script
# decides. Everything here is carried over from the file already on disk.
LAYOUT_KEYS = ("pos", "size", "title", "color", "bgcolor", "flags", "order")


def carry_layout(data: dict, path: Path) -> int:
    """Move the on-disk layout onto a freshly generated workflow.

    The examples were opened in ComfyUI, arranged by hand and saved back. Values and
    wiring have to come from the live node definitions or they drift, but position and
    size are somebody's work and regenerating must not throw them away. Nodes are
    matched by id **and** type together: an id that now holds a different node is a
    different node, and giving it the old one's box would be worse than placing it
    fresh.
    """
    if not path.exists():
        return 0
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0

    previous = {(n.get("id"), n.get("type")): n for n in existing.get("nodes", [])}

    # Second chance, by type alone. Nodes added in ComfyUI get whatever id the frontend
    # hands out, so a node this script emits third may sit on the file's id 7 -- the
    # Diagnostics pair came back as 5/6 in one example and 7/6 in the next. Where a type
    # occurs exactly once on each side there is no ambiguity about which is which, and
    # matching on it keeps somebody's arrangement instead of resetting those two boxes.
    def unique_by_type(nodes):
        seen = {}
        for node in nodes:
            seen.setdefault(node.get("type"), []).append(node)
        return {kind: found[0] for kind, found in seen.items() if len(found) == 1}

    old_unique = unique_by_type(existing.get("nodes", []))
    new_unique = unique_by_type(data["nodes"])

    carried = 0
    for node in data["nodes"]:
        old = previous.get((node["id"], node["type"]))
        if old is None and node is new_unique.get(node["type"]):
            old = old_unique.get(node["type"])
        if old is None:
            continue
        for key in LAYOUT_KEYS:
            if key in old:
                node[key] = old[key]
        carried += 1

    # The canvas view, and the group box somebody may have resized. The group's title
    # still comes from this script — it is the description, not layout.
    if existing.get("extra"):
        data["extra"] = existing["extra"]
    old_groups = existing.get("groups") or []
    if old_groups and data.get("groups"):
        for index, group in enumerate(data["groups"]):
            if index < len(old_groups) and "bounding" in old_groups[index]:
                group["bounding"] = old_groups[index]["bounding"]
    return carried


def differences(name: str, generated: dict, path: Path) -> list[str]:
    """What a file on disk says that the live definitions no longer do.

    Layout is ignored on purpose — moving a node is not drift. What matters is the node
    set, the widget values and the wiring, which are exactly the things that break
    silently when a node changes.
    """
    if not path.exists():
        return [f"{name}: not written yet"]
    try:
        on_disk = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"{name}: unreadable ({exc})"]

    found = []

    # Node ids are not stable across a save: a node added in ComfyUI takes whatever id
    # the frontend hands out, so the same Diagnostics node came back as id 5 in one
    # example and 7 in the next. Comparing ids would report a difference that means
    # nothing. What matters is which node types are present and how many of each.
    def by_type(nodes):
        grouped = {}
        for node in nodes:
            grouped.setdefault(node["type"], []).append(node)
        return grouped

    here = by_type(on_disk.get("nodes", []))
    there = by_type(generated["nodes"])
    for kind in sorted(set(there) | set(here)):
        wanted, got = len(there.get(kind, [])), len(here.get(kind, []))
        if wanted > got:
            found.append(f"{name}: {kind} appears {got}x in the file, "
                         f"{wanted}x generated")
        elif got > wanted:
            found.append(f"{name}: {kind} appears {got}x in the file, "
                         f"{wanted}x generated - an extra one was added by hand")

    for kind in sorted(set(there) & set(here)):
        # Within one type, pair them up in document order. Every example has at most one
        # of each type that carries values worth checking.
        for want_node, got_node in zip(there[kind], here[kind]):
            want = want_node.get("widgets_values") or []
            got = got_node.get("widgets_values") or []
            # ComfyUI appends the values of widgets the frontend adds by itself, such as
            # LoadImage's upload button, so a longer list on disk is normal. A shorter
            # one, or a differing value in the range this script writes, is not.
            if len(got) < len(want):
                found.append(f"{name}: {kind} has {len(got)} widget values, "
                             f"{len(want)} expected")
                continue
            for index, value in enumerate(want):
                if got[index] != value:
                    found.append(f"{name}: {kind} widget {index} is "
                                 f"{got[index]!r}, generated {value!r}")

    def topology(data):
        """Connections as (source type, output name) -> (target type, input name).

        By **name**, not slot index. ComfyUI expands every widget into the inputs array
        when it saves, which shifts the indices, and it leaves the ``links`` array
        holding whichever index the link was created with. Comparing indices would
        report a difference on every file the moment somebody saves one from ComfyUI,
        and there would be no real difference to find. The input side is what ComfyUI
        actually reads (verified against the running frontend), so that is what this
        reads too.
        """
        by_id = {n["id"]: n for n in data["nodes"]}
        source_of = {}
        for link in data.get("links", []):
            link_id, src, slot, _dst, _dst_slot, kind = link[:6]
            node = by_id.get(src)
            if node is None:
                continue
            outputs = node.get("outputs") or []
            port = outputs[slot].get("name") if slot < len(outputs) else f"#{slot}"
            source_of[link_id] = (node["type"], port, kind)

        edges = set()
        for node in data["nodes"]:
            for slot in node.get("inputs") or []:
                origin = source_of.get(slot.get("link"))
                if origin is not None:
                    edges.add((origin[0], origin[1], node["type"],
                               slot.get("name"), origin[2]))
        return edges

    missing = topology(generated) - topology(on_disk)
    extra = topology(on_disk) - topology(generated)
    for edge in sorted(missing, key=str):
        found.append(f"{name}: {edge[0]}.{edge[1]} -> {edge[2]}.{edge[3]} "
                     f"({edge[4]}) is missing from the file")
    for edge in sorted(extra, key=str):
        found.append(f"{name}: {edge[0]}.{edge[1]} -> {edge[2]}.{edge[3]} "
                     f"({edge[4]}) is in the file but not generated")
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="compare the files on disk against the live definitions "
                             "and write nothing")
    args = parser.parse_args()

    pkg = load_package()
    defs = Definitions(pkg.NODE_CLASS_MAPPINGS)
    EXAMPLES.mkdir(parents=True, exist_ok=True)

    built = build_all(defs)
    problems = []
    for name, workflow in built.items():
        data = workflow.to_json()
        problems.extend(validate(name, data, defs))
        path = EXAMPLES / f"{name}.json"

        if args.check:
            found = differences(name, data, path)
            problems.extend(found)
            summary = "ok" if not found else f"{len(found)} difference(s)"
            print(f"  {path.name:32s} {summary}")
            continue

        carried = carry_layout(data, path)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        node_types = sorted({n["type"] for n in data["nodes"]})
        print(f"  {path.name:32s} {len(data['nodes'])} nodes, "
              f"{len(data['links'])} links, {carried} kept their place")
        print(f"      {', '.join(node_types)}")

    print()
    if problems:
        print(f"{len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    if args.check:
        print(f"{len(built)} workflows on disk agree with the live node definitions")
    else:
        print(f"{len(built)} workflows written to {EXAMPLES}, all consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
