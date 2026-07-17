"""
elmer_driven_cavity.py — Tutorial 20: Driven Cavity Navier-Stokes

2D Navier-Stokes driven cavity: a square cavity whose top lid moves at
lid_velocity (default 1.0 m/s) with no-slip walls on the other three sides.

Functions
---------
write_driven_cavity_sif(work_dir, lid_velocity, viscosity, **kwargs)
write_startinfo(work_dir)
run_driven_cavity(work_dir, timeout) -> dict
get_velocity_stats(work_dir) -> dict
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

# ---------------------------------------------------------------------------
# Elmer binary location (shared with elmer_solver.py convention)
# ---------------------------------------------------------------------------

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


# ---------------------------------------------------------------------------
# SIF writer
# ---------------------------------------------------------------------------

def write_driven_cavity_sif(
    work_dir,
    lid_velocity: float = 1.0,
    viscosity: float = 0.01,
    **kwargs,
) -> Path:
    """
    Write case.sif for the 2D driven cavity Navier-Stokes problem.

    Boundary tags (matching DrivenCavity mesh):
      1, 2, 4 — no-slip walls (bottom, left, right)
      3       — moving lid (top), Velocity 1 = lid_velocity
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    sif = f"""\
Header
  CHECK KEYWORDS Warn
  Mesh DB "." "."
  Include Path ""
  Results Directory ""
End

Simulation
  Max Output Level = 5
  Coordinate System = Cartesian
  Coordinate Mapping(3) = 1 2 3
  Simulation Type = Steady state
  Steady State Max Iterations = 1
  Output Intervals(1) = 1
  Solver Input File = case.sif
  Post File = case.vtu
End

Constants
  Gravity(4) = 0 -1 0 9.82
  Stefan Boltzmann = 5.670374419e-08
  Permittivity of Vacuum = 8.85418781e-12
  Permeability of Vacuum = 1.25663706e-6
  Boltzmann Constant = 1.380649e-23
  Unit Charge = 1.6021766e-19
End

Body 1
  Target Bodies(1) = 1
  Name = "Body 1"
  Equation = 1
  Material = 1
End

Solver 1
  Equation = Navier-Stokes
  Variable = Flow Solution[Velocity:2 Pressure:1]
  Procedure = "FlowSolve" "FlowSolver"
  Exec Solver = Always
  Stabilize = True
  Optimize Bandwidth = True
  Steady State Convergence Tolerance = 1.0e-5
  Nonlinear System Convergence Tolerance = 1.0e-7
  Nonlinear System Max Iterations = 20
  Nonlinear System Newton After Iterations = 20
  Nonlinear System Newton After Tolerance = 1.0e-3
  Nonlinear System Relaxation Factor = 1
  Linear System Solver = Direct
  Linear System Direct Method = Umfpack
End

Equation 1
  Name = "Equation 1"
  Active Solvers(1) = 1
End

Material 1
  Name = "Material 1"
  Viscosity = {viscosity}
  Density = 1
  Compressibility Model = Incompressible
End

Boundary Condition 1
  Target Boundaries(3) = 1 2 4
  Name = "NoSlipWalls"
  Noslip wall BC = True
End

Boundary Condition 2
  Target Boundaries(1) = 3
  Name = "MovingLid"
  Velocity 2 = 0
  Velocity 1 = {lid_velocity}
End
"""

    sif_path = work / "case.sif"
    sif_path.write_text(sif, encoding="utf-8")
    return sif_path


# ---------------------------------------------------------------------------
# ELMERSOLVER_STARTINFO
# ---------------------------------------------------------------------------

def write_startinfo(work_dir) -> Path:
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    work = Path(work_dir)
    p = work / "ELMERSOLVER_STARTINFO"
    p.write_text("case.sif\n1\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Run ElmerSolver
# ---------------------------------------------------------------------------

def run_driven_cavity(work_dir, timeout: int = 120) -> dict:
    """Run ElmerSolver in work_dir. Returns dict with returncode/stdout/stderr."""
    work = Path(work_dir)
    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    # Ensure bin dir is on PATH so DLL dependencies resolve
    existing_path = env.get("PATH", "")
    if str(ELMER_BIN) not in existing_path:
        env["PATH"] = str(ELMER_BIN) + os.pathsep + existing_path

    proc = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(work),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "converged": "ALL DONE" in proc.stdout,
    }


# ---------------------------------------------------------------------------
# VTU parser (raw-binary appended format, as used by Elmer)
# ---------------------------------------------------------------------------

