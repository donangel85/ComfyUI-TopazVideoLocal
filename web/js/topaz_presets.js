// Preset buttons for the Topaz Upscale Params node.
//
// ComfyUI fixes a node's widget values when INPUT_TYPES is read, so Python cannot put a
// preset's numbers into the sliders by itself. This asks the server for them and writes
// them in, which is the only way to get values you can then actually adjust.
//
// Deliberately additive: the `profile` dropdown keeps working exactly as before, on the
// server, for anyone running a workflow through the API with no browser involved. The
// button is a convenience on top — it copies the numbers in and sets the dropdown back
// to `manual` so what you see in the sliders is what will run.

import { app } from "../../scripts/app.js";

const NODE = "TopazStudioUpscaleParams";
const PREFIX = "/topaz_studio";
const MANUAL = "manual";

// Must match SLIDER_KEYS/EXTRA_KEYS in server_routes.py and the widget names in
// TopazUpscaleParams.
const VALUE_WIDGETS = [
  "preblur", "noise", "details", "halo", "blur", "compression",
  "prenoise", "grain", "gsize", "blend",
];

let presetCache = null;

async function fetchPresets(strength) {
  const response = await fetch(`${PREFIX}/presets?strength=${encodeURIComponent(strength)}`);
  if (!response.ok) throw new Error(`server returned ${response.status}`);
  return await response.json();
}

function widget(node, name) {
  return node.widgets?.find((w) => w.name === name);
}

function widgetValue(node, name, fallback = 0) {
  const found = widget(node, name);
  return found ? found.value : fallback;
}

function setWidget(node, name, value) {
  const found = widget(node, name);
  if (!found) return false;
  found.value = value;
  // Some widget types keep a separate callback for side effects; call it so the graph
  // registers the change as if it had been typed.
  found.callback?.(value, app.canvas, node);
  return true;
}

function toast(text, kind = "info") {
  try {
    app.extensionManager?.toast?.add({
      severity: kind,
      summary: "Topaz Studio",
      detail: text,
      life: 4000,
    });
  } catch (_) {
    console.log(`[Topaz Studio] ${text}`);
  }
}

async function loadPresetIntoSliders(node) {
  const profileWidget = widget(node, "profile");
  if (!profileWidget) return;

  const label = profileWidget.value;
  if (!label || label === MANUAL) {
    toast("Pick a preset in 'profile' first, then load it.", "warn");
    return;
  }

  const strength = widgetValue(node, "profile_strength", 1.0);
  try {
    presetCache = await fetchPresets(strength);
  } catch (error) {
    toast(`Could not read the presets: ${error.message}`, "error");
    return;
  }

  const entry = presetCache.presets?.find((p) => p.label === label);
  if (!entry) {
    toast(`'${label}' is no longer in the preset list.`, "warn");
    return;
  }

  let applied = 0;
  for (const name of VALUE_WIDGETS) {
    if (name in entry.values && setWidget(node, name, entry.values[name])) applied++;
  }
  setWidget(node, "auto_estimate_frames", entry.estimate ?? 0);

  // Back to manual, so the sliders you are now looking at are the ones that will run.
  // Leaving the dropdown set would make the server apply the preset again and quietly
  // discard every edit made afterwards.
  setWidget(node, "profile", MANUAL);

  node.setDirtyCanvas(true, true);

  let message = `Loaded '${label}' into ${applied} slider${applied === 1 ? "" : "s"}`;
  if (strength !== 1.0) message += ` at strength ${strength}`;
  if (entry.estimate) {
    message += `. This preset asks Topaz to estimate the values from ${entry.estimate} `
      + "frames, so the sliders below are only a starting point.";
  }
  if (entry.suggested_model) message += ` Authored for model ${entry.suggested_model}.`;
  toast(message);
}

async function saveCurrentAsPreset(node) {
  const suggested = widgetValue(node, "profile", "") || "";
  const initial = suggested && suggested !== MANUAL ? `${suggested} (copy)` : "";
  const name = window.prompt("Save these values as a preset named:", initial);
  if (name === null) return;
  if (!name.trim()) {
    toast("A preset needs a name.", "warn");
    return;
  }

  const values = {};
  for (const key of VALUE_WIDGETS) {
    const found = widget(node, key);
    if (found) values[key] = found.value;
  }

  try {
    const response = await fetch(`${PREFIX}/presets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        values,
        estimate: widgetValue(node, "auto_estimate_frames", 0),
        description: "Saved from the Topaz Upscale Params node.",
      }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || `server returned ${response.status}`);

    presetCache = null;
    const profileWidget = widget(node, "profile");
    if (profileWidget && !profileWidget.options.values.includes(body.label)) {
      // Add it to this node's list right away. Other Params nodes already on the canvas
      // pick it up on the next ComfyUI restart, when INPUT_TYPES is read again.
      profileWidget.options.values.push(body.label);
    }
    toast(`Saved as '${body.label}'. It is in the profile list now.`);
  } catch (error) {
    toast(`Could not save: ${error.message}`, "error");
  }
}

app.registerExtension({
  name: "TopazStudio.Presets",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onCreated?.apply(this, arguments);

      this.addWidget("button", "Load preset into sliders", null, () => {
        loadPresetIntoSliders(this);
      });
      this.addWidget("button", "Save sliders as preset", null, () => {
        saveCurrentAsPreset(this);
      });

      return result;
    };
  },
});
