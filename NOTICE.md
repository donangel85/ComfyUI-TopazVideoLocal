# Credits and prior art

This package is an independent implementation. No third-party source code has been
copied into it. The projects below were studied as technical references, and the people
who wrote them deserve credit for the ideas and for mapping out this territory first.

## Referenced, not copied

| Project | Author | Licence | How it was used |
|---|---|---|---|
| [ComfyUI-TopazVideoAI](https://github.com/sh570655308/ComfyUI-TopazVideoAI) | sh570655308 | **none stated** | Studied to understand the `tvai_up` / `tvai_fi` filter approach and how a ComfyUI node can drive Topaz's ffmpeg. |
| [ComfyUI-GigapixelAI](https://github.com/sh570655308/ComfyUI-GigapixelAI) | sh570655308 | **none stated** | Reviewed while assessing whether Gigapixel could be automated. |
| [ComfyUI-TopazGigapixelAI](https://github.com/opj161/ComfyUI-TopazGigapixelAI) | opj161 | **none stated** | Same. |
| [Comfy-Topaz](https://github.com/choey/Comfy-Topaz) | choey | MIT | Reviewed for its Topaz Photo CLI integration. |
| [Comfy-Topaz-Photo](https://github.com/leoleelxh/Comfy-Topaz-Photo) | leoleelxh | MIT | Same. |
| [topyaz](https://github.com/twardoch/topyaz) | Adam Twardoch | MIT | Reviewed for its separation of product handlers from execution, which informed the split between `topaz_video` and `topaz_nodes` here. |

**On the unlicensed projects:** a public repository without a licence file is
"all rights reserved" by default. Those three could be read but not borrowed from, so
every part of this package that overlaps with them was written from scratch against
Topaz's own documented filter interface.

Nothing above is affiliated with or endorsed by this project.

## Not used

| Project | Reason |
|---|---|
| [Gigapixel](https://github.com/TimNekk/Gigapixel) (Apache-2.0) | Drives the Topaz GUI with `pywinauto`. Deliberately out of scope. |
| [ComfyUI-Topaz-Upscaler](https://github.com/comrender/ComfyUI-Topaz-Upscaler) (MIT) | Uses the Topaz cloud API. This package processes locally only. |

## Topaz Labs

Topaz Video, Topaz Photo and Topaz Gigapixel are products of
[Topaz Labs LLC](https://www.topazlabs.com/). This project is not affiliated with,
endorsed by, or supported by Topaz Labs. You need your own licensed installation of
Topaz Video for these nodes to do anything.

## Dependencies

`numpy` (BSD-3-Clause). Everything else comes from the Python standard library or from
ComfyUI itself.
