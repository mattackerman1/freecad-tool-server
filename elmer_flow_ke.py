"""
elmer_flow_ke.py — Tutorial 14: Turbulent Flow past a Step (k-epsilon model)

Implements the FlowStepKe Elmer tutorial:
  - Navier-Stokes solver with k-epsilon turbulence model
  - Steady-state 2D incompressible flow
  - Parabolic inlet velocity profile
  - Wall boundary conditions (no-slip)
  - Free outlet
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Elmer binary location
# ---------------------------------------------------------------------------

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


def elmer_available() -> bool:
    return ELMER_SOLVER.exists()


# ---------------------------------------------------------------------------
# SIF writer
# ---------------------------------------------------------------------------

def write_sif(
    work_dir: Path,
    *,
    density: float = 1.0,
    viscosity: float = 1.0e-4,
    wall_tags: list[int] = (3,),
    inlet_tag: int = 1,
    outlet_tag: int = 2,
    max_inlet_velocity: float = 1.5,
    inlet_y_min: float = 1.0,
    inlet_y_max: float = 2.0,
    kinetic_energy_init: float = 0.00457,
    kinetic_dissipation_init: float = 1.0e-4,
    steady_state_max_iter: int = 200,
    sif_name: str = "case.sif",
) -> Path:
    """
    Write a case.sif for the k-epsilon turbulent flow past a step tutorial.

    The mesh uses boundary tag convention:
      1 = inlet
      2 = outlet
      3 = walls (all no-slip surfaces)

    The parabolic inlet velocity profile uses MATC:
        U_x = 4 * U_max * (y - y_min) * (y_max - y) / (y_max - y_min)^2
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # Build wall BC block
    wall_tag_str = " ".join(str(t) for t in wall_tags)
    n_wall_tags = len(list(wall_tags))

    span = inlet_y_max - inlet_y_min
    # Elmer MATC parabolic: 4*Umax*(ty-ymin)*(ymax-ty) / span^2
    matc_expr = (
        f"4*{max_inlet_velocity}*"
        f"(tx-{inlet_y_min})*({inlet_y_max}-tx)"
        f"/({span}^2)"
    )

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
  Steady State Max Iterations = {steady_state_max_iter}
  Output Intervals(1) = 1
  Solver Input File = {sif_name}
  Post File = case.vtu
End

Constants
  Gravity(4) = 0 -1 0 9.82
  Stefan Boltzmann = 5.67e-08
  Permittivity of Vacuum = 8.85418781e-12
  Boltzmann Constant = 1.3807e-23
  Unit Charge = 1.602e-19
End

Body 1
  Target Bodies(1) = 1
  Name = "Body 1"
  Equation = 1
  Material = 1
  Initial Condition = 1
End

Solver 1
  Equation = Navier-Stokes
  Variable = Flow Solution[Velocity:2 Pressure:1]
  Procedure = "FlowSolve" "FlowSolver"
  Exec Solver = Always
  Stabilize = True
  Optimize Bandwidth = True
  Steady State Convergence Tolerance = 1.0e-4
  Nonlinear System Convergence Tolerance = 1.0e-7
  Nonlinear System Max Iterations = 1
  Nonlinear System Newton After Iterations = 3
  Nonlinear System Newton After Tolerance = 0.0
  Nonlinear System Relaxation Factor = 0.5
  Linear System Solver = Iterative
  Linear System Iterative Method = BiCGStab
  Linear System Max Iterations = 500
  Linear System Convergence Tolerance = 1.0e-8
  Linear System Preconditioning = ILU0
  Linear System Abort Not Converged = False
  Linear System Residual Output = 10
End

