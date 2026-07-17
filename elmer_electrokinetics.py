"""
elmer_electrokinetics.py — Tutorial 25: Electrokinetic flow in a T-shaped microchannel.

Physics:
  1. Electrostatics (StatCurrentSolver) — electric potential phi driven by applied voltages.
  2. Navier-Stokes — fluid velocity with Helmholtz-Smoluchowski electroosmotic slip BC at walls.
  3. Advection-Diffusion — concentration transport (solute plug injected at inlet-A).

Geometry: T-shaped microchannel in 2D (Tcross.grd mesh).
  Boundary tags:
    1 = channel walls (electroosmotic slip BC)
    2 = inlet-el-A  (top arm: V=100V, concentration injection)
    3 = outlet-el-B (right arm: V=30V, outflow)
    4 = outlet-el-C (bottom arm: V=0V, outflow)
    5 = remaining walls (same as tag 1 in some meshes)

Reference: Elmer tutorials-GUI-files/Electrokinetics
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"
TUTORIAL_MESH_DIR = Path(r"C:\Elmer\tutorials\tutorials-GUI-files\Electrokinetics")

# Coordinate scaling: mesh is in units of 1e-5 m (10 micrometres per unit)
DEFAULT_COORDINATE_SCALING = 1.0e-5


def elmer_available() -> bool:
    return ELMER_SOLVER.exists()


def write_sif(
    work_dir: Path,
    *,
    # Material
    density: float = 1000.0,          # water kg/m3
    viscosity: float = 1.0e-3,        # water Pa.s
    diffusivity: float = 1.0e-10,     # solute diffusivity m2/s
    relative_permittivity: float = 1.0,
    eo_mobility: float = 5.0e-8,       # electroosmotic mobility m2/(V.s)
    # BCs
    wall_tags: list[int] = None,
    inlet_tag: int = 2,
    outlet_b_tag: int = 3,
    outlet_c_tag: int = 4,
    inlet_potential: float = 100.0,    # V
    outlet_b_potential: float = 30.0,  # V
    outlet_c_potential: float = 0.0,   # V
    # Simulation
    n_timesteps: int = 120,
    timestep_size: float = 1.0e-5,    # s
    output_intervals: int = 2,
    coordinate_scaling: float = DEFAULT_COORDINATE_SCALING,
    sif_name: str = "case.sif",
) -> Path:
    """Write the case.sif for the electrokinetics tutorial."""
    if wall_tags is None:
        wall_tags = [1, 5]

    # Build wall BC target string (can be multiple tags)
    wall_tag_list = " ".join(str(t) for t in wall_tags)

    sif = f"""\
Header
  CHECK KEYWORDS Warn
  Mesh DB "." "."
  Include Path ""
  Results Directory ""
End

Simulation
  Max Output Level = 5
  Coordinate System = Cartesian 2D
  Coordinate Mapping(3) = 1 2 3
  Simulation Type = Transient
  Steady State Max Iterations = 20
  Timestep Intervals = {n_timesteps}
  Timestep Sizes = {timestep_size}
  Output Intervals = {output_intervals}
  Coordinate Scaling = {coordinate_scaling}
  Timestepping Method = BDF
  BDF Order = 2
  Post File = "case.vtu"
End

Constants
  Gravity(4) = 0 -1 0 9.82
  Stefan Boltzmann = 5.6704e-08
  Unit Charge = 1.602e-19
  Boltzmann Constant = 1.3807e-23
End

Body 1
  Target Bodies(1) = 1
  Name = "fluid"
  Equation = 1
  Material = 1
End

Solver 1
  Equation = Electrostatics
  Procedure = "StatElecSolve" "StatElecSolver"
  Variable = Potential
  Variable DOFs = 1
  Calculate Electric Field = True
  Calculate Electric Flux = False
  Linear System Solver = Direct
  Linear System Direct Method = umfpack
  Steady State Convergence Tolerance = 1.0e-5
  Exec Solver = Before Timestep
End

Solver 2
  Equation = Navier-Stokes
  Procedure = "FlowSolve" "FlowSolver"
  Variable = Flow Solution[Velocity:2 Pressure:1]
  Stabilize = True
  Bubbles = False
  Steady State Convergence Tolerance = 1.0e-5
  Nonlinear System Convergence Tolerance = 1.0e-5
  Nonlinear System Max Iterations = 5
  Nonlinear System Newton After Tolerance = 1.0e-2
  Nonlinear System Newton After Iterations = 3
  Nonlinear System Relaxation Factor = 1.0
  Linear System Solver = Direct
  Linear System Direct Method = umfpack
  Exec Solver = Always
End

Solver 3
  Equation = Advection Diffusion Equation
  Procedure = "AdvectionDiffusion" "AdvectionDiffusionSolver"
  Variable = Concentration
  Variable DOFs = 1
  Velocity Variable Name = Flow Solution
  Stabilize = True
  Steady State Convergence Tolerance = 1.0e-5
  Nonlinear System Convergence Tolerance = 1.0e-5
  Nonlinear System Max Iterations = 3
  Linear System Solver = Direct
  Linear System Direct Method = umfpack
  Exec Solver = Always
End

Solver 4
  Equation = SaveScalars
  Procedure = "SaveData" "SaveScalars"
  Filename = "scalars.dat"
  Exec Solver = After Timestep
End

Equation 1
  Name = "AllEquations"
  Active Solvers(3) = 1 2 3
End

Material 1
  Name = "Water"
  Density = {density}
  Viscosity = {viscosity}
  Relative Permittivity = {relative_permittivity}
  Concentration Diffusivity = {diffusivity}
End

! ---- Boundary Conditions ----

