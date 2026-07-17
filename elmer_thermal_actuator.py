"""
Elmer Tutorial 22 - Thermal Actuator (Coupled Electro-Thermo-Mechanical).

Physics: Coupled StatCurrentSolve + HeatSolve + StressAnalysis.
An electric current through a silicon MEMS actuator causes Joule heating;
the resulting temperature rise produces thermal stress and displacement.

Reference SIF: C:\\Elmer\\tutorials-CL\\tutorials-CL-files\\ThermalActuator\\thermal_actuator.sif
Mesh strategy: Generate a 3D box mesh via ElmerGrid from a .grd file.
               Mesh is in SI units (meters). Material properties in SI.
               Geometry: 60 mm x 24 mm x 2 mm silicon beam.
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
ELMER_GRID = ELMER_BIN / "ElmerGrid.exe"


def elmer_available() -> bool:
    return ELMER_SOLVER.exists()


# ---------------------------------------------------------------------------
# Mesh generation
# ---------------------------------------------------------------------------

def write_grd_file(work_dir: Path, nx: int = 10, ny: int = 5, nz: int = 3) -> Path:
    """
    Write a 3D box GRD file for the thermal actuator.

    Geometry: 0.06 x 0.024 x 0.002 m (60 x 24 x 2 mm) silicon beam.
    Boundary tags (ElmerGrid 3D convention, -out mesh):
      1 = -X face (left end  = ground / fixed displacement)
      2 = +X face (right end = voltage / fixed displacement)
      3 = -Y face
      4 = +Y face
      5 = -Z face
      6 = +Z face
    """
    grd = f"""##### ElmerGrid input file for thermal actuator ######
Version = 210903
Coordinate System = Cartesian 3D
Subcell Divisions in 3D = 1 1 1
Subcell Sizes 1 = 0.06
Subcell Sizes 2 = 0.024
Subcell Sizes 3 = 0.002
Material Structure in 2D
  1
End
Materials Interval = 1 1
Boundary Definitions
# type     out      int
  1        -1        1        1
  2        -2        1        1
  3        -3        1        1
  4        -4        1        1
  5        -5        1        1
  6        -6        1        1
End
Numbering = Horizontal
Element Degree = 1
Element Innernodes = False
Triangles = False
Element Divisions 1 = {nx}
Element Divisions 2 = {ny}
Element Divisions 3 = {nz}
"""
    grd_path = work_dir / "actuator.grd"
    grd_path.write_text(grd, encoding="utf-8")
    return grd_path


def generate_mesh(work_dir: Path, nx: int = 10, ny: int = 5, nz: int = 3) -> dict:
    """
    Generate Elmer mesh files from the GRD file using ElmerGrid.
    Returns dict with returncode, stdout, stderr.
    Mesh files (mesh.header, mesh.nodes, mesh.elements, mesh.boundary)
    are placed directly in work_dir.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    grd_path = write_grd_file(work_dir, nx=nx, ny=ny, nz=nz)

    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    env["PATH"] = str(ELMER_BIN) + os.pathsep + env.get("PATH", "")

    # ElmerGrid creates a subdirectory named after the .grd base name
    # Run without -out to let it create actuator/ subdir, then move files up
    proc = subprocess.run(
        [str(ELMER_GRID), "1", "2", str(grd_path)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )

    # Move mesh files from actuator/ subdirectory to work_dir
    sub_dir = work_dir / "actuator"
    if sub_dir.exists():
        for f in sub_dir.glob("mesh.*"):
            target = work_dir / f.name
            if target.exists():
                target.unlink()
            f.rename(target)

    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "mesh_header_exists": (work_dir / "mesh.header").exists(),
    }


# ---------------------------------------------------------------------------
# SIF writer
# ---------------------------------------------------------------------------