Solver 2
  Equation = K-Epsilon
  Variable = K-Epsilon[Kinetic Energy:1 Kinetic Dissipation:1]
  Procedure = "KESolver" "KESolver"
  Exec Solver = Always
  Stabilize = True
  Optimize Bandwidth = True
  Steady State Convergence Tolerance = 1.0e-4
  Nonlinear System Convergence Tolerance = 1.0e-5
  Nonlinear System Max Iterations = 1
  Nonlinear System Newton After Iterations = 3
  Nonlinear System Newton After Tolerance = 1.0e-3
  Nonlinear System Relaxation Factor = 0.2
  Linear System Solver = Iterative
  Linear System Iterative Method = BiCGStab
  Linear System Max Iterations = 500
  Linear System Convergence Tolerance = 1.0e-8
  Linear System Preconditioning = ILU0
  Linear System Abort Not Converged = False
  Linear System Residual Output = 10
End

Equation 1
  Name = "Flow Equations"
  Active Solvers(2) = 1 2
End

Material 1
  Name = "Ideal"
  Density = {density}
  Viscosity = {viscosity}
  Viscosity Model = K-Epsilon
  Compressibility Model = Incompressible
  KE Clip = 1.0e-6
End

Initial Condition 1
  Name = "Initial Guess"
  Velocity 1 = 0.0
  Velocity 2 = 0.0
  Kinetic Energy = {kinetic_energy_init}
  Kinetic Dissipation = {kinetic_dissipation_init}
End

Boundary Condition 1
  Target Boundaries(1) = {inlet_tag}
  Name = "Inlet"
  Velocity 2 = 0.0
  Velocity 1 = Variable Coordinate 2
    Real MATC "{matc_expr}"
  Kinetic Energy = {kinetic_energy_init}
  Kinetic Dissipation = {kinetic_dissipation_init}
End

Boundary Condition 2
  Target Boundaries(1) = {outlet_tag}
  Name = "Outlet"
  Velocity 2 = 0.0
End

Boundary Condition 3
  Target Boundaries({n_wall_tags}) = {wall_tag_str}
  Name = "Walls"
  Velocity 1 = 0.0
  Velocity 2 = 0.0
End

