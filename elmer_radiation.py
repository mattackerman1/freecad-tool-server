"""
Elmer radiation heat transfer support.
Implements two-solver (GebhartFactors + HeatSolve) cases in axi-symmetric coordinates.

Tutorial 4 reference:
  Heat Equation – 2D – Axi Symmetric Steady State Radiation
  Concentric cylinders, two bodies (inner conductivity=10, outer=1),
  diffuse-gray radiation between inner and outer cylindrical surfaces,
  Dirichlet T=100 on exterior wall.

Key difference from plain HeatSolve cases: radiation BCs require ViewFactors.exe to be
on PATH at run time. Use run_radiation_heat() rather than elmer_solver.run_elmer() to
ensure the Elmer bin directory is prepended to PATH automatically.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

# Import constants from elmer_solver (avoids duplicating paths)
try:
    from elmer_solver import ELMER_BIN, ELMER_SOLVER, write_startinfo, get_field_stats
except ImportError:
    # Fallback if imported outside the project root
    ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
    ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"
    from elmer_solver import write_startinfo, get_field_stats


def write_radiation_heat_sif(
    working_dir: Path,
    *,
    coordinate_system: str = "Axi Symmetric",
    bodies: list[dict],
    materials: list[dict],
    body_forces: list[dict],
    initial_conditions: list[dict],
    boundary_conditions: list[dict],
    steady_state_max_iter: int = 1,
    nonlinear_max_iter: int = 50,
    nonlinear_tolerance: float = 1.0e-8,
    sif_name: str = "case.sif",
) -> Path:
    """
    Write a two-solver radiation heat transfer .sif file.

    Parameters
    ----------
    working_dir : Path
        Directory where the .sif will be written (mesh files must be present).
    coordinate_system : str
        "Axi Symmetric" (default) or "Cartesian".
    bodies : list[dict]
        Each dict:
            {
              "target_body": <int mesh body index>,
              "material_idx": <1-based>,
              "body_force_idx": <1-based or None>,
              "ic_idx": <1-based>,
            }
    materials : list[dict]
        Each dict: {"density": float, "heat_capacity": float, "heat_conductivity": float, "name": str (optional)}
    body_forces : list[dict]
        Each dict: {"heat_source": float, "name": str (optional)}
    initial_conditions : list[dict]
        Each dict: {"temperature": float, "name": str (optional)}
    boundary_conditions : list[dict]
        Dirichlet BC:    {"tags": [int, ...], "temperature": float, "name": str (optional)}
        Radiation BC:    {"tags": [int, ...], "radiation": "Diffuse Gray",
                          "emissivity": float, "radiation_target_body": int, "name": str (optional)}
    steady_state_max_iter : int
        Steady State Max Iterations for the simulation block.
    nonlinear_max_iter : int
        Nonlinear System Max Iterations for HeatSolve.
    nonlinear_tolerance : float
        Convergence tolerance for nonlinear / steady-state loops.
    sif_name : str
        Output filename within working_dir.

    Returns
    -------
    Path to the written .sif file.
    """
    lines: list[str] = []

    def s(line: str = "") -> None:
        lines.append(line)

    # ---- Header ----
    s("Header")
    s("  CHECK KEYWORDS Warn")
    s('  Mesh DB "." "."')
    s('  Include Path ""')
    s('  Results Directory ""')
    s("End")
    s()

    # ---- Simulation ----
    s("Simulation")
    s("  Max Output Level = 5")
    s(f"  Coordinate System = {coordinate_system}")
    s("  Coordinate Mapping(3) = 1 2 3")
    s("  Simulation Type = Steady state")
    s(f"  Steady State Max Iterations = {steady_state_max_iter}")
    s("  Output Intervals = 1")
    s(f'  Solver Input File = {sif_name}')
    s("  Post File = case.vtu")
    s("End")
    s()

    # ---- Constants ----
    s("Constants")
    s("  Stefan Boltzmann = 5.67e-08")
    s("End")
    s()

    # ---- Bodies ----
    for i, body in enumerate(bodies, start=1):
        s(f"Body {i}")
        s(f"  Target Bodies(1) = {body['target_body']}")
        s(f"  Equation = 1")
        s(f"  Material = {body['material_idx']}")
        if body.get("body_force_idx") is not None:
            s(f"  Body Force = {body['body_force_idx']}")
        s(f"  Initial Condition = {body['ic_idx']}")
        s("End")
        s()

    # ---- Solver 1: HeatSolve with built-in radiation ----
    # Note: Elmer's HeatSolve handles diffuse-gray radiation internally.
    # When radiation BCs are present, HeatSolve calls ViewFactors.exe automatically
    # to compute view/Gebhart factors before assembly. Ensure ViewFactors.exe is on
    # PATH when running (use run_radiation_heat() for this).
    s("Solver 1")
    s('  Equation = "Heat Equation"')
    s("  Variable = Temperature")
    s('  Procedure = "HeatSolve" "HeatSolver"')
    s("  Exec Solver = Always")
    s("  Stabilize = True")
    s(f"  Steady State Convergence Tolerance = {nonlinear_tolerance}")
    s(f"  Nonlinear System Convergence Tolerance = {nonlinear_tolerance}")
    s(f"  Nonlinear System Max Iterations = {nonlinear_max_iter}")
    s("  Nonlinear System Newton After Iterations = 1")
    s("  Nonlinear System Newton After Tolerance = 1.0e-4")
    s("  Nonlinear System Relaxation Factor = 0.7")
    s("  Linear System Solver = Iterative")
    s("  Linear System Iterative Method = BiCGStab")
    s("  Linear System Max Iterations = 500")
    s("  Linear System Convergence Tolerance = 1.0e-12")
    s("  Linear System Preconditioning = ILU1")
    s("  Linear System Abort Not Converged = False")
    s("End")
    s()

    # ---- Equation ----
    s("Equation 1")
    s("  Active Solvers(1) = 1")
    s("End")
    s()

    # ---- Materials ----
    for i, mat in enumerate(materials, start=1):
        name = mat.get("name", f"Material{i}")
        s(f"Material {i}")
        s(f'  Name = "{name}"')
        s(f"  Density = {mat['density']}")
        s(f"  Heat Capacity = {mat['heat_capacity']}")
        s(f"  Heat Conductivity = {mat['heat_conductivity']}")
        s("End")
        s()

    # ---- Body Forces ----
    for i, bf in enumerate(body_forces, start=1):
        name = bf.get("name", f"BodyForce{i}")
        s(f"Body Force {i}")
        s(f'  Name = "{name}"')
        s(f"  Heat Source = {bf['heat_source']}")
        s("End")
        s()

    # ---- Initial Conditions ----
    for i, ic in enumerate(initial_conditions, start=1):
        name = ic.get("name", f"IC{i}")
        s(f"Initial Condition {i}")
        s(f'  Name = "{name}"')
        s(f"  Temperature = {ic['temperature']}")
        s("End")
        s()

    # ---- Boundary Conditions ----
    for i, bc in enumerate(boundary_conditions, start=1):
        tags = bc.get("tags", [])
        tag_str = " ".join(str(t) for t in tags)
        n = len(tags)
        name = bc.get("name", f"BC{i}")
        s(f"Boundary Condition {i}")
        s(f'  Name = "{name}"')
        s(f"  Target Boundaries({n}) = {tag_str}")
        if "temperature" in bc:
            s(f"  Temperature = {bc['temperature']}")
        if "radiation" in bc:
            s(f"  Radiation = {bc['radiation']}")
            s(f"  Emissivity = {bc['emissivity']}")
            s(f"  Radiation Target Body = {bc.get('radiation_target_body', -1)}")
        s("End")
        s()

    sif_path = working_dir / sif_name
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def run_radiation_heat(working_dir: Path, sif_name: str = "case.sif", timeout_seconds: int = 300) -> dict:
    """
    Run ElmerSolver for a radiation heat case.

    Compared with elmer_solver.run_elmer(), this function:
    - Prepends the Elmer bin directory to PATH so ViewFactors.exe is found.
    - Returns the same dict structure as run_elmer().

    Parameters
    ----------
    working_dir : Path
        Directory containing mesh files and case.sif.
    sif_name : str
        Name of the .sif file (default: case.sif).
    timeout_seconds : int
        Max seconds to wait for ElmerSolver.

    Returns
    -------
    dict with keys: converged, result_norm, elapsed_seconds, return_code, vtu_files, log_snippet
    """
    if not ELMER_SOLVER.exists():
        raise RuntimeError(f"ElmerSolver not found at {ELMER_SOLVER}")

    write_startinfo(working_dir, sif_name)

    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    # Ensure ViewFactors.exe can be found
    elmer_bin_str = str(ELMER_BIN)
    existing = env.get("PATH", "")
    if elmer_bin_str not in existing:
        env["PATH"] = elmer_bin_str + os.pathsep + existing

    t0 = time.time()
    result = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(working_dir),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )
    elapsed = time.time() - t0

    stdout = result.stdout + result.stderr
    converged = "ALL DONE" in stdout
    norm = None
    for line in stdout.splitlines():
        if "Result Norm" in line and ":" in line:
            try:
                norm = float(line.split(":")[-1].strip())
            except ValueError:
                pass

    vtu_files = list(working_dir.glob("*.vtu"))

    return {
        "converged": converged,
        "result_norm": norm,
        "elapsed_seconds": round(elapsed, 2),
        "return_code": result.returncode,
        "vtu_files": [str(f) for f in vtu_files],
        "log_snippet": stdout[-3000:] if stdout else "",
    }
