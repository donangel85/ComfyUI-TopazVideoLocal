# ComfyUI-TopazStudio

Topaz Video AI nodes for ComfyUI. Everything runs locally through your own Topaz Video
installation — no cloud, no API keys, no uploads.

## Requirements

- Windows
- A licensed, signed-in **Topaz Video** installation
- ComfyUI with `numpy` (already present in every standard install)

## Install

Clone or copy the package into ComfyUI's `custom_nodes` directory, or link it from
elsewhere with a junction (no admin rights needed):

```bash
mklink /J "F:\ComfyUI\custom_nodes\ComfyUI-TopazStudio" "D:\TopazLab-Studio\ComfyUI-TopazStudio"
```

Restart ComfyUI. Start with the **Topaz Diagnostics** node — it reports what was found
and what is missing, without running a workflow.

## Nodes

| Node | What it does |
|---|---|
| **Topaz Video Upscale** | IMAGE → IMAGE through `tvai_up`. Proteus, Rhea, Iris, Gaia, Nyx, Themis, Starlight Mini and the rest. |
| **Topaz Frame Interpolation** | IMAGE → IMAGE through `tvai_fi`. Apollo, Aion, Chronos. Returns a different frame count by design. |
| **Topaz Video Stabilize** | IMAGE → IMAGE through `tvai_cpe` + `tvai_stb`. Full-frame or auto-crop, rolling-shutter correction. |
| **Topaz Deinterlace** | Dione models, with field order. Deinterlaces and optionally upscales in one pass. |
| **Topaz Motion Deblur** | Themis. Resolution unchanged — Themis supports scale 1 only. |
| **Topaz Parameter Estimate** | Analyses the footage with `tvai_pe` and outputs the tuning Topaz would pick. |
| **Topaz Image Upscale** | Still images through `tvai_up`. Processes each picture independently by default, and supports the same multi-pass chain. |
| **Topaz Engine Settings** | Device, VRAM, transport, licence handling, verbose logging. Optional. |
| **Topaz Upscale Stage** | One pass of a multi-pass upscale. Chain several for Proteus → Rhea → … in a single run. Optional. |
| **Topaz Upscale Params** | Ready-made profiles, or manual control over preblur, noise, details, halo, blur, compression, grain, blend. Optional. |
| **Topaz Hyperion HDR Params** | SDR → HDR parameters for `hyp-1`. Optional. |
| **Topaz SAM2 Mask** | Segment-Anything-2 click expression for object-aware processing. Optional. |
| **Topaz Resolution** | Named output sizes with orientation and a divisibility constraint. Outputs plain INTs, so it drives other nodes too. Optional. |
| **Topaz Diagnostics** | Installation, codecs, models, licence and CLI-lock status. |

The main nodes work on their own; attach the settings nodes only when you need them.

## Choosing an output size

Both upscale nodes take `scale_mode: factor | target_size`. `factor` is an exact integer
multiple and the most predictable option. `target_size` accepts any resolution: Topaz
upscales far enough to cover it, and the result is fitted to the exact size you asked for.

**Topaz Resolution** exists so you do not have to type those numbers. Pick a named size,
an orientation, and — where it matters — a divisibility constraint:

```
Topaz Resolution ──▶ width  ──▶ target_width
                 └─▶ height ──▶ target_height
```

It outputs plain `INT`s rather than a private type, so the same node drives MiniMax-H3,
LTX2.5, an empty latent, or anything else that takes dimensions.

### Divisibility

Most latent video models only accept dimensions that are a multiple of some number,
because their encoder downsamples by that factor. MiniMax-H3 wants multiples of 32, which
is why Full HD there is **1920x1088**, not 1920x1080.

Set `divisible_by` and both edges are snapped for you. `rounding` decides which way:
`up` never returns less than you asked for, `down` never returns more, `nearest` keeps
the smallest difference. Snapping happens after the orientation is applied, so portrait
sizes satisfy the constraint too.

Note that two different sizes both get called 2K, so the list names them: **QHD 1440p**
is 2560x1440, **DCI 2K** is 2048x1080.

### fit, fill and stretch

When the target does not match the source aspect ratio, `fit_mode` decides what happens.
A 4:3 frame going to 640x360:

| Mode | Result |
|---|---|
| `fit` (default) | scaled to 480x360, black bars either side. Nothing is lost or distorted. |
| `fill` | scaled to 640x480, then top and bottom cropped away. Fills the frame, loses the edges. |
| `stretch` | squashed to 640x360. No bars, no crop, but the aspect ratio changes. |

Every mode ends at exactly the size requested — an IMAGE batch has to be one size.

**Topaz Upscale Stage** offers the same `scale_mode`, so an intermediate pass can be
pinned to a resolution before the next model sees it.

## Multi-pass upscaling

