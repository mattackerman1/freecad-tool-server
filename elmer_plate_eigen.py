"""
elmer_plate_eigen.py — Tutorial 10: Smitc plate eigenmode analysis.

Pentagon-shaped steel plate, all edges clamped. Computes the 10 lowest
eigenmodes using the SmitcSolver.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Elmer binary location
ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


def write_plate_eigenmodes_sif(
    work_dir: Path,
    *,
    density: float = 1000.0,
    youngs_modulus: float = 1.0e9,
    poisson_ratio: float = 0.3,
    thickness: float = 0.001,
    tension: float = 0.0,
    n_eigen_values: int = 10,
    n_boundary_tags: int = 5,
) -> Path:
    """Write case.sif for plate eigenmode analysis into work_dir."""
    tags_str = " ".join(str(i) for i in range(1, n_boundary_tags + 1))
    sif = f"""Header
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
End

Solver 1
  Equation = Elastic Plates
  Procedure = "Smitc" "SmitcSolver"
  Variable = -dofs 3 Deflection
  Exec Solver = Always
  Eigen Analysis = True
  Eigen System Values = {n_eigen_values}
  Stabilize = True
  Bubbles = False
  Lumped Mass Matrix = False
  Optimize Bandwidth = True
  Steady State Convergence Tolerance = 1.0e-5
  Linear System Solver = Direct
  Linear System Direct Method = Umfpack
  Linear System Abort Not Converged = False
  Linear System Residual Output = 10
End

Equation 1
  Name = "Plate Equation"
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

Boundary Condition 1
  Target Boundaries({n_boundary_tags}) = {tags_str}
  Name = "Fixed"
  Deflection 1 = 0.0
  Deflection 2 = 0.0
  Deflection 3 = 0.0
End
"""
    sif_path = Path(work_dir) / "case.sif"
    sif_path.write_text(sif, encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path) -> None:
    """Write ELMERSOLVER_STARTINFO pointing to case.sif."""
    p = Path(work_dir) / "ELMERSOLVER_STARTINFO"
    p.write_text("case.sif\n1\n", encoding="utf-8")


def run_plate_eigen(work_dir: Path) -> dict:
    """Run ElmerSolver in work_dir. Returns dict with returncode, stdout, stderr."""
    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    existing_path = env.get("PATH", "")
    if str(ELMER_BIN) not in existing_path:
        env["PATH"] = str(ELMER_BIN) + os.pathsep + existing_path

    proc = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def parse_eigenvalues(stdout: str) -> list[float]:
    """
    Parse eigenvalues (omega^2) from ElmerSolver stdout.

    Elmer SmitcSolver prints lines like:
        EigenSolve: 1:    1.884402E+01   0.000000E+00
        EigenSolve: 2:    8.075503E+01   0.000000E+00

    We also try generic fallback patterns.
    """
    eigenvalues: list[float] = []

    # Strategy 1: EigenSolve: N:  <real>  <imag>  pattern
    pattern1 = re.compile(
        r'EigenSolve:\s+(\d+):\s+([-+]?\d+[\.,]\d+[Ee][+-]?\d+)\s+([-+]?\d+[\.,]\d+[Ee][+-]?\d+)'
    )
    for m in pattern1.finditer(stdout):
        try:
            val = float(m.group(2).replace(',', '.'))
            eigenvalues.append(val)
        except ValueError:
            pass

    if eigenvalues:
        return eigenvalues

    # Strategy 2: Lines like "  1   1.8900E+01" anywhere in output
    pattern2 = re.compile(r'^\s*(\d+)\s+([-+]?\d+[\.,]\d+[Ee][+-]?\d+)\s*$')
    for line in stdout.splitlines():
        m = pattern2.match(line)
        if m:
            try:
                val = float(m.group(2).replace(',', '.'))
                eigenvalues.append(val)
            except ValueError:
                pass

    if eigenvalues:
        return eigenvalues

    # Strategy 3: Any line with "eigenval" context followed by scientific numbers
    lines = stdout.splitlines()
    in_eigen = False
    sci = re.compile(r'([-+]?\d+[\.,]\d+[Ee][+-]?\d+)')
    for line in lines:
        if 'computed' in line.lower() and 'eigen' in line.lower():
            in_eigen = True
            continue
        if in_eigen:
            nums = sci.findall(line)
            if nums:
                try:
                    val = float(nums[0].replace(',', '.'))
                    if val > 0:
                        eigenvalues.append(val)
                except ValueError:
                    pass
            elif line.strip() and 'eigensolve' not in line.lower():
                in_eigen = False

    return eigenvalues


def get_eigenmode_vtu_stats(work_dir: Path, n_modes: int) -> dict:
    """Check how many eigenmode VTU files were written."""
    work = Path(work_dir)
    count = 0
    for i in range(1, n_modes + 1):
        candidate = work / f"case_t{i:04d}.vtu"
        if candidate.exists():
            count += 1
    # Also check generic *.vtu
    all_vtu = list(work.glob("*.vtu"))
    return {
        "vtu_files_found": count,
        "total_vtu_in_dir": len(all_vtu),
        "vtu_names": [f.name for f in sorted(all_vtu)[:20]],
    }