! Channel walls: no-slip (zero velocity) + electroosmotic slip via Helmholtz-Smoluchowski
Boundary Condition 1
  Target Boundaries({len(wall_tags)}) = {wall_tag_list}
  Name = "channel-walls"
  Noslip wall BC = False
  Velocity 1 = Variable Pressure
    Real Procedure "Electrokinetics" "helmholtz_smoluchowski1"
  Velocity 2 = Variable Pressure
    Real Procedure "Electrokinetics" "helmholtz_smoluchowski2"
  EO Mobility = Real {eo_mobility}
  Concentration Flux = 0.0
End

! Inlet electrode A (top arm): fixed potential + concentration injection pulse
Boundary Condition 2
  Target Boundaries(1) = {inlet_tag}
  Name = "inlet-el-A"
  Potential = {inlet_potential}
  Velocity 2 = 0.0
  Concentration = Variable Time
    Real
      0.0      1.0
      3.0e-5   1.0
      4.0e-5   0.0
      0.5      0.0
    End
End

! Outlet electrode B (right arm): fixed potential + zero normal velocity
Boundary Condition 3
  Target Boundaries(1) = {outlet_b_tag}
  Name = "outlet-el-B"
  Potential = {outlet_b_potential}
  Velocity 1 = 0.0
End

! Outlet electrode C (bottom arm): ground + zero normal velocity
Boundary Condition 4
  Target Boundaries(1) = {outlet_c_tag}
  Name = "outlet-el-C"
  Potential = {outlet_c_potential}
  Velocity 1 = 0.0
End
"""

    sif_path = work_dir / sif_name
    sif_path.write_text(sif, encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> Path:
    """Write ELMERSOLVER_STARTINFO pointing to the SIF."""
    si = work_dir / "ELMERSOLVER_STARTINFO"
    si.write_text(f"{sif_name}\n1\n", encoding="utf-8")
    return si


def run_solver(work_dir: Path, timeout: int = 300) -> dict:
    """Run ElmerSolver in work_dir. Returns dict with returncode, stdout, stderr, elapsed_seconds."""
    t0 = time.time()
    try:
        result = subprocess.run(
            [str(ELMER_SOLVER)],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - t0
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        log_snippet = (stdout + stderr)[-3000:]
        converged = (
            result.returncode == 0
            and "ELMER SOLVER FINISHED AT" in (stdout + stderr).upper()
        )
        return {
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "log_snippet": log_snippet,
            "elapsed_seconds": elapsed,
            "converged": converged,
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Timed out after {timeout}s",
            "log_snippet": f"Timed out after {timeout}s",
            "elapsed_seconds": timeout,
            "converged": False,
        }


def get_stats(work_dir: Path, field_name: str = "Concentration") -> dict:
    """
    Parse the last VTU file and return min/max/mean for a named field.

    Handles Elmer's appended raw-binary VTU (little-endian float64).
    Field name matching is case-insensitive.
    Elmer writes field names in lowercase (e.g. 'concentration', 'potential',
    'velocity', 'pressure', 'electric field').

    For multi-component fields (velocity=3 components), returns stats for
    the first (x) component and the overall magnitude.
    """
    import re
    import struct

    vtu_files = sorted(work_dir.glob("case*.vtu"))
    if not vtu_files:
        return {"error": "No VTU files found"}

    vtu_path = vtu_files[-1]
    raw = vtu_path.read_bytes()

    # Locate binary data block (after the underscore following <AppendedData ...>)
    app_idx = raw.find(b"<AppendedData")
    if app_idx < 0:
        return {"field": field_name, "error": "No AppendedData section found"}
    underscore_pos = raw.find(b"_", app_idx) + 1
    xml_header = raw[:underscore_pos].decode("utf-8", errors="replace")
    bin_data = raw[underscore_pos:]

    # Parse DataArray attributes from XML header with regex (avoids binary corruption issues)
    target = field_name.lower()
    da_re = re.compile(r'<DataArray\b([^>]+)/>', re.DOTALL)
    attr_re = re.compile(r'(\w+)="([^"]*)"')

    matched_attrs = None
    for m in da_re.finditer(xml_header):
        attrs = dict(attr_re.findall(m.group(1)))
        name = attrs.get("Name", "").lower()
        if name == target or (target.startswith(name) and name):
            matched_attrs = attrs
            break

    if matched_attrs is None:
        available = [dict(attr_re.findall(m.group(1))).get("Name", "")
                     for m in da_re.finditer(xml_header)]
        return {
            "field": field_name,
            "error": f"Field not found. Available: {available}",
            "vtu_file": vtu_path.name,
        }

    dtype_str = matched_attrs.get("type", "Float64")
    n_comp = int(matched_attrs.get("NumberOfComponents", "1"))
    offset = int(matched_attrs.get("offset", "0"))
    fmt_map = {"Float32": ("f", 4), "Float64": ("d", 8), "Int32": ("i", 4)}
    fmt_char, item_size = fmt_map.get(dtype_str, ("d", 8))

    # Binary block: 4-byte uint32 byte-count, then data
    n_bytes = struct.unpack_from("<I", bin_data, offset)[0]
    n_items = n_bytes // item_size
    vals = list(struct.unpack_from(f"<{n_items}{fmt_char}", bin_data, offset + 4))

    if not vals:
        return {"field": field_name, "error": "empty data block"}

    if n_comp == 1:
        comp_vals = vals
    else:
        # Extract first component; compute magnitude separately
        comp_vals = vals[0::n_comp]

    return {
        "field": field_name,
        "vtu_file": vtu_path.name,
        "n_nodes": len(comp_vals),
        "n_components": n_comp,
        "min_value": min(comp_vals),
        "max_value": max(comp_vals),
        "mean_value": sum(comp_vals) / len(comp_vals),
    }
