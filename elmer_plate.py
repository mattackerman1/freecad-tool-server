"""
Elmer FEM solver integration for Tutorial 9: Smitc plate deflection solver.

Implements 2D Reissner-Mindlin plate theory for an L-shaped steel plate
under uniform pressure, clamped at all edges.
"""

from __future__ import annotations

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

def write_plate_deflection_sif(
    work_dir: Path,
    *,
    density: float = 7800.0,
    youngs_modulus: float = 209.0e9,
    poisson_ratio: float = 0.3,
    thickness: float = 1.0e-2,
    tension: float = 0.0,
    pressure: float = 5.0e4,
    n_boundary_tags: int = 6,
) -> Path:
    """Write case.sif for the Smitc plate deflection tutorial."""
    tag_str = " ".join(str(i) for i in range(1, n_boundary_tags + 1))

    content = f"""Header
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
  Output Intervals = 1
  Solver Input File = case.sif
  Post File = case.vtu
End

Constants
  Gravity(4) = 0 -1 0 9.82
  Stefan Boltzmann = 5.67e-08
  Permittivity of Vacuum = 8.8542e-12
  Boltzmann Constant = 1.3807e-23
  Unit Charge = 1.602e-19
End

Body 1
  Target Bodies(1) = 1
  Name = "Body 1"
  Equation = 1
  Material = 1
  Body Force = 1
End

Solver 1
  Equation = Elastic Plates
  Procedure = "Smitc" "SmitcSolver"
  Variable = -dofs 3 Deflection
  Exec Solver = Always
  Stabilize = True
  Bubbles = False
  Lumped Mass Matrix = False
  Optimize Bandwidth = True
  Steady State Convergence Tolerance = 1.0e-5
  Nonlinear System Convergence Tolerance = 1.0e-7
  Nonlinear System Max Iterations = 1
  Linear System Solver = Iterative
  Linear System Iterative Method = BiCGStab
  Linear System Max Iterations = 500
  Linear System Convergence Tolerance = 1.0e-10
  BiCGstabl polynomial degree = 2
  Linear System Preconditioning = ILU0
  Linear System Abort Not Converged = False
  Linear System Residual Output = 10
End

Equation 1
  Name = "Elastic Plate"
  Active Solvers(1) = 1
End

Material 1
  Name = "Ideal"
  Density = {density}
  Youngs modulus = {youngs_modulus}
  Poisson ratio = {poisson_ratio}
  Thickness = {thickness}
  Tension = {tension}
End

Body Force 1
  Name = "Pressure"
  Pressure = {pressure}
End

Boundary Condition 1
  Target Boundaries({n_boundary_tags}) = {tag_str}
  Name = "Fixed"
  Deflection 1 = 0.0
  Deflection 2 = 0.0
  Deflection 3 = 0.0
End
"""
    sif_path = work_dir / "case.sif"
    sif_path.write_text(content, encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    (work_dir / "ELMERSOLVER_STARTINFO").write_text(f"{sif_name}\n1\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Run ElmerSolver
# ---------------------------------------------------------------------------

def run_plate(work_dir: Path, timeout_seconds: int = 300) -> dict:
    """Run ElmerSolver in work_dir, return returncode/stdout/stderr."""
    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    existing_path = env.get("PATH", "")
    if str(ELMER_BIN) not in existing_path:
        env["PATH"] = str(ELMER_BIN) + os.pathsep + existing_path

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
# VTU parsing (reuse pattern from elmer_solver.py)
# ---------------------------------------------------------------------------

def _read_vtu_xml_root(vtu_path: Path):
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
                n_comp = int(da.get("NumberOfComponents", 1))
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

    # Try listing available fields for a better error message
    available = []
    try:
        root2, _ = _read_vtu_xml_root(vtu_path)
        for piece in root2.iter("Piece"):
            pd = piece.find("PointData")
            if pd is not None:
                available.extend(da.get("Name", "") for da in pd.findall("DataArray"))
    except Exception:
        pass

    raise RuntimeError(
        f"Field '{field_name}' not found in {vtu_path.name}. "
        f"Available: {available}"
    )


# ---------------------------------------------------------------------------
# Extract deflection statistics
# ---------------------------------------------------------------------------

def get_deflection_stats(work_dir: Path) -> dict:
    """
    Read case_t0001.vtu and extract Deflection field statistics.

    Deflection has 3 components per node:
      component 0: normal displacement (w)
      component 1: rotation around x
      component 2: rotation around y

    Returns max_deflection_m, min_deflection_m, max_rotation_x, max_rotation_y.
    """
    # Try the expected filename first, then fall back to any .vtu
    vtu_path = work_dir / "case_t0001.vtu"
    if not vtu_path.exists():
        candidates = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
        if not candidates:
            raise RuntimeError(f"No .vtu result files found in {work_dir}")
        vtu_path = candidates[-1]

    values = _parse_vtu_field(vtu_path, "Deflection")
    if not values:
        raise RuntimeError(f"Deflection field is empty in {vtu_path.name}")

    # Values are interleaved: [w0, rx0, ry0, w1, rx1, ry1, ...]
    n_comp = 3
    n_nodes = len(values) // n_comp

    w_vals = [values[i * n_comp] for i in range(n_nodes)]
    rx_vals = [values[i * n_comp + 1] for i in range(n_nodes)]
    ry_vals = [values[i * n_comp + 2] for i in range(n_nodes)]

    return {
        "vtu_file": str(vtu_path),
        "node_count": n_nodes,
        "max_deflection_m": max(abs(v) for v in w_vals),
        "min_deflection_m": min(w_vals),
        "max_rotation_x": max(abs(v) for v in rx_vals),
        "max_rotation_y": max(abs(v) for v in ry_vals),
    }
