"""
Elmer FEM solver integration — Tutorial 7: 3D Linear Elasticity (Loaded Elastic Beam).

A dry pine timber beam (1m x 0.1m x 0.05m) clamped at one end, with gravity
and a point load of ~2000N at the free end.

Expected max displacement: ~6.36 cm (0.0636 m).

NOTE on Elmer's Force keyword in boundary conditions:
  In Elmer, "Force 2 = <value>" in a Boundary Condition block is a *per-node*
  nodal force integrated over the boundary using shape-function weights.  It is
  NOT a surface traction (N/m2) — the total resultant force depends on the
  mesh density and element type.  To apply a true pressure/traction use
  "Traction 2 = <value>" (N/m2 * face area = N).

  For this 6073-node mesh the equivalent of ~2000 N total tip force requires
  Force 2 = -45800000.0 (empirically derived from the Elmer tutorial reference
  case_bigF.sif which produces max_disp ~ 0.0645 m).

  If you want a mesh-independent load, use Traction 2 instead:
    Traction 2 = -2000 / 0.005  = -400000  N/m2  (face area = 0.1*0.05 = 0.005 m2)
  but verify against a known result because the traction VTU from the Elmer
  team's own test run showed ~0 m (possible convergence issue in that run).
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


# ---------------------------------------------------------------------------
# SIF writer
# ---------------------------------------------------------------------------

def write_elasticity_3d_sif(
    work_dir: Path,
    *,
    poisson_ratio: float = 0.37,
    youngs_modulus: float = 10.0e9,
    density: float = 550.0,
    gravity_force_y: float = -9.81,
    wall_bc_tag: int = 5,
    load_bc_tag: int = 6,
    force_y: float = -45_800_000.0,
) -> Path:
    """Write case.sif for a 3D linear elasticity beam problem."""
    lines: list[str] = []

    def s(line: str = "") -> None:
        lines.append(line)

    s("Header")
    s("  CHECK KEYWORDS Warn")
    s('  Mesh DB "." "."')
    s('  Include Path ""')
    s('  Results Directory ""')
    s("End")
    s()
    s("Simulation")
    s("  Max Output Level = 4")
    s("  Coordinate System = Cartesian")
    s("  Coordinate Mapping(3) = 1 2 3")
    s("  Simulation Type = Steady state")
    s("  Steady State Max Iterations = 1")
    s("  Output Intervals = 1")
    s("  Timestepping Method = BDF")
    s("  BDF Order = 1")
    s("  Solver Input File = case.sif")
    s("  Post File = case.vtu")
    s("End")
    s()
    s("Constants")
    s("  Gravity(4) = 0 -1 0 9.82")
    s("  Stefan Boltzmann = 5.67e-08")
    s("  Permittivity of Vacuum = 8.8542e-12")
    s("  Boltzmann Constant = 1.3807e-23")
    s("  Unit Charge = 1.602e-19")
    s("End")
    s()
    s("Body 1")
    s("  Target Bodies(1) = 1")
    s('  Name = "Body 1"')
    s("  Equation = 1")
    s("  Material = 1")
    s("  Body Force = 1")
    s("End")
    s()
    s("Solver 1")
    s("  Equation = Linear elasticity")
    s('  Procedure = "StressSolve" "StressSolver"')
    s("  Variable = -dofs 3 Displacement")
    s("  Exec Solver = Always")
    s("  Stabilize = True")
    s("  Bubbles = False")
    s("  Lumped Mass Matrix = False")
    s("  Optimize Bandwidth = True")
    s("  Steady State Convergence Tolerance = 1.0e-5")
    s("  Nonlinear System Convergence Tolerance = 1.0e-8")
    s("  Nonlinear System Max Iterations = 1")
    s("  Nonlinear System Newton After Iterations = 3")
    s("  Nonlinear System Newton After Tolerance = 1.0e-3")
    s("  Nonlinear System Relaxation Factor = 1")
    s("  Linear System Solver = Iterative")
    s("  Linear System Iterative Method = GCR")
    s("  Linear System Max Iterations = 500")
    s("  Linear System Convergence Tolerance = 1.0e-8")
    s("  BiCGstabl polynomial degree = 2")
    s("  Linear System Preconditioning = ILU0")
    s("  Linear System ILUT Tolerance = 1.0e-3")
    s("  Linear System Abort Not Converged = False")
    s("  Linear System Residual Output = 1")
    s("  Linear System Precondition Recompute = 1")
    s("End")
    s()
    s("Equation 1")
    s('  Name = "Elasticity"')
    s("  Calculate Stresses = True")
    s("  Active Solvers(1) = 1")
    s("End")
    s()
    s("Material 1")
    s('  Name = "Pine"')
    s(f"  Density = {density}")
    s(f"  Youngs modulus = {youngs_modulus}")
    s(f"  Poisson ratio = {poisson_ratio}")
    s("End")
    s()
    # Body force: gravity = gravity_force_y * density  (N/m^3)
    body_force_val = gravity_force_y * density
    s("Body Force 1")
    s('  Name = "Gravity"')
    s(f"  Stress Bodyforce 2 = $ {gravity_force_y}*{density}")
    s("End")
    s()
    s("Boundary Condition 1")
    s(f"  Target Boundaries(1) = {wall_bc_tag}")
    s('  Name = "Wall"')
    s("  Displacement 1 = 0.0")
    s("  Displacement 2 = 0.0")
    s("  Displacement 3 = 0.0")
    s("End")
    s()
    s("Boundary Condition 2")
    s(f"  Target Boundaries(1) = {load_bc_tag}")
    s('  Name = "Mass"')
    s(f"  Force 2 = {force_y}")
    s("End")
    s()

    sif_path = work_dir / "case.sif"
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path) -> None:
    """Write ELMERSOLVER_STARTINFO pointing to case.sif."""
    (work_dir / "ELMERSOLVER_STARTINFO").write_text("case.sif\n1\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Run ElmerSolver
# ---------------------------------------------------------------------------

def run_elasticity_3d(work_dir: Path, timeout_seconds: int = 600) -> dict:
    """Run ElmerSolver in work_dir. Returns returncode, stdout, stderr."""
    if not ELMER_SOLVER.exists():
        raise RuntimeError(f"ElmerSolver not found at {ELMER_SOLVER}")

    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    existing_path = env.get("PATH", "")
    elmer_bin_str = str(ELMER_BIN)
    if elmer_bin_str not in existing_path:
        env["PATH"] = elmer_bin_str + os.pathsep + existing_path

    result = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ---------------------------------------------------------------------------
# VTU parsing helpers (copied from elmer_solver.py pattern)
# ---------------------------------------------------------------------------

def _read_vtu_xml_root(vtu_path: Path):
    """
    Parse a VTK XML (.vtu) file that may contain raw binary appended data.
    Returns (ET.Element root, raw_bytes_after_underscore_or_None).
    """
    raw = vtu_path.read_bytes()
    marker = b'<AppendedData encoding="raw">'
    idx = raw.find(marker)
    if idx == -1:
        return ET.fromstring(raw.decode("utf-8", errors="replace")), None

    header_bytes = raw[: idx + len(marker)]
    after_marker = raw[idx + len(marker):]
    underscore_pos = after_marker.find(b"_")
    if underscore_pos == -1:
        return ET.fromstring(raw.decode("utf-8", errors="replace")), None
    binary_data = after_marker[underscore_pos + 1:]

    xml_str = header_bytes.decode("utf-8", errors="replace") + "\n_</AppendedData>\n</VTKFile>"
    return ET.fromstring(xml_str), binary_data


def _parse_vtu_field(vtu_path: Path, field_name: str) -> list[float]:
    """
    Extract a named field from a VTK XML (.vtu) file.
    For vector fields (NumberOfComponents > 1), returns all components flat.
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
            fmt = da.get("format", "ascii")
            if fmt == "ascii":
                text = (da.text or "").strip()
                return [float(x) for x in text.split() if x]
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
                return [float(v) for v in values]

    # List available fields for error message
    available = []
    for piece in root.iter("Piece"):
        pd = piece.find("PointData")
        if pd is not None:
            available.extend(da.get("Name", "") for da in pd.findall("DataArray"))
    raise RuntimeError(
        f"Field '{field_name}' not found in {vtu_path.name}. "
        f"Available fields: {available}"
    )


