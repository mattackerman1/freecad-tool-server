#!/usr/bin/env bash
# FreeCAD Tool Server launcher (Linux / macOS)
# Must use FreeCAD's bundled Python — its compiled bindings are built against
# its own interpreter. Set FREECAD_PYTHON to that interpreter.
#
#   FREECAD_PYTHON=/path/to/FreeCAD/bin/python ./start.sh
#
# Common locations:
#   Linux AppImage:  (extract, then) squashfs-root/usr/bin/python
#   macOS:           /Applications/FreeCAD.app/Contents/Resources/bin/python

set -euo pipefail

FREECAD_PYTHON="${FREECAD_PYTHON:-}"
if [[ -z "$FREECAD_PYTHON" ]]; then
  echo "ERROR: set FREECAD_PYTHON to your FreeCAD bundled Python interpreter." >&2
  echo "  e.g. FREECAD_PYTHON=/path/to/FreeCAD/bin/python ./start.sh" >&2
  exit 1
fi

echo "Starting FreeCAD Tool Server..."
echo "Using Python: $FREECAD_PYTHON"
echo "Server: http://localhost:8000   Docs: http://localhost:8000/docs"
echo

exec "$FREECAD_PYTHON" main.py
