"""ComfyUI-TopazVideoLocal — Topaz Video AI nodes for ComfyUI.

All processing runs locally through the Topaz Video installation on this machine.
Nothing is uploaded anywhere.

Note the package layout: the node modules live in ``topaz_nodes``, not ``nodes``.
ComfyUI has its own top-level ``nodes`` module, and a package of that name here would
shadow it. Everything uses relative imports for the same reason.
"""

__version__ = "0.1.0"

# Frontend assets. ComfyUI serves this directory and loads every .js under it, which is
# how the Upscale Params node gets its preset buttons: widget values are fixed when
# INPUT_TYPES is read, so filling sliders from a preset can only happen in the browser.
WEB_DIRECTORY = "web"

if __package__:
    # Normal case: ComfyUI imports this directory as a package.
    # Import errors are deliberately not caught — a missing dependency must be visible,
    # not silently turn into an empty node list.
    from .topaz_nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
    from .topaz_nodes.server_routes import register_if_available

    # Best-effort: without the routes the buttons report a failure and every other part
    # of the package still works, so this must never prevent the nodes from loading.
    register_if_available()
else:
    # Imported outside a package context. pytest does this: it treats any directory
    # holding an __init__.py as a package node and imports the file directly, where a
    # relative import cannot resolve. The node layer needs ComfyUI anyway, and the tests
    # only exercise topaz_video, so expose empty mappings rather than failing.
    NODE_CLASS_MAPPINGS: dict = {}
    NODE_DISPLAY_NAME_MAPPINGS: dict = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY",
           "__version__"]
