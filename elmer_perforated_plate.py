"""
Elmer FEM solver integration for Tutorial 14: Capacitance of a Perforated Plate.

Physics: 3D electrostatics — compute the electric potential and energy in the air
gap between a perforated square plate (held at 1 V) and a ground plane (0 V).
The perforation reduces the effective capacitance compared with a solid plate.

Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\CapacitanceOfPerforatedPlate\\
  (hexhole.grd generates a hex mesh of a plate unit cell with one hole)
Mesh is in mm — Coordinate Scaling = 0.001 converts to SI metres.

Boundary tags (reference case.sif):
  4          = ground plane (Potential = 0)
  1, 2, 3, 7 = perforated plate faces (Potential = 1)

Expected results: solver converges in 1 steady-state iteration,
writes case_t0001.vtu with Potential in [0, 1].
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"
TUTORIAL_MESH_DIR = Path(
    r"C:\Elmer\tutorials\tutorials-GUI-files\CapacitanceOfPerforatedPlate"
)


def elmer_available() -> bool:
    return ELMER_SOLVER.exists()


def write_sif(
    work_dir: Path,
    *,
    ground_bc_tag: int = 4,
    capacitor_bc_tags: list[int] | None = None,
    ground_potential: float = 0.0,
    capacitor_potential: float = 1.0,
    relative_permittivity: float = 1.00059,
    coordinate_scaling: float = 0.001,
    sif_name: str = "case.sif",
) -> Path:
    """Write electrostatics SIF for the perforated-plate capacitor tutorial."""
    if capacitor_bc_tags is None:
        capacitor_bc_tags = [1, 2, 3, 7]

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
    s(f"  Coordinate Scaling = {coordinate_scaling}")
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
    s("End")
    s()
    s("Solver 1")
    s("  Equation = Electrostatics")
    s("  Calculate Electric Field = True")
    s('  Procedure = "StatElecSolve" "StatElecSolver"')
    s("  Variable = Potential")
    s("  Calculate Electric Energy = True")
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
    s('  Name = "Air (room temperature)"')
    s("  Heat Capacity = 1005.0")
    s("  Density = 1.205")
    s("  Heat Conductivity = 0.0257")
    s("  Viscosity = 1.983e-5")
    s("  Heat expansion Coefficient = 3.43e-3")
    s(f"  Relative Permittivity = {relative_permittivity}")
    s("  Sound speed = 343.0")
    s("End")
    s()
    s("Boundary Condition 1")
    s(f"  Target Boundaries(1) = {ground_bc_tag}")
    s('  Name = "Ground"')
    s(f"  Potential = {ground_potential}")
    s("End")
    s()
    n_cap = len(capacitor_bc_tags)
    tags_str = " ".join(str(t) for t in capacitor_bc_tags)
    s("Boundary Condition 2")
    s(f"  Target Boundaries({n_cap}) = {tags_str}")
    s('  Name = "Capacitor"')
    s(f"  Potential = {capacitor_potential}")
    s("End")
    s()

    sif_path = work_dir / sif_name
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    (work_dir / "ELMERSOLVER_STARTINFO").write_text(f"{sif_name}\n", encoding="utf-8")


def run_solver(work_dir: Path, timeout: int = 300) -> dict:
    """Run ElmerSolver and return returncode, elapsed_seconds, log_snippet, converged."""
    env = os.environ.copy()
    env["PATH"] = str(ELMER_BIN) + os.pathsep + env.get("PATH", "")
    env["ELMER_HOME"] = str(ELMER_BIN.parent)

    t0 = time.time()
    try:
        result = subprocess.run(
            [str(ELMER_SOLVER)],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "elapsed_seconds": time.time() - t0,
            "log_snippet": "ElmerSolver timed out",
            "converged": False,
            "stdout": "",
        }

    elapsed = time.time() - t0
    combined = result.stdout + result.stderr
    converged = (
        result.returncode == 0
        and "SOLVER TOTAL TIME" in combined
    )

    return {
        "returncode": result.returncode,
        "elapsed_seconds": elapsed,
        "log_snippet": combined[-3000:],
        "converged": converged,
        "stdout": result.stdout,
    }


def get_stats(work_dir: Path, field: str = "Potential") -> dict:
    """
    Parse the most recent VTU file and return min/max/mean for the given field.
    Uses the raw-binary VTU parser from elmer_solver.py.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import elmer_solver as _es

    vtu_path = work_dir / "case_t0001.vtu"
    if not vtu_path.exists():
        vtu_files = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
        if not vtu_files:
            raise RuntimeError(f"No .vtu files found in {work_dir}")
        vtu_path = vtu_files[-1]

    for f in (field, field.lower(), field.upper()):
        try:
            values = _es._parse_vtu_field(vtu_path, f)
            if values:
                return {
                    "field": field,
                    "min_value": min(values),
                    "max_value": max(values),
                    "mean_value": sum(values) / len(values),
                    "n_points": len(values),
                    "vtu_file": str(vtu_path),
                }
        except Exception:
            pass

    available = _es._list_vtu_fields(vtu_path)
    raise RuntimeError(
        f"Field '{field}' not found in {vtu_path.name}. Available: {available}"
    )
