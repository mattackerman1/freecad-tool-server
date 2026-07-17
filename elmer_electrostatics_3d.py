"""
Elmer FEM solver integration for Tutorial 12: 3D Electrostatics (Capacitance of Two Balls).

Physics: 3D electrostatics to compute the capacitance matrix of two perfectly conducting
balls inside a large sphere (far-field boundary). The capacitance matrix is 2x2:
  C11 (self-capacitance of ball 1), C22 (self-capacitance of ball 2), C12 (cross).

Mesh dir: C:\\Elmer\\tutorials\\tutorials-GUI-files\\CapacitanceOfTwoBalls\\
Expected: norm ~ 0.36356324, C12 ~ 1.691, C11 ~ C22 ~ 5.019 (reference values)
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


def write_capacitance_matrix_sif(
    work_dir: Path,
    *,
    vacuum_permittivity: float = 1.0,
    relative_permittivity: float = 1.0,
    farfield_bc_tag: int = 3,
    cap_body1_bc_tag: int = 1,
    cap_body2_bc_tag: int = 2,
    sif_name: str = "case.sif",
) -> Path:
    """
    Write a 3D electrostatics .sif file for the capacitance matrix of two balls.

    Matches the reference case.sif in CapacitanceOfTwoBalls tutorial exactly,
    but with parameterized boundary tags and material properties.

    BC tags (from reference case.sif):
      - farfield_bc_tag=3  → outer sphere (Electric Infinity BC)
      - cap_body1_bc_tag=1 → ball 1 (Capacitance Body = 1)
      - cap_body2_bc_tag=2 → ball 2 (Capacitance Body = 2)
    """
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
    s("  Max Output Level = 5")
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
    s('  Name = "Body 1"')
    s("  Equation = 1")
    s("  Material = 1")
    s("End")
    s()
    s("Body 2")
    s("  Target Bodies(1) = 2")
    s('  Name = "Body Property 2"')
    s("  Equation = 1")
    s("  Material = 1")
    s("End")
    s()
    s("Solver 1")
    s("  Equation = Electrostatics")
    s("  Calculate Electric Field = True")
    s('  Procedure = "StatElecSolve" "StatElecSolver"')
    s("  Variable = Potential")
    s("  Calculate Electric Energy = True")
    s("  Calculate Capacitance Matrix = True")
    s("  Exec Solver = Always")
    s("  Stabilize = True")
    s("  Bubbles = False")
    s("  Lumped Mass Matrix = False")
    s("  Optimize Bandwidth = True")
    s("  Steady State Convergence Tolerance = 1.0e-5")
    s("  Nonlinear System Convergence Tolerance = 1.0e-7")
    s("  Nonlinear System Max Iterations = 20")
    s("  Nonlinear System Newton After Iterations = 3")
    s("  Nonlinear System Newton After Tolerance = 1.0e-3")
    s("  Nonlinear System Relaxation Factor = 1")
    s("  Linear System Solver = Iterative")
    s("  Linear System Iterative Method = BiCGStab")
    s("  Linear System Max Iterations = 500")
    s("  Linear System Convergence Tolerance = 1.0e-10")
    s("  BiCGstabl polynomial degree = 2")
    s("  Linear System Preconditioning = ILU0")
    s("  Linear System ILUT Tolerance = 1.0e-3")
    s("  Linear System Abort Not Converged = False")
    s("  Linear System Residual Output = 10")
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
    s("Boundary Condition 1")
    s(f"  Target Boundaries(1) = {farfield_bc_tag}")
    s('  Name = "Farfield"')
    s("  Electric Infinity BC = True")
    s("End")
    s()
    s("Boundary Condition 2")
    s(f"  Target Boundaries(1) = {cap_body1_bc_tag}")
    s('  Name = "CapBody1"')
    s("  Capacitance Body = 1")
    s("End")
    s()
    s("Boundary Condition 3")
    s(f"  Target Boundaries(1) = {cap_body2_bc_tag}")
    s('  Name = "CapBody2"')
    s("  Capacitance Body = 2")
    s("End")
    s()

    sif_path = work_dir / sif_name
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO file (UTF-8, no BOM)."""
    (work_dir / "ELMERSOLVER_STARTINFO").write_text(f"{sif_name}\n", encoding="utf-8")


def run_electrostatics_3d(work_dir: Path, timeout_seconds: int = 300) -> dict:
    """Run ElmerSolver for 3D electrostatics and return returncode, stdout, stderr."""
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


def parse_capacitance_matrix(stdout: str) -> dict | None:
    """
    Parse capacitance matrix from ElmerSolver stdout.

    Elmer's StatElecSolver prints:
      StatElecSolver: Capacitance matrix computation performed (i,j,C_ij)
      StatElecSolver:   1  1    5.08316E+00
      StatElecSolver:   1  2    1.69616E+00
      StatElecSolver:   2  2    5.07563E+00

    Returns dict: {"C11": float, "C12": float, "C22": float}
    or None if not found.
    """
    result: dict = {}
    lines = stdout.splitlines()
    in_matrix = False

    for line in lines:
        if "capacitance matrix" in line.lower():
            in_matrix = True
            continue

        if in_matrix:
            # Match lines like: "StatElecSolver:   1  1    5.08316E+00"
            # Extract trailing i j value pattern
            m = re.search(
                r"\b(\d+)\s+(\d+)\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*$",
                line,
            )
            if m:
                i, j, val = int(m.group(1)), int(m.group(2)), float(m.group(3))
                if i == 1 and j == 1:
                    result["C11"] = val
                elif (i == 1 and j == 2) or (i == 2 and j == 1):
                    result["C12"] = val
                elif i == 2 and j == 2:
                    result["C22"] = val
            elif result:
                # Stop reading after blank line or non-matching line once we have data
                stripped = line.strip()
                if stripped and not stripped.startswith("StatElec"):
                    in_matrix = False

    return result if result else None


def get_potential_stats_3d(work_dir: Path) -> dict:
    """
    Read case_t0001.vtu (or most recent VTU), extract Potential field,
    return max_potential and min_potential.
    """
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

    # Try "Potential" field
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
