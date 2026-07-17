"""
Tutorial 21: Eigenfrequency Analysis of an Elastic Plate (ElasticPlateEigenmodesGUI)

Uses the Smitc (Reissner-Mindlin) plate bending solver in eigen-analysis mode
to compute the natural frequencies of a clamped pentagon-shaped elastic plate.

Mesh source: C:\\Elmer\\tutorials\\tutorials-GUI-files\\ElasticPlateEigenmodesGUI\\
"""
from __future__ import annotations

import os
import struct
import subprocess
import time
import re
from pathlib import Path

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


def elmer_available() -> bool:
    return ELMER_SOLVER.exists()


def write_sif(
    working_dir: Path,
    density: float = 1000.0,
    youngs_modulus: float = 1.0e9,
    poisson_ratio: float = 0.3,
    thickness: float = 0.001,
    tension: float = 0.0,
    n_eigen_values: int = 10,
    n_boundary_tags: int = 5,
    sif_name: str = "case.sif",
) -> Path:
    """Write the Smitc plate eigen-analysis SIF file for Tutorial 21."""
    # Fixed boundary conditions: all boundary tags clamped
    bc_lines = ""
    for i in range(1, n_boundary_tags + 1):
        bc_lines += f"""
Boundary Condition {i}
  Target Boundaries(1) = {i}
  Name = "Fixed_{i}"
  Deflection 1 = 0.0
  Deflection 2 = 0.0
  Deflection 3 = 0.0
End
"""

    # Group all boundary tags in a single BC block (tutorial style: one BC with all 5 tags)
    tag_list = " ".join(str(i) for i in range(1, n_boundary_tags + 1))
    bc_block = f"""Boundary Condition 1
  Target Boundaries({n_boundary_tags}) = {tag_list}
  Name = "Fixed"
  Deflection 1 = 0.0
  Deflection 2 = 0.0
  Deflection 3 = 0.0
End
"""

    sif_content = f"""Header
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

{bc_block}"""

    sif_path = working_dir / sif_name
    sif_path.write_text(sif_content, encoding="utf-8")
    return sif_path


def write_startinfo(working_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO pointing at the SIF file."""
    si = working_dir / "ELMERSOLVER_STARTINFO"
    si.write_text(f"{sif_name}\n1\n", encoding="utf-8")


def run_solver(working_dir: Path, timeout: int = 300) -> dict:
    """Run ElmerSolver in working_dir, return result dict."""
    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)

    t0 = time.time()
    proc = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(working_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    elapsed = round(time.time() - t0, 2)
    stdout = proc.stdout + proc.stderr
    return {
        "returncode": proc.returncode,
        "elapsed_seconds": elapsed,
        "converged": "ALL DONE" in stdout,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "log_snippet": stdout[-3000:],
    }


def parse_eigenvalues(stdout: str) -> list[float]:
    """
    Extract eigenvalues (omega^2) from ElmerSolver output.
    Elmer prints lines like:
      EigenSolve: 1:    1.884402E+01   0.000000E+00
    or legacy:
      EigenValue(  1) =   1.88921E+01
    """
    eigenvalues = []
    for line in stdout.splitlines():
        # Primary format: "EigenSolve: N:    VALUE   IMAG"
        m = re.search(r"EigenSolve:\s+\d+:\s+([\d.Ee+\-]+)", line)
        if m:
            try:
                eigenvalues.append(float(m.group(1)))
            except ValueError:
                pass
            continue
        # Legacy format
        m = re.search(r"EigenValue\s*\(\s*\d+\s*\)\s*=\s*([0-9Ee+\-\.]+)", line)
        if m:
            try:
                eigenvalues.append(float(m.group(1)))
            except ValueError:
                pass
    return eigenvalues


def _read_vtu_scalar(vtu_path: Path, field_name: str) -> list[float]:
    """
    Minimal raw-binary VTU parser to extract a scalar field.
    Handles both ASCII DataArray and appended raw binary.
    """
    raw = vtu_path.read_bytes()
    text = raw.decode("utf-8", errors="replace")

    # Try ASCII inline data first
    pattern = re.compile(
        rf'<DataArray[^>]*Name="{re.escape(field_name)}"[^>]*>\s*([\d\s.eE+\-]+?)\s*</DataArray>',
        re.DOTALL,
    )
    m = pattern.search(text)
    if m:
        vals = [float(x) for x in m.group(1).split() if x.strip()]
        if vals:
            return vals

    # Try appended binary: find offset from DataArray header
    offset_match = re.search(
        rf'<DataArray[^>]*Name="{re.escape(field_name)}"[^>]*offset="(\d+)"',
        text,
    )
    if offset_match:
        app_match = re.search(rb"<AppendedData[^>]*>_", raw)
        if app_match:
            base = app_match.end()
            offset = int(offset_match.group(1))
            pos = base + offset
            n_bytes = struct.unpack_from("<I", raw, pos)[0]
            n_floats = n_bytes // 4
            floats = struct.unpack_from(f"<{n_floats}f", raw, pos + 4)
            return list(floats)

    return []


def get_stats(working_dir: Path, n_eigen_values: int = 10) -> dict:
    """
    Parse VTU output and return deflection stats per mode.
    Returns eigenvalues parsed from stdout if available, else from VTU files.
    """
    vtu_files = sorted(working_dir.glob("case_t*.vtu"))
    mode_stats = []
    for i, vtu in enumerate(vtu_files[:n_eigen_values]):
        try:
            vals = _read_vtu_scalar(vtu, "Deflection 3")
            if not vals:
                vals = _read_vtu_scalar(vtu, "Deflection")
            if vals:
                mode_stats.append({
                    "mode": i + 1,
                    "file": vtu.name,
                    "min_deflection": round(min(vals), 6),
                    "max_deflection": round(max(vals), 6),
                })
            else:
                mode_stats.append({"mode": i + 1, "file": vtu.name, "note": "no deflection field found"})
        except Exception as e:
            mode_stats.append({"mode": i + 1, "file": vtu.name, "error": str(e)})

    return {
        "vtu_count": len(vtu_files),
        "mode_stats": mode_stats,
    }
