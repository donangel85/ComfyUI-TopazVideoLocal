"""ComfyUI-TopazStudio — Topaz Video AI nodes for ComfyUI.

All processing runs locally through the Topaz Video installation on this machine.
Nothing is uploaded anywhere.

Note the package layout: the node modules live in ``topaz_nodes``, not ``nodes``.
ComfyUI has its own top-level ``nodes`` module, and a package of that name here would
shadow it. Everything uses relative imports for the same reason.
"""

__version__ = "0.1.0"

if __package__:
    # Normal case: ComfyUI imports this directory as a package.
    # Import errors are deliberately not caught — a missing dependency must be visible,
    # not silently turn into an empty node list.
    from .topaz_nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
else:
    # Imported outside a package context. pytest does this: it treats any directory
    # holding an __init__.py as a package node and imports the file directly, where a
    # relative import cannot resolve. The node layer needs ComfyUI anyway, and the tests
    # only exercise topaz_studio, so expose empty mappings rather than failing.
    NODE_CLASS_MAPPINGS: dict = {}
    NODE_DISPLAY_NAME_MAPPINGS: dict = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "__version__"]