Topaz Video lets you stack enhancement passes, and so does this package. Feed one
**Topaz Upscale Stage** into the next through `previous_stage`, then connect the last one
to the `upscale_chain` input of **Topaz Video Upscale**:

```
Topaz Upscale Stage (Proteus, 2x)
  -> Topaz Upscale Stage (Rhea, 2x)      [previous_stage]
    -> Topaz Video Upscale (Proteus, 1x) [upscale_chain]
```

The stages run first, in order, and the Upscale node's own model runs last. Scales
multiply, so 2x then 2x gives 4x overall. **Topaz Image Upscale** takes the same
`upscale_chain` input, where it is arguably more useful still: repair on the first
pass with one profile, resolution on the second with another.

All passes happen inside **one** ffmpeg call as chained `tvai_up` filters, so the frames
never leave the process in between — no repeated model loading and no tensor round trip.
Wiring two Upscale nodes in series also works, but costs an extra process launch and
conversion each time.

Each stage takes its own `params`, so you can denoise hard on the first pass and sharpen
on the second. Scale factors are validated against the model before anything runs: Topaz
rejects e.g. `pnat-1` at 1x, and the node says so immediately rather than failing several
seconds into a render.

## Letting Topaz choose the parameters

**Topaz Parameter Estimate** runs `tvai_pe` over the batch and reports the tuning it would
pick for that specific material. The result plugs straight into the `params` input of any
upscale node, and a second output gives you the numbers to read:

```
Topaz parameter estimate — Parameter Estimation (prap-3)
11 frame(s) analysed, aggregated by median

  preblur       -0.3962   (range -0.4136 … -0.3699)
  noise          0.0460   (range +0.0174 … +0.0549)
  details        0.2143   (range +0.1994 … +0.2869)
  ...
```

This differs from the Upscale node's own `estimate` option in three ways: you see the
numbers, you can reuse one estimate across several passes instead of re-analysing each
time, and you can analyse a sample (`max_frames`) rather than the whole clip.

Aggregation defaults to **median**, so a cut or a single black frame does not drag the
whole clip's settings with it. The reported range tells you whether one setting really
fits the material: a wide spread means the footage changes character partway through.

## Profiles

**Topaz Upscale Params** starts with a `profile` dropdown. Leave it on `manual` and the
sliders apply as usual; pick anything else and that profile's values are used.
`profile_strength` scales a profile up or down — 0.5 for half the intervention, 0 to
disable its tuning entirely. In the browser, picking a profile also copies its values into
the sliders so you can adjust them — see below.

Three kinds of entry appear, and the prefix tells them apart:

- **`Topaz: …`** — read live from Topaz Video's own preset folder, authored by Topaz
  Labs. Their GUI stores values on a -100..100 scale; they are converted to the -1..1 the
  filter expects. Only presets that actually set tuning values are listed: most of Topaz's
  presets only pick a model and output settings, and would otherwise fill the dropdown
  with identical empty entries. Topaz also ships an old and a new copy of nearly every
  preset under the same name, so duplicates are collapsed to the newer file.
- **`My: …`** — presets you saved yourself. See below.
- **No prefix** — starting points shipped with this package, derived from what each
  parameter is documented to do. Useful defaults, not official Topaz values.

Whichever you pick, the resolved parameters are written to the log:

```
profile 'Compressed / web video' at strength 1 ->
  blur=0, compression=0.6, details=0.3, estimate=0, halo=0.1, noise=0.25, preblur=0
```

Topaz presets also log the model they were authored for.

### Seeing and adjusting a preset's values

Picking a profile in the browser **copies its numbers straight into the sliders**, so you
can see what the preset actually does and change any of it. `profile_strength` is applied
while copying, so what you end up looking at is what will run.

Alongside the dropdown sits `edit_preset_values`, which decides who wins:

| `edit_preset_values` | What runs |
|---|---|
| `preset as-is` (off) | The profile, exactly as authored. The sliders are ignored. |
| `sliders (edited)` (on) | The sliders. Your adjustments count. |

Picking a profile turns it **on** for you, because the sliders now hold that preset's
values and adjusting them is the point. Turn it off to go back to the untouched preset —
your slider values are kept, just not used, so you can flip between the two and compare.

Two buttons round it out:

- **Reload preset into sliders** — copies the selected profile in again. Useful after
  changing `profile_strength`, or to discard an experiment and start over.
- **Save sliders as preset** — stores the current values under a name you choose. It
  appears in the dropdown as `My: <name>` and behaves like any other profile, strength
  scaling included. Saving under an existing name overwrites it.

Saved presets live in `user_presets.json` beside the package and are git-ignored — they
are your machine's data. Other Upscale Params nodes already on the canvas offer a newly
saved entry after the next ComfyUI restart.

