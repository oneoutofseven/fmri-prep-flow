"""Record the Python packages that interpret inputs and verify outputs."""

import platform
from importlib.metadata import version


def environment():
    return {
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("numpy", "nibabel", "pybids", "matplotlib")},
    }
