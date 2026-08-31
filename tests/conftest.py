"""Test bootstrap.

The package root contains an ``__init__.py`` that imports the ComfyUI node layer. The
tests must not touch that: they exercise ``topaz_studio``, which is deliberately free of
ComfyUI imports so it runs anywhere.

Putting the package directory on ``sys.path`` here (rather than in each test module)
keeps the test files clean, and ``--import-mode=importlib`` in pyproject.toml stops
pytest from trying to import the root ``__init__`` as a module.
"""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))