"""

    sif_path = work_dir / sif_name
    sif_path.write_text(sif, encoding="utf-8")
    return sif_path


# ---------------------------------------------------------------------------
# ELMERSOLVER_STARTINFO writer
# ---------------------------------------------------------------------------

def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    p = Path(work_dir) / "ELMERSOLVER_STARTINFO"
    p.write_text(f"{sif_name}\n1\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Solver runner
# ---------------------------------------------------------------------------

def run_solver(work_dir: Path, timeout: int = 300) -> dict:
    """Run ElmerSolver in work_dir. Returns returncode/stdout/stderr dict."""
    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    env["PATH"] = str(ELMER_BIN) + os.pathsep + env.get("PATH", "")

    t0 = time.time()
    proc = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    elapsed = round(time.time() - t0, 2)

    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "elapsed_seconds": elapsed,
        "converged": "ALL DONE" in proc.stdout,
        "log_snippet": (proc.stdout + proc.stderr)[-3000:],
    }


# ---------------------------------------------------------------------------
# Raw-binary VTU parser
# ---------------------------------------------------------------------------

def _parse_vtu_field_raw(vtu_path: Path, field_name: str) -> list[float]:
    """
    Parse a field from a VTU file written with encoding="raw" (Elmer default).

    Elmer writes VTU files with <AppendedData encoding="raw"> where each
    DataArray is stored as: [Int32 byte_length][Float64 data...].
    Offsets in the XML header are cumulative byte positions from the start
    of the appended data section (after the '_' marker).
    """
    raw = vtu_path.read_bytes()

    # Split at AppendedData to get clean XML header
    split_pos = raw.find(b"<AppendedData")
    if split_pos == -1:
        raise ValueError(f"No <AppendedData section in {vtu_path.name}")

    # Build parseable XML: use regex to find all DataArray tags from the header
    xml_header = raw[:split_pos].decode("latin-1")

    # Parse DataArray attributes using regex (avoids XML closing-tag issues)
    import re
    da_pattern = re.compile(
        r'<DataArray\s+([^/]+?)(?:/>|>)',
        re.DOTALL | re.IGNORECASE
    )
    attr_pattern = re.compile(r'(\w+)="([^"]*)"')

    all_das = []
    for m in da_pattern.finditer(xml_header):
        attrs = dict(attr_pattern.findall(m.group(1)))
        all_das.append(attrs)

    # Find matching DataArray (case-insensitive)
    target_offset = None
    n_components = 1
    da_type = "Float64"
    field_lower = field_name.lower()
    for attrs in all_das:
        if attrs.get("Name", "").lower() == field_lower:
            target_offset = int(attrs.get("offset", "0"))
            n_components = int(attrs.get("NumberOfComponents", "1"))
            da_type = attrs.get("type", "Float64")
            break

    if target_offset is None:
        available = [a.get("Name") for a in all_das if "Name" in a]
        raise ValueError(
            f"Field '{field_name}' not found in {vtu_path.name}. "
            f"Available: {available}"
        )

    # Locate the raw binary section (after the underscore marker)
    # The underscore is the first character after encoding="raw">
    appended_start = raw.find(b"_", split_pos)
    if appended_start == -1:
        raise ValueError("No raw appended data marker found in VTU file.")
    data_start = appended_start + 1

    # Jump to our block using the XML offset
    block_start = data_start + target_offset

    # Read Int32 length prefix (4 bytes)
    byte_length = struct.unpack_from("<I", raw, block_start)[0]
    values_start = block_start + 4

    # Determine element size from type
    if da_type == "Float64":
        fmt_char = "d"
        elem_size = 8
    elif da_type == "Float32":
        fmt_char = "f"
        elem_size = 4
    elif da_type == "Int32":
        fmt_char = "i"
        elem_size = 4
    else:
        fmt_char = "d"
        elem_size = 8

    n_values = byte_length // elem_size
    values = struct.unpack_from(f"<{n_values}{fmt_char}", raw, values_start)

    return list(values)


def get_stats(
    work_dir: Path,
    field_name: str = "velocity",
) -> dict:
    """
    Read the VTU output and return statistics for the requested field.

    For the k-epsilon flow tutorial the fields in the VTU are (lowercase):
      'velocity'             — velocity vector (2 components: Vx, Vy)
      'pressure'             — pressure field
      'kinetic energy'       — turbulent kinetic energy k
      'kinetic dissipation'  — turbulent dissipation rate epsilon

    Case-insensitive matching is applied automatically.
    """
    work_dir = Path(work_dir)
    vtu_files = sorted(work_dir.glob("case_t*.vtu"))
    if not vtu_files:
        single = work_dir / "case.vtu"
        if single.exists():
            vtu_files = [single]
    if not vtu_files:
        raise FileNotFoundError(f"No VTU files found in {work_dir}")

    vtu = vtu_files[-1]  # use the last (final steady-state) file

    try:
        values = _parse_vtu_field_raw(vtu, field_name)
    except Exception:
        # Fallback: try as plain XML (some Elmer builds write ASCII VTU)
        values = _parse_vtu_field_ascii(vtu, field_name)

    if not values:
        raise ValueError(f"Field '{field_name}' returned no values from {vtu.name}")

    n = len(values)
    mn = min(values)
    mx = max(values)
    mean = sum(values) / n
    rms = (sum(v * v for v in values) / n) ** 0.5

    return {
        "field_name": field_name,
        "vtu_file": vtu.name,
        "node_count": n,
        "min_value": mn,
        "max_value": mx,
        "mean_value": mean,
        "rms_norm": rms,
    }


def _parse_vtu_field_ascii(vtu_path: Path, field_name: str) -> list[float]:
    """Fallback: parse ASCII-format VTU (slow but robust)."""
    import re

    text = vtu_path.read_text(encoding="utf-8", errors="replace")
    # Find DataArray block for field_name
    pattern = rf'<DataArray[^>]*Name="{re.escape(field_name)}"[^>]*>(.*?)</DataArray>'
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        available = re.findall(r'Name="([^"]+)"', text)
        raise ValueError(
            f"Field '{field_name}' not found. Available: {list(set(available))}"
        )
    raw_values = m.group(1).strip().split()
    return [float(v) for v in raw_values]