def write_thermal_actuator_sif(
    work_dir: Path,
    *,
    voltage: float = 7.0,
    ground_bc_tag: int = 1,
    voltage_bc_tag: int = 2,
    reference_temperature: float = 298.0,
    # Silicon material properties (SI units — mesh is in meters)
    # Temperature-dependent electric conductivity of doped silicon
    # Values from reference tutorial, scaled to S/m (mesh in meters)
    electric_conductivity_table: list[tuple[float, float]] | None = None,
    density: float = 2330.0,        # kg/m3
    heat_conductivity: float = 32.0, # W/(m K)
    youngs_modulus: float = 169.0e9, # Pa
    poisson_ratio: float = 0.22,
    heat_expansion_coefficient: float = 2.9e-6,  # 1/K
    steady_state_max_iter: int = 30,
    sif_name: str = "case.sif",
) -> Path:
    """
    Write case.sif for Tutorial 22: Thermal Actuator.

    Three coupled solvers (SI units, mesh in meters):
      1. StatCurrentSolve  - electric potential -> Joule heating
      2. Heat Equation     - temperature from Joule heat source
      3. Stress Analysis   - thermal stress / displacement

    Material: silicon with temperature-dependent electric conductivity.
    The original reference tutorial used mm-scaled units with conductivity in S/mm.
    Here we use SI (S/m) since the mesh is generated in meters.
    """
    work_dir = Path(work_dir)

    # Temperature-dependent electric conductivity of silicon (S/m).
    # Original reference tutorial used mm-unit mesh with very high conductivity
    # values scaled to mm units. Here we use SI (m) units with physically
    # reasonable values for doped silicon (heavily n-doped, ~1e4 to 1e5 S/m at 300K).
    # Values decrease with temperature (phonon scattering dominates for doped Si).
    if electric_conductivity_table is None:
        electric_conductivity_table = [
            (298.0,  5.0e4),
            (498.0,  2.0e4),
            (698.0,  1.0e4),
            (898.0,  6.0e3),
            (1098.0, 4.0e3),
            (1298.0, 3.0e3),
            (1683.0, 2.0e3),
            (2000.0, 1.0e3),
        ]

    # Build conductivity table string
    cond_lines = "\n".join(
        f"      {T:.1f}   {sigma:.4e}" for T, sigma in electric_conductivity_table
    )

    sif = f"""Header
  CHECK KEYWORDS Warn
  Mesh DB "." "."
  Include Path ""
  Results Directory ""
End

Simulation
  Max Output Level = 5
  Coordinate System = Cartesian 3D
  Coordinate Mapping(3) = 1 2 3
  Simulation Type = Steady State
  Steady State Max Iterations = {steady_state_max_iter}
  Output Intervals = 1
  Solver Input File = {sif_name}
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
  Name = "Silicon Actuator"
  Equation = 1
  Material = 1
  Initial Condition = 1
  Body Force = 1
End

Equation 1
  Name = "Coupled Electro-Thermo-Mechanical"
  Active Solvers(3) = 1 2 3
End

Solver 1
  Equation = Stat Current Solver
  Procedure = "StatCurrentSolve" "StatCurrentSolver"
  Variable = Potential
  Variable DOFs = 1
  Calculate Volume Current = True
  Calculate Electric Conductivity = True
  Exec Solver = Always
  Stabilize = True
  Bubbles = False
  Lumped Mass Matrix = False
  Optimize Bandwidth = True
  Steady State Convergence Tolerance = 1.0e-6
  Nonlinear System Convergence Tolerance = 1.0e-6
  Nonlinear System Max Iterations = 10
  Nonlinear System Newton After Iterations = 3
  Nonlinear System Newton After Tolerance = 1.0e-12
  Nonlinear System Relaxation Factor = 1.0
  Linear System Solver = Iterative
  Linear System Iterative Method = CG
  Linear System Max Iterations = 500
  Linear System Convergence Tolerance = 1.0e-8
  Linear System Preconditioning = ILU3
  Linear System Residual Output = 50
  Linear System Abort Not Converged = False
End

Solver 2
  Equation = Heat Equation
  Procedure = "HeatSolve" "HeatSolver"
  Variable = Temperature
  Variable DOFs = 1
  Exec Solver = Always
  Stabilize = True
  Bubbles = False
  Lumped Mass Matrix = False
  Optimize Bandwidth = True
  Steady State Convergence Tolerance = 1.0e-7
  Nonlinear System Convergence Tolerance = 1.0e-7
  Nonlinear System Max Iterations = 10
  Nonlinear System Newton After Iterations = 3
  Nonlinear System Newton After Tolerance = 1.0e-12
  Nonlinear System Relaxation Factor = 0.5
  Linear System Solver = Iterative
  Linear System Iterative Method = BiCGStab
  Linear System Max Iterations = 500
  Linear System Convergence Tolerance = 1.0e-9
  Linear System Preconditioning = ILU1
  Linear System Residual Output = 50
  Linear System Abort Not Converged = False
End

Solver 3
  Equation = Stress Analysis
  Procedure = "StressSolve" "StressSolver"
  Variable = Displacement
  Variable DOFs = 3
  Exec Solver = After All
  Stabilize = True
  Bubbles = False
  Lumped Mass Matrix = False
  Optimize Bandwidth = True
  Steady State Convergence Tolerance = 1.0e-6
  Nonlinear System Convergence Tolerance = 1.0e-6
  Nonlinear System Max Iterations = 1
  Nonlinear System Newton After Iterations = 3
  Nonlinear System Newton After Tolerance = 1.0e-12
  Nonlinear System Relaxation Factor = 1.0
  Linear System Solver = Direct
  Linear System Direct Method = Banded
  Linear System Abort Not Converged = False
End

Material 1
  Name = "Silicon"
  Density = {density}
  Heat Conductivity = {heat_conductivity}
  Youngs Modulus = {youngs_modulus}
  Poisson Ratio = {poisson_ratio}
  Heat Expansion Coefficient = {heat_expansion_coefficient}
  Reference Temperature = {reference_temperature}
  Electric Conductivity = Variable Temperature
    Real
{cond_lines}
    End
End

Initial Condition 1
  Name = "RoomTemp"
  Temperature = {reference_temperature}
End

Body Force 1
  Name = "JouleHeat"
  Joule Heat = Logical True
End

Boundary Condition 1
  Target Boundaries(1) = {ground_bc_tag}
  Name = "Ground"
  Potential = 0.0
  Temperature = {reference_temperature}
  Displacement 1 = 0.0
  Displacement 2 = 0.0
  Displacement 3 = 0.0
End

Boundary Condition 2
  Target Boundaries(1) = {voltage_bc_tag}
  Name = "Voltage"
  Potential = {voltage}
  Temperature = {reference_temperature}
  Displacement 1 = 0.0
  Displacement 2 = 0.0
  Displacement 3 = 0.0
End
"""
    sif_path = work_dir / sif_name
    sif_path.write_text(sif, encoding="utf-8")
    return sif_path


