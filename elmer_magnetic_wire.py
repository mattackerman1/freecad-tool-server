# elmer_magnetic_wire.py
"""
Elmer Tutorial 18: Magnetic field of a current-carrying wire.

Uses the MagnetoDynamics WhitneyAVHarmonicSolver (harmonic A-V formulation)
to compute the complex magnetic vector potential and derived quantities
(magnetic field strength H, Joule heating) in a copper wire and surrounding air.

Geometry: two-body mesh — Body 1 = copper wire, Body 2 = air.
Boundary tags (from mesh.boundary):
  1 = voltage inlet face
  3 = ground face
  4,5,6 = outer/axial field boundaries (tangential field = 0)
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Elmer binary location
# ---------------------------------------------------------------------------

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"

TUTORIAL_MESH_DIR = Path(
    r"C:\Elmer\tutorials\tutorials-GUI-files\MagneticFieldWire"
)


def elmer_available() -> bool:
    return ELMER_SOLVER.exists()


# ---------------------------------------------------------------------------
# SIF writer
# ---------------------------------------------------------------------------

def write_magnetic_wire_sif(
    working_dir: Path,
    angular_frequency: float = 1.0e5,
    coordinate_scaling: float = 1.0e-3,
    copper_conductivity: float = 59.59e6,
    copper_permeability: float = 0.999994,
    air_permeability: float = 1.00000037,
    voltage_amplitude: float = 0.01,
    voltage_tag: int = 1,
    ground_tag: int = 3,
    axial_tags: list[int] | None = None,
    sif_name: str = "case.sif",
) -> Path:
    """Write a harmonic magnetodynamics SIF for the wire problem."""
    if axial_tags is None:
        axial_tags = [4, 5, 6]

    axial_str = " ".join(str(t) for t in axial_tags)

    sif = f"""Header
  CHECK KEYWORDS Warn
  Mesh DB "." "."
  Include Path ""
  Results Directory ""
End

Simulation
  Max Output Level = 6
  Coordinate System = Cartesian
  Coordinate Mapping(3) = 1 2 3
  Simulation Type = Steady state
  Steady State Max Iterations = 1
  Output Intervals(1) = 1
  Coordinate Scaling = {coordinate_scaling}
  Angular Frequency = {angular_frequency}
  Solver Input File = {sif_name}
  Post File = case.vtu
End

Constants
  Gravity(4) = 0 -1 0 9.82
  Stefan Boltzmann = 5.670374419e-08
  Permittivity of Vacuum = 8.85418781e-12
  Permeability of Vacuum = 1.25663706e-6
  Boltzmann Constant = 1.380649e-23
  Unit Charge = 1.6021766e-19
End

Body 1
  Target Bodies(1) = 1
  Name = "Copper"
  Equation = 1
  Material = 1
End

Body 2
  Target Bodies(1) = 2
  Name = "Air"
  Equation = 1
  Material = 2
End

! Solver 1: harmonic A-V formulation (Whitney elements)
Solver 1
  Equation = MgHarm
  Procedure = "MagnetoDynamics" "WhitneyAVHarmonicSolver"
  Exec Solver = Always
  Stabilize = True
  Optimize Bandwidth = True
  Steady State Convergence Tolerance = 1.0e-5
  Nonlinear System Convergence Tolerance = 1.0e-7
  Nonlinear System Max Iterations = 20
  Nonlinear System Newton After Iterations = 3
  Nonlinear System Newton After Tolerance = 1.0e-3
  Nonlinear System Relaxation Factor = 1
  Linear System Solver = Iterative
  Linear System Iterative Method = BiCGStabl
  Linear System Max Iterations = 500
  Linear System Convergence Tolerance = 1.0e-10
  BiCGstabl polynomial degree = 4
  Linear System Preconditioning = none
  Linear System ILUT Tolerance = 1.0e-3
  Linear System Abort Not Converged = False
  Linear System Residual Output = 10
  Linear System Precondition Recompute = 1
End

! Solver 2: post-processing (field strength + Joule heating)
Solver 2
  Equation = MgDynPost
  Calculate Joule Heating = True
  Calculate Magnetic Field Strength = True
  Procedure = "MagnetoDynamics" "MagnetoDynamicsCalcFields"
  Discontinuous Bodies = True
  Exec Solver = Before Saving
  Stabilize = True
  Optimize Bandwidth = True
  Steady State Convergence Tolerance = 1.0e-5
  Nonlinear System Convergence Tolerance = 1.0e-7
  Nonlinear System Max Iterations = 20
  Nonlinear System Newton After Iterations = 3
  Nonlinear System Newton After Tolerance = 1.0e-3
  Nonlinear System Relaxation Factor = 1
  Linear System Solver = Iterative
  Linear System Iterative Method = BiCGStab
  Linear System Max Iterations = 500
  Linear System Convergence Tolerance = 1.0e-10
  BiCGstabl polynomial degree = 2
  Linear System Preconditioning = ILU0
  Linear System ILUT Tolerance = 1.0e-3
  Linear System Abort Not Converged = False
  Linear System Residual Output = 10
  Linear System Precondition Recompute = 1
End

Equation 1
  Name = "Equation 1"
  Active Solvers(2) = 1 2
End

Material 1
  Name = "Copper (generic)"
  Heat Conductivity = 401.0
  Electric Conductivity = {copper_conductivity}
  Poisson ratio = 0.34
  Relative Permeability = {copper_permeability}
  Youngs modulus = 115.0e9
  Heat expansion Coefficient = 16.5e-6
  Density = 8960.0
  Sound speed = 3810.0
  Heat Capacity = 385.0