def _read_vtu_xml_root(vtu_path: Path):
    """
    Parse a VTK XML (.vtu) file that may contain raw-binary appended data.
    Returns (ET.Element root, raw_bytes_after_underscore or None).
    """
    raw = vtu_path.read_bytes()
    marker = b'<AppendedData encoding="raw">'
    idx = raw.find(marker)
    if idx == -1:
        return ET.fromstring(raw.decode("utf-8", errors="replace")), None

    header_bytes = raw[:idx + len(marker)]
    # Binary payload starts right after '_' character
    underscore_pos = raw.find(b"_", idx + len(marker))
    binary_data = raw[underscore_pos + 1:] if underscore_pos != -1 else b""

    xml_str = header_bytes.decode("utf-8", errors="replace") + "\n_</AppendedData>\n</VTKFile>"
    return ET.fromstring(xml_str), binary_data


def _parse_vtu_field_components(vtu_path: Path, field_name: str) -> tuple[list[float], int]:
    """
    Extract a named field from a VTU file.
    Returns (flat_values, n_components).
    For a scalar, n_components=1. For a 2-DOF velocity, n_components=2.
    """
    root, binary_data = _read_vtu_xml_root(vtu_path)

    for piece in root.iter("Piece"):
        point_data = piece.find("PointData")
        if point_data is None:
            continue
        for da in point_data.findall("DataArray"):
            name = da.get("Name", "")
            if name.lower() != field_name.lower():
                continue
            n_comp = int(da.get("NumberOfComponents", 1))
            fmt = da.get("format", "ascii")
            if fmt == "ascii":
                text = (da.text or "").strip()
                vals = [float(x) for x in text.split() if x]
                return vals, n_comp
            elif fmt == "appended" and binary_data is not None:
                offset = int(da.get("offset", 0))
                dtype_str = da.get("type", "Float64")
                dtype_map = {
                    "Float32": ("f", 4),
                    "Float64": ("d", 8),
                    "Int32": ("i", 4),
                    "Int64": ("q", 8),
                }
                pack_char, item_size = dtype_map.get(dtype_str, ("d", 8))
                seg = binary_data[offset:]
                byte_len = struct.unpack_from("<I", seg, 0)[0]
                n_vals = byte_len // item_size
                values = list(struct.unpack_from(f"<{n_vals}{pack_char}", seg, 4))
                return [float(v) for v in values], n_comp

    # List available fields for a useful error message
    available = []
    root2, _ = _read_vtu_xml_root(vtu_path)
    for piece in root2.iter("Piece"):
        pd = piece.find("PointData")
        if pd is not None:
            available.extend(da.get("Name", "") for da in pd.findall("DataArray"))
    raise RuntimeError(
        f"Field '{field_name}' not found in {vtu_path.name}. "
        f"Available: {available}"
    )


# ---------------------------------------------------------------------------
# Velocity statistics
# ---------------------------------------------------------------------------

def get_velocity_stats(work_dir) -> dict:
    """
    Read the VTU output file and extract velocity statistics.

    Elmer writes velocity as a multi-component field named "Velocity" with
    NumberOfComponents=2 (vx, vy). The function computes per-node magnitudes
    and returns max/min/mean magnitude plus max component values.
    """
    work = Path(work_dir)
    vtu_files = sorted(work.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
    if not vtu_files:
        raise RuntimeError(f"No .vtu result files found in {work}")
    vtu_path = vtu_files[-1]

    # Try "Velocity" first (Elmer's flow variable export name)
    field_candidates = ["Velocity", "Flow Solution", "velocity"]
    vals = None
    n_comp = 1
    used_field = None
    last_err = None
    for fname in field_candidates:
        try:
            vals, n_comp = _parse_vtu_field_components(vtu_path, fname)
            used_field = fname
            break
        except RuntimeError as e:
            last_err = e

    if vals is None:
        raise RuntimeError(f"Could not find velocity field. Last error: {last_err}")

    if n_comp >= 2:
        # Interleaved: [vx0, vy0, vx1, vy1, ...]
        n_nodes = len(vals) // n_comp
        magnitudes = []
        for i in range(n_nodes):
            components = vals[i * n_comp: i * n_comp + n_comp]
            magnitudes.append(math.sqrt(sum(c * c for c in components)))
    else:
        magnitudes = [abs(v) for v in vals]

    max_mag = max(magnitudes)
    min_mag = min(magnitudes)
    mean_mag = sum(magnitudes) / len(magnitudes)

    return {
        "vtu_file": vtu_path.name,
        "field_name": used_field,
        "n_components": n_comp,
        "node_count": len(magnitudes),
        "max_velocity_magnitude": round(max_mag, 6),
        "min_velocity_magnitude": round(min_mag, 6),
        "mean_velocity_magnitude": round(mean_mag, 6),
    }
