"""HTTP routes backing the node's preset buttons.

ComfyUI fixes a node's widget values when ``INPUT_TYPES`` is read, long before the graph
runs, so Python alone cannot answer "put this preset's numbers into the sliders". The
browser has to ask for them, and that needs a route to ask.

Registration is best-effort by design. Outside ComfyUI — the unit tests, the integration
scripts — there is no server to register with, and that must not stop the nodes from
importing.
"""

from __future__ import annotations

from ..topaz_studio import parameters, profiles, user_profiles
from ..topaz_studio.logging_util import get_logger

from .common import model_dir_or_none

logger = get_logger()

PREFIX = "/topaz_studio"

# The six tuning sliders, in the order Topaz's own parameter list uses. The frontend
# maps these onto widgets by name, so they have to match the widget names in
# TopazUpscaleParams exactly.
SLIDER_KEYS = parameters.TUNING
EXTRA_KEYS = tuple(k for k in parameters.RANGES if k not in SLIDER_KEYS)


def _profile_payload(profile, strength: float = 1.0) -> dict:
    """One profile as the frontend needs it: resolved numbers, ready for the widgets.

    Clamped again here even though Profile.resolve already does it. This is the last
    point before a number becomes a widget value, and a widget that refuses its own
    contents fails the whole prompt with a message pointing at a parameter nobody
    touched: ``Value 0.3 bigger than max of 0.1: prenoise``.
    """
    resolved = profile.resolve(strength)
    values = {key: parameters.clamp(key, resolved.get(key, 0.0)) for key in SLIDER_KEYS}
    values.update({key: parameters.clamp(key, resolved.get(key, 0.0))
                   for key in EXTRA_KEYS if key in resolved})
    return {
        "label": profiles.label_for(profile),
        "name": profile.name,
        "source": profile.source,
        "description": profile.description,
        "suggested_model": profile.suggested_model,
        # 0 means "use the values as given"; anything else asks Topaz to estimate them,
        # which the frontend shows so a filled-in slider is not mistaken for the truth.
        "estimate": int(resolved.get("estimate", 0)),
        "values": values,
    }


def register(server) -> bool:
    """Attach the routes to a ComfyUI PromptServer. Returns whether it worked."""
    try:
        routes = server.routes
        from aiohttp import web
    except Exception as exc:  # noqa: BLE001
        logger.debug("preset routes not registered: %s", exc)
        return False

    @routes.get(f"{PREFIX}/presets")
    async def list_presets(request):  # noqa: ANN001
        try:
            strength = float(request.query.get("strength", 1.0))
        except (TypeError, ValueError):
            strength = 1.0
        model_dir = model_dir_or_none()
        payload = [_profile_payload(p, strength) for p in profiles.load(model_dir)]
        return web.json_response({"presets": payload, "manual": profiles.MANUAL})

    @routes.post(f"{PREFIX}/presets")
    async def save_preset(request):  # noqa: ANN001
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "expected a JSON body"}, status=400)

        try:
            entry = user_profiles.save(
                body.get("name", ""),
                body.get("values") or body.get("options") or {},
                description=body.get("description", ""),
                estimate=body.get("estimate", 0) or 0,
                suggested_model=body.get("suggested_model", ""),
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except OSError as exc:
            logger.warning("could not write user presets: %s", exc)
            return web.json_response({"error": f"could not save: {exc}"}, status=500)

        # The dropdown is built from this catalog at INPUT_TYPES time, so it has to be
        # rebuilt before the new entry can appear.
        profiles.clear_cache()
        return web.json_response({
            "saved": entry,
            "label": f"{user_profiles.PREFIX}{entry['name']}",
        })

    @routes.delete(f"{PREFIX}/presets/{{name}}")
    async def delete_preset(request):  # noqa: ANN001
        name = request.match_info.get("name", "")
        removed = user_profiles.delete(name)
        if removed:
            profiles.clear_cache()
        return web.json_response({"deleted": removed})

    logger.debug("preset routes registered under %s", PREFIX)
    return True


def register_if_available() -> bool:
    """Register against ComfyUI's server when there is one, otherwise do nothing."""
    try:
        from server import PromptServer
    except Exception:  # noqa: BLE001 - not running inside ComfyUI
        return False
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return False
    try:
        return register(instance)
    except Exception as exc:  # noqa: BLE001
        # A failed route registration costs the preset buttons, nothing more. The nodes
        # themselves must still load.
        logger.warning("preset routes unavailable: %s", exc)
        return False