End

Material 2
  Name = "Air (room temperature)"
  Relative Permeability = {air_permeability}
  Viscosity = 1.983e-5
  Heat expansion Coefficient = 3.43e-3
  Heat Conductivity = 0.0257
  Density = 1.205
  Sound speed = 343.0
  Relative Permittivity = 1.00059
  Heat Capacity = 1005.0
End

Boundary Condition 1
  Target Boundaries(1) = {ground_tag}
  Name = "Ground"
  AV re {{e}} 1 = 0
  AV im {{e}} 1 = 0
  AV im {{e}} 2 = 0
  AV im = 0
  AV re {{e}} 2 = 0
  AV re = 0
End

Boundary Condition 2
  Target Boundaries(1) = {voltage_tag}
  Name = "Voltage"
  AV im {{e}} 2 = 0
  AV re {{e}} 2 = 0
  AV im {{e}} 1 = 0
  AV im = 0
  AV re {{e}} 1 = 0
  AV re = {voltage_amplitude}
End

Boundary Condition 3
  Target Boundaries({len(axial_tags)}) = {axial_str}
  Name = "AxialField"
  AV re {{e}} 1 = 0
  AV re {{e}} 2 = 0
  AV im {{e}} 1 = 0
  AV im {{e}} 2 = 0
End
"""

    sif_path = working_dir / sif_name
    sif_path.write_text(sif, encoding="utf-8")
    return sif_path


def write_startinfo(working_dir: Path, sif_name: str = "case.sif") -> None:
    (working_dir / "ELMERSOLVER_STARTINFO").write_text(f"{sif_name}\n1\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Solver runner
# ---------------------------------------------------------------------------

def run_solver(working_dir: Path, timeout: int = 300) -> dict:
    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    existing = env.get("PATH", "")
    if str(ELMER_BIN) not in existing:
        env["PATH"] = str(ELMER_BIN) + os.pathsep + existing

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
    combined = proc.stdout + proc.stderr
    converged = "ALL DONE" in combined

    return {
        "returncode": proc.returncode,
        "converged": converged,
        "elapsed_seconds": elapsed,
        "log_snippet": combined[-3000:],
    }


# ---------------------------------------------------------------------------
# VTU result reader (raw binary)
# ---------------------------------------------------------------------------

def _parse_vtu_field(vtu_path: Path, field_name: str) -> list[float]:
    """
    Parse an appended-binary VTU file and extract values for `field_name`.
    Returns a flat list of float64 values.

    VTK raw-appended format: after <AppendedData encoding="raw">_,
    each DataArray block is: [4-byte uint32 byte_count][float64 * n_values].
    The `offset` attribute in the XML header is the byte offset from the
    start of the binary block.
    """
    import re

    raw = vtu_path.read_bytes()

    # Binary block starts after the '_' following <AppendedData encoding="raw">
    appended_marker = b'<AppendedData encoding="raw">'
    marker_pos = raw.find(appended_marker)
    if marker_pos == -1:
        raise ValueError(f"No raw appended data found in {vtu_path.name}")
    underscore_pos = raw.find(b"_", marker_pos)
    if underscore_pos == -1:
        raise ValueError("Could not find binary data start '_'")
    binary_start = underscore_pos + 1

    # Parse XML header only
    xml_text = raw[:marker_pos].decode("latin-1", errors="replace")

    # Find DataArray with matching Name (case-insensitive)
    pattern = re.compile(
        r'<DataArray[^>]*Name="' + re.escape(field_name) + r'"[^>]*/?>',
        re.IGNORECASE
    )
    m = pattern.search(xml_text)
    if not m:
        raise ValueError(
            f"Field '{field_name}' not found in {vtu_path.name}."
        )
    tag_text = m.group(0)

    off_m = re.search(r'offset="(\d+)"', tag_text, re.IGNORECASE)
    if not off_m:
        raise ValueError(f"No offset for '{field_name}'")
    offset = int(off_m.group(1))

    block_pos = binary_start + offset
    byte_count = struct.unpack_from("<I", raw, block_pos)[0]
    n_values = byte_count // 8  # float64
    values = list(struct.unpack_from(f"<{n_values}d", raw, block_pos + 4))
    return values


def get_field_stats(working_dir: Path, field_name: str = "az re") -> dict:
    """
    Parse the VTU result and return min/max/mean/rms for the given field.
    For the magnetic wire problem, typical fields: 'av re', 'av im',
    'Magnetic Field Strength re 1', 'Joule Heating'.
    """
    vtu_files = sorted(working_dir.glob("case*.vtu"))
    if not vtu_files:
        raise FileNotFoundError(f"No VTU files found in {working_dir}")
    vtu = vtu_files[-1]

    vals = _parse_vtu_field(vtu, field_name)
    if not vals:
        raise ValueError(f"Field '{field_name}' has no values in {vtu.name}")

    n = len(vals)
    mn = min(vals)
    mx = max(vals)
    mean = sum(vals) / n
    rms = (sum(v * v for v in vals) / n) ** 0.5

    return {
        "field_name": field_name,
        "vtu_file": str(vtu),
        "node_count": n,
        "min_value": mn,
        "max_value": mx,
        "mean_value": mean,
        "rms_norm": rms,
    }
