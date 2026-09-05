// Preset handling for the Topaz Upscale Params node.
//
// ComfyUI fixes a node's widget values when INPUT_TYPES is read, long before the graph
// runs, so Python cannot show a preset's numbers in the sliders by itself. Picking a
// profile here copies its resolved values into the sliders and switches the node to
// `edit_preset_values`, so what you see is what runs and you can adjust from there.
//
// Nothing depends on this file being loaded. Without it `edit_preset_values` stays off
// and the server applies the profile exactly as it always has, which is what an API
// caller with no browser gets.
//
// Note the import depth: this file is served from /extensions/<pack>/js/, so reaching
// /scripts/ takes three levels, not two.

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const NODE = "TopazVideoLocalUpscaleParams";
const MANUAL = "manual";

// Must match SLIDER_KEYS/EXTRA_KEYS in server_routes.py and the widget names in
// TopazUpscaleParams.
const VALUE_WIDGETS = [
  "preblur", "noise", "details", "halo", "blur", "compression",
  "prenoise", "grain", "gsize", "blend",
];

// gsize is the filter's name for it; the widget is spelled out.
const WIDGET_ALIASES = { gsize: "grain_size" };

function widget(node, name) {
  const target = WIDGET_ALIASES[name] || name;
  return node.widgets?.find((w) => w.name === target);
}

function widgetValue(node, name, fallback = 0) {
  return widget(node, name)?.value ?? fallback;
}

function setWidget(node, name, value) {
  const found = widget(node, name);
  if (!found) return false;
  // Hold to the widget's own limits. The server clamps too, but a widget that ends up
  // outside its range fails the entire prompt with a message pointing at a parameter
  // nobody touched -- "Value 0.3 bigger than max of 0.1: prenoise" -- so it is worth
  // catching on this side as well.
  if (typeof value === "number" && Number.isFinite(value)) {
    const { min, max } = found.options || {};
    if (typeof min === "number") value = Math.max(min, value);
    if (typeof max === "number") value = Math.min(max, value);
  }
  found.value = value;
  return true;
}

function toast(text, kind = "info") {
  try {
    app.extensionManager.toast.add({
      severity: kind,
      summary: "Topaz Video Local",
      detail: text,
      life: 6000,
    });
  } catch (_) {
    console.log(`[Topaz Video Local] ${text}`);
  }
}

async function fetchPresets(strength) {
  const response = await api.fetchApi(
    `/topaz_video_local/presets?strength=${encodeURIComponent(strength)}`);
  if (!response.ok) throw new Error(`server returned ${response.status}`);
  return await response.json();
}

/** Copy the selected profile's resolved values into the sliders. */
async function copyPresetIntoSliders(node, label, { quiet = false } = {}) {
  if (!label || label === MANUAL) {
    if (!quiet) toast("Pick a profile first — 'manual' has nothing to copy.", "warn");
    return;
  }

  const strength = widgetValue(node, "profile_strength", 1.0);
  let data;
  try {
    data = await fetchPresets(strength);
  } catch (error) {
    toast(`Could not read the presets: ${error.message}. `
      + "The sliders were left alone.", "error");
    return;
  }

  const entry = data.presets?.find((p) => p.label === label);
  if (!entry) {
    toast(`'${label}' is no longer in the preset list.`, "warn");
    return;
  }

  let applied = 0;
  for (const key of VALUE_WIDGETS) {
    if (key in entry.values && setWidget(node, key, entry.values[key])) applied++;
  }
  setWidget(node, "auto_estimate_frames", entry.estimate ?? 0);
  // The sliders now hold real numbers, so they are the ones that should run.
  setWidget(node, "edit_preset_values", true);

  node.setDirtyCanvas(true, true);

  let message = `Copied '${entry.label}' into ${applied} slider`
    + `${applied === 1 ? "" : "s"}`;
  if (Number(strength) !== 1) message += ` at strength ${strength}`;
  message += ". Adjust them freely — they are what will run.";
  if (entry.estimate) {
    message += ` This preset asks Topaz to estimate the values from ${entry.estimate}`
      + " frames, so the sliders are a starting point rather than the final answer.";
  }
  if (entry.suggested_model) {
    message += ` Authored for model ${entry.suggested_model}.`;
  }
  toast(message);
}

async function saveCurrentAsPreset(node) {
  const source = widgetValue(node, "profile", "");
  const initial = source && source !== MANUAL ? `${source} (my version)` : "";
  const name = window.prompt("Save the current slider values as a preset named:",
                             initial);
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
    const response = await api.fetchApi("/topaz_video_local/presets", {
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
    if (!response.ok) {
      throw new Error(body.error || `server returned ${response.status}`);
    }

    // Offer it in this node's dropdown straight away. Other Params nodes already on the
    // canvas pick it up when ComfyUI next reads INPUT_TYPES, i.e. after a restart.
    const profileWidget = widget(node, "profile");
    const choices = profileWidget?.options?.values;
    if (Array.isArray(choices) && !choices.includes(body.label)) {
      choices.push(body.label);
    }
    node.setDirtyCanvas(true, true);
    toast(`Saved as '${body.label}'. It is in the profile list now.`);
  } catch (error) {
    toast(`Could not save: ${error.message}`, "error");
  }
}

app.registerExtension({
  name: "TopazVideoLocal.Presets",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onCreated?.apply(this, arguments);
      const node = this;

      // Selecting a profile fills the sliders, so the values are visible and editable
      // rather than hidden behind the dropdown.
      const profileWidget = widget(node, "profile");
      if (profileWidget) {
        const original = profileWidget.callback;
        profileWidget.callback = function (value, ...rest) {
          const passthrough = original?.apply(this, [value, ...rest]);
          // Guard: setWidget below can re-enter this callback in some frontend
          // versions, and a loop here would hammer the server.
          if (!node.__topazBusy) {
            node.__topazBusy = true;
            Promise.resolve(copyPresetIntoSliders(node, value, { quiet: true }))
              .finally(() => { node.__topazBusy = false; });
          }
          return passthrough;
        };
      }

      const reload = node.addWidget("button", "Reload preset into sliders", null, () => {
        copyPresetIntoSliders(node, widgetValue(node, "profile", MANUAL));
      });
      const save = node.addWidget("button", "Save sliders as preset", null, () => {
        saveCurrentAsPreset(node);
      });
      // Buttons hold no state; keeping them out of widgets_values avoids shifting the
      // values ComfyUI maps back onto the Python-declared widgets.
      for (const button of [reload, save]) button.serialize = false;

      return result;
    };
  },
});