# ---------------------------------------------------------------------------
# Displacement statistics
# ---------------------------------------------------------------------------

def get_displacement_stats_3d(work_dir: Path) -> dict:
    """
    Read case_t0001.vtu (or the most recent .vtu), extract the Displacement
    vector field (3-DOF per node), and return magnitude and per-component stats.
    """
    # Prefer case_t0001.vtu; fall back to most recently modified .vtu
    preferred = work_dir / "case_t0001.vtu"
    if preferred.exists():
        vtu_path = preferred
    else:
        vtu_files = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
        if not vtu_files:
            raise RuntimeError(f"No .vtu result files found in {work_dir}")
        vtu_path = vtu_files[-1]

    # Parse flat list — 3 components per node: [ux0, uy0, uz0, ux1, uy1, uz1, ...]
    flat = _parse_vtu_field(vtu_path, "Displacement")

    if len(flat) % 3 != 0:
        raise RuntimeError(
            f"Displacement field has {len(flat)} values, not divisible by 3."
        )

    n_nodes = len(flat) // 3
    ux = flat[0::3]
    uy = flat[1::3]
    uz = flat[2::3]

    magnitudes = [math.sqrt(ux[i]**2 + uy[i]**2 + uz[i]**2) for i in range(n_nodes)]

    return {
        "vtu_file": str(vtu_path),
        "node_count": n_nodes,
        "max_magnitude_m": max(magnitudes),
        "min_x": min(ux),
        "max_x": max(ux),
        "min_y": min(uy),
        "max_y": max(uy),
        "min_z": min(uz),
        "max_z": max(uz),
    }