# ---------------------------------------------------------------------------
# ELMERSOLVER_STARTINFO
# ---------------------------------------------------------------------------

def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> Path:
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    si = Path(work_dir) / "ELMERSOLVER_STARTINFO"
    si.write_text(f"{sif_name}\n1\n", encoding="utf-8")
    return si


# ---------------------------------------------------------------------------
# Solver runner
# ---------------------------------------------------------------------------

def run_solver(work_dir: Path, timeout: int = 300) -> dict:
    """
    Run ElmerSolver in work_dir.
    Returns dict with returncode, stdout, stderr, log_snippet, converged, elapsed_seconds.
    """
    work_dir = Path(work_dir)
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
    combined = proc.stdout + proc.stderr
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "log_snippet": combined[-3000:],
        "converged": "ALL DONE" in combined,
        "elapsed_seconds": elapsed,
    }


# ---------------------------------------------------------------------------
# VTU parser (binary appended + ASCII)
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
    all_arrays = root.findall(".//DataArray")

    target = None
    for da in all_arrays:
        if da.get("Name") == field_name:
            target = da
            break

    if target is None:
        available = [da.get("Name") for da in all_arrays]
        raise RuntimeError(
            f"Field '{field_name}' not found in {vtu_path.name}. "
            f"Available: {available}"
        )

    fmt = target.get("format", "ascii")
    n_components = int(target.get("NumberOfComponents", "1"))
    dtype_str = target.get("type", "Float64")
    dtype_map = {
        "Float32": ("f", 4),
        "Float64": ("d", 8),
        "Int32": ("i", 4),
        "Int64": ("q", 8),
    }
    pack_char, item_size = dtype_map.get(dtype_str, ("d", 8))

    if fmt == "ascii":
        raw_vals = list(map(float, target.text.split()))
        if n_components > 1:
            result = []
            for i in range(0, len(raw_vals), n_components):
                vec = raw_vals[i:i + n_components]
                result.append(sum(v * v for v in vec) ** 0.5)
            return result
        return raw_vals

    if binary_data is None:
        raise RuntimeError(f"Expected binary data section in {vtu_path.name} but found none.")

    offset = int(target.get("offset", "0"))
    header_type = root.get("header_type", "UInt32")
    hdr_size = 8 if header_type == "UInt64" else 4
    hdr_fmt = "<Q" if header_type == "UInt64" else "<I"

    block_start = offset
    block_len = struct.unpack_from(hdr_fmt, binary_data, block_start)[0]
    data_start = block_start + hdr_size
    data_end = data_start + block_len

    chunk = binary_data[data_start:data_end]
    n_values = len(chunk) // item_size
    values = list(struct.unpack_from(f"<{n_values}{pack_char}", chunk))

    if n_components > 1:
        result = []
        for i in range(0, len(values), n_components):
            vec = values[i:i + n_components]
            result.append(sum(v * v for v in vec) ** 0.5)
        return result
    return [float(v) for v in values]


def get_stats(work_dir: Path) -> dict:
    """
    Parse the most-recent VTU result file and return field statistics for
    Temperature, Displacement (magnitude), and Potential.
    """
    work_dir = Path(work_dir)
    vtu_files = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
    if not vtu_files:
        raise RuntimeError(f"No .vtu result files found in {work_dir}")

    vtu_path = vtu_files[-1]
    result = {"vtu_file": vtu_path.name}

    root, _ = _read_vtu_xml_root(vtu_path)
    available = [da.get("Name") for da in root.findall(".//DataArray") if da.get("Name")]
    result["available_fields"] = available

    fields_to_try = [
        ("temperature", "temperature"),
        ("Temperature", "temperature"),
        ("displacement", "displacement_magnitude"),
        ("Displacement", "displacement_magnitude"),
        ("potential", "potential"),
        ("Potential", "potential"),
    ]

    seen_keys = set()
    for field_name, key_prefix in fields_to_try:
        if key_prefix in seen_keys:
            continue
        try:
            values = _parse_vtu_field(vtu_path, field_name)
            if values:
                result[f"{key_prefix}_min"] = round(min(values), 8)
                result[f"{key_prefix}_max"] = round(max(values), 8)
                result[f"{key_prefix}_mean"] = round(sum(values) / len(values), 8)
                result["node_count"] = len(values)
                seen_keys.add(key_prefix)
        except RuntimeError:
            continue

    return result
