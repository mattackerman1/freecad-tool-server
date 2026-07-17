"""
Elmer FEM solver integration for Tutorial 11: 2D Electrostatics (Fringe Capacitance).

Physics: 2D electrostatics (Laplace equation for electric potential).
Geometry: Plate capacitor, computing fringe capacitance.
Expected: solver norm = 0.3055, capacitance = 13.697 (vs analytical 10.0)
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


def write_electrostatics_2d_sif(
    work_dir: Path,
    *,
    vacuum_permittivity: float = 1.0,
    relative_permittivity: float = 1.0,
    ground_bc_tag: int = 2,
    capacitor_bc_tag: int = 1,
    ground_potential: float = 0.0,
    capacitor_potential: float = 1.0,
    sif_name: str = "case.sif",
) -> Path:
    """Write a 2D electrostatics .sif file for the fringe capacitance tutorial."""
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
    s(f"  Permittivity of Vacuum = {vacuum_permittivity}")
    s("  Boltzmann Constant = 1.3807e-23")
    s("  Unit Charge = 1.602e-19")
    s("End")
    s()
    s("Body 1")
    s("  Target Bodies(1) = 1")
    s('  Name = "Body Property 1"')
    s("  Equation = 1")
    s("  Material = 1")
    s("End")
    s()
    s("Solver 1")
    s("  Equation = Electrostatics")
    s('  Procedure = "StatElecSolve" "StatElecSolver"')
    s("  Calculate Electric Field = True")
    s("  Calculate Electric Energy = True")
    s("  Variable = Potential")
    s("  Exec Solver = Always")
    s("  Stabilize = True")
    s("  Optimize Bandwidth = True")
    s("  Steady State Convergence Tolerance = 1.0e-5")
    s("  Nonlinear System Convergence Tolerance = 1.0e-8")
    s("  Nonlinear System Max Iterations = 20")
    s("  Nonlinear System Newton After Iterations = 3")
    s("  Nonlinear System Newton After Tolerance = 1.0e-3")
    s("  Nonlinear System Relaxation Factor = 1")
    s("  Linear System Solver = Iterative")
    s("  Linear System Iterative Method = BiCGStab")
    s("  Linear System Max Iterations = 500")
    s("  Linear System Convergence Tolerance = 1.0e-8")
    s("  BiCGstabl polynomial degree = 2")
    s("  Linear System Preconditioning = ILU0")
    s("  Linear System Abort Not Converged = False")
    s("  Linear System Residual Output = 1")
    s("  Linear System Precondition Recompute = 1")
    s("End")
    s()
    s("Equation 1")
    s('  Name = "Electrostatics"')
    s("  Active Solvers(1) = 1")
    s("End")
    s()
    s("Material 1")
    s('  Name = "Ideal"')
    s(f"  Relative Permittivity = {relative_permittivity}")
    s("End")
    s()
    s(f"Boundary Condition 1")
    s(f"  Target Boundaries(1) = {ground_bc_tag}")
    s('  Name = "Ground"')
    s(f"  Potential = {ground_potential}")
    s("End")
    s()
    s(f"Boundary Condition 2")
    s(f"  Target Boundaries(1) = {capacitor_bc_tag}")
    s('  Name = "Capacitor"')
    s(f"  Potential = {capacitor_potential}")
    s("End")
    s()

    sif_path = work_dir / sif_name
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path) -> None:
    """Write ELMERSOLVER_STARTINFO file (UTF-8, no BOM)."""
    (work_dir / "ELMERSOLVER_STARTINFO").write_text("case.sif\n", encoding="utf-8")


def run_electrostatics(work_dir: Path, timeout_seconds: int = 300) -> dict:
    """Run ElmerSolver for electrostatics and return returncode, stdout, stderr."""
    env = os.environ.copy()
    env["PATH"] = str(ELMER_BIN) + os.pathsep + env.get("PATH", "")
    env["ELMER_HOME"] = str(ELMER_BIN.parent)

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


def parse_capacitance(stdout: str) -> float | None:
    """
    Parse capacitance from ElmerSolver stdout.

    StatElecSolver prints a line like:
      StatElecSolve: Capacitance:   1.36974E+01
    or computes it from Electric Energy: C = 2*E / U^2.
    With U=1 (default), C = 2*E.
    """
    # Try explicit "Capacitance" line first
    for line in stdout.splitlines():
        lo = line.lower()
        if "capacitance" in lo:
            # Extract the last number on the line
            nums = re.findall(r"[-+]?\d*\.?\d+[eE][-+]?\d+|[-+]?\d+\.?\d*", line)
            if nums:
                try:
                    return float(nums[-1])
                except ValueError:
                    pass

    # Fall back: derive from Electric Energy (C = 2*E when U=1)
    for line in stdout.splitlines():
        lo = line.lower()
        if "electric energy" in lo or "electricenergy" in lo:
            nums = re.findall(r"[-+]?\d*\.?\d+[eE][-+]?\d+|[-+]?\d+\.?\d*", line)
            if nums:
                try:
                    energy = float(nums[-1])
                    return 2.0 * energy
                except ValueError:
                    pass

    return None


def get_potential_stats(work_dir: Path) -> dict:
    """
    Read case_t0001.vtu (or most recent VTU), extract Potential field,
    return max_potential and min_potential.
    """
    # Import VTU parser from elmer_solver
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import elmer_solver as _es

    # Prefer case_t0001.vtu; fall back to most recent
    vtu_path = work_dir / "case_t0001.vtu"
    if not vtu_path.exists():
        vtu_files = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
        if not vtu_files:
            raise RuntimeError(f"No .vtu files found in {work_dir}")
        vtu_path = vtu_files[-1]

    # Try "Potential", then "potential"
    for field in ("Potential", "potential"):
        try:
            values = _es._parse_vtu_field(vtu_path, field)
            if values:
                return {
                    "max_potential": max(values),
                    "min_potential": min(values),
                    "vtu_file": str(vtu_path),
                }
        except Exception:
            pass

    # List available fields for debugging
    available = _es._list_vtu_fields(vtu_path)
    raise RuntimeError(
        f"Field 'Potential' not found in {vtu_path.name}. Available: {available}"
    )