All of this comes from a small frontend extension in `web/`. Without it — running a
workflow through the API, for instance — `edit_preset_values` stays off and the `profile`
dropdown behaves exactly as it always has, applied on the server. Nothing here depends on
a browser being involved.

## What about audio?

Nothing is lost. These nodes are `IMAGE` → `IMAGE`, and a ComfyUI IMAGE batch has never
carried audio — it is just frames. Your audio travels its own path through the workflow
and is attached wherever you write the video, for example by the `AUDIO` input of
Video Helper Suite's *Video Combine*. Route the audio straight from your source node to
the save node and it arrives untouched, without a re-encode.

## How it works, and why

Topaz builds its FFmpeg with `--disable-decoder=h264 --disable-decoder=hevc`. The
software H.264 decoder is simply not there, so anything that hands Topaz an H.264 file
forces FFmpeg onto `h264_qsv`, `h264_amf` or `h264_cuvid`. On a machine without Intel
graphics, `h264_qsv` fails with `Error creating a MFX session: -9`.

This package sidesteps that entirely:

```
IMAGE tensor -> raw RGB24 -> ffmpeg stdin -> tvai_* -> raw file -> IMAGE tensor
```

There is no container and no input decoder, so there is no decoder to choose wrongly.
It also avoids two lossy H.264 generations in the middle of your workflow.

A few other behaviours worth knowing about, all established by testing against a real
installation:

- **Minimum four frames.** Topaz's temporal models crash with an access violation on
  fewer. Short batches are padded and trimmed back automatically.
- **`device` defaults to auto (`-2`).** An explicit `device=0` has been observed to fail
  with `Failed to configure output pad` on mixed NVIDIA/AMD systems.
- **The licence is checked once and cached** in `config.json`, keyed to the installation.
  A Topaz update or a path change triggers a re-check. A check that times out counts as
  *unknown*, never as *invalid*.
- **`stdout` is never logged.** Topaz prints an auth token there; the package strips
  anything resembling one from all output.

## Models

The dropdowns are built from Topaz's own JSON metadata, so new models appear on their
own. Models are shown as `Proteus (prob-4)` — readable name plus the short code that
actually goes to Topaz.

Models whose weights are not on disk are marked `[download required]`. Enable
`allow_model_download` in the Engine Settings node to let Topaz fetch them, or process
once in the Topaz app. This is off by default so processing stays entirely offline.

Upscale models are *temporal* — they look at neighbouring frames. **Topaz Image Upscale**
therefore defaults to processing each picture on its own, so unrelated photos in one batch
cannot bleed into each other. Switch it to `sequence` when the batch really is consecutive
video frames; that is considerably faster.

**Not available:** Astra, Starlight SLP-2.5 and Hyperion-2 run inside Topaz's
`neuroserver` runtime rather than through FFmpeg, and cannot be reached from outside the
Topaz application. They are hidden rather than offered and then failing.

## Topaz Photo and Topaz Gigapixel

Not supported, and not for lack of trying. Both CLIs are locked behind a Topaz
**enterprise** licence:

```
> gigapixel.exe --help
CLI access requires enterprise license.

> tpai.exe --cli --help
Topaz Photo CLI has been disabled.
```

Neither ships an FFmpeg-style interface, and their remaining integration points are
Photoshop/Lightroom/Capture One plugins that need the host application running. The
Diagnostics node reports the current lock status on your machine, so if Topaz ever
changes this you will see it.

## Troubleshooting

Run **Topaz Diagnostics** first. Then:

| Symptom | Cause |
|---|---|
| "No usable Topaz Video installation found" | Set `install_path` in Engine Settings. A folder only counts if its ffmpeg provides `tvai_up`. |
| "has no weights installed" | Enable `allow_model_download`, or run the model once in the Topaz app. |
| "Topaz reports a licence problem" | Open Topaz Video and sign in. |
| "batch is too short" | Fewer than four frames reached the node. |

Turn on `verbose` in Engine Settings to log the exact FFmpeg command for every call —
it can be pasted straight into a terminal to reproduce a failure.

## Development

```bash
python -m pytest
```

The tests cover the command builder, error classification, the model catalog, frame
conversion, the resolution arithmetic and the user-preset store. They need neither Topaz
nor ComfyUI: `topaz_studio` is deliberately free of ComfyUI imports.

Layout:

| Directory | Contents |
|---|---|
| `topaz_studio/` | Backend. Knows Topaz, knows nothing about ComfyUI, testable on its own. |
| `topaz_nodes/` | The ComfyUI layer. Thin: gather widget values, call the backend, turn a failure into a message worth reading. |
| `web/` | Frontend extension. Only the Upscale Params buttons — everything else works without it. |

## Licence

MIT — see [LICENSE](LICENSE). Credits and prior art: [NOTICE.md](NOTICE.md).

Not affiliated with Topaz Labs LLC.
