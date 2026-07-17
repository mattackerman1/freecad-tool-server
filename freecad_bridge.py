"""
FreeCAD Python bridge — discovers and imports FreeCAD in headless mode.

Priority order:
  1. FREECAD_PATH env var (explicit override)
  2. Common Windows install locations
  3. Already on sys.path (Linux/Mac package installs)
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_WINDOWS_CANDIDATES = [
    r"C:\Program Files\FreeCAD 1.1\bin",
    r"C:\Program Files\FreeCAD 1.0\bin",
    r"C:\Program Files\FreeCAD 0.21\bin",
    r"C:\Program Files\FreeCAD 0.20\bin",
    r"C:\Program Files\FreeCAD\bin",
    r"C:\Program Files (x86)\FreeCAD 0.21\bin",
    r"C:\Program Files (x86)\FreeCAD 0.20\bin",
]

_LINUX_CANDIDATES = [
    "/usr/lib/freecad/lib",
    "/usr/lib/freecad-python3/lib",
    "/usr/local/lib/freecad/lib",
    "/opt/freecad/lib",
]

# Cached result after first successful import
_freecad: Optional[object] = None
_part: Optional[object] = None


def _inject_path(bin_path: str) -> None:
    """Add FreeCAD bin (and sibling lib) to sys.path if not already present."""
    p = Path(bin_path)
    for d in [p, p.parent / "lib", p.parent / "Ext"]:
        s = str(d)
        if d.exists() and s not in sys.path:
            sys.path.insert(0, s)
            logger.debug("Added to sys.path: %s", s)


def _try_import() -> bool:
    """Attempt to import FreeCAD and Part; return True on success."""
    global _freecad, _part
    try:
        import FreeCAD  # noqa: PLC0415
        import Part     # noqa: PLC0415
        _freecad = FreeCAD
        _part = Part
        # Silence verbose console output (API varies by version — swallow errors)
        try:
            FreeCAD.Console.SetStatus("Log", 0)
            FreeCAD.Console.SetStatus("Wrn", 0)
        except TypeError:
            pass
        logger.info("FreeCAD %s loaded successfully.", FreeCAD.Version()[0])
        return True
    except ImportError:
        return False


def _discover() -> bool:
    """Try all candidate paths until FreeCAD imports cleanly."""
    # 1. Env var override
    env_path = os.environ.get("FREECAD_PATH")
    if env_path:
        _inject_path(env_path)
        if _try_import():
            return True
        logger.warning("FREECAD_PATH set to %s but FreeCAD still not importable.", env_path)

    # 2. Platform candidates
    candidates = _WINDOWS_CANDIDATES if sys.platform == "win32" else _LINUX_CANDIDATES
    for path in candidates:
        if Path(path).exists():
            _inject_path(path)
            if _try_import():
                return True

    # 3. Already available (e.g. conda, apt package)
    return _try_import()


def get_freecad():
    """Return the FreeCAD module, raising ImportError if unavailable."""
    global _freecad
    if _freecad is not None:
        return _freecad
    if not _discover():
        raise ImportError(
            "FreeCAD Python module could not be found. "
            "Set the FREECAD_PATH environment variable to your FreeCAD bin directory, "
            "e.g.  FREECAD_PATH='C:\\Program Files\\FreeCAD 0.21\\bin'"
        )
    return _freecad


def get_part():
    """Return the Part module (requires FreeCAD already discovered)."""
    global _part
    if _part is None:
        get_freecad()  # triggers discovery which also imports Part
    return _part


def freecad_available() -> bool:
    """Non-raising availability check used by the health endpoint."""
    try:
        get_freecad()
        return True
    except ImportError:
        return False
