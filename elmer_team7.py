# elmer_team7.py
"""
Elmer Tutorial 31: TEAM Workshop Problem 7 — Asymmetrical Conductor with a Hole.

3D transient eddy currents in an aluminium plate with an eccentric hole, driven
by a sinusoidal coil current.

Physics:
  - CoilSolver        — computes normalized coil current distribution
  - WhitneyAVSolver   — transient A-V formulation (eddy currents)
  - MagnetoDynamicsCalcFields — post-processing: B, H, J fields

Reference:
  elmer-elmag / TEAM7 / TEAM7.sif  (Jonathan Velasco, CSC, March 2021)

Mesh source:
  https://github.com/ElmerCSC/elmer-elmag  (TEAM7/TEAM7/ subdirectory)
  Mesh bodies (from mesh.names):
    1 = Coil, 2 = Plate (aluminium), 3 = Air
  Mesh boundaries:
    4 = CoilSkin, 5 = PlateSkin, 6 = Inf (far-field, AV=0)
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Elmer binary location
# ---------------------------------------------------------------------------

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"
ELMER_GRID = ELMER_BIN / "ElmerGrid.exe"

TEAM7_MESH_SOURCE = Path(
    r"C:\Elmer\elmer-elmag-extracted\elmer-elmag-main\TEAM7\TEAM7"
)


def elmer_available() -> bool:
    return ELMER_SOLVER.exists()


# ---------------------------------------------------------------------------
# SIF writer
# ---------------------------------------------------------------------------

def write_team7_sif(
    working_dir: Path,
    timestep_interval: int = 16,
    timestep_size: float = 0.0025,
    sif_name: str = "case.sif",
) -> Path:
    """
    Write the TEAM7 transient eddy current SIF.

    The SIF is based directly on the reference case from:
      elmer-elmag/TEAM7/TEAM7.sif

    Key settings:
      - Simulation Type = Transient
      - 16 timesteps × 0.0025 s = 0.04 s (2 periods at 50 Hz)
      - CoilSolver: desired current = -2742 A
      - Frequency: 50 Hz, cos(2*pi*50*t) current drive
      - Aluminium: sigma = 3.526e7 S/m

    The mesh must be in working_dir/TEAM7/ (standard Elmer mesh layout).
    """
    working_dir.mkdir(parents=True, exist_ok=True)

    sif_content = f"""! TEAM Workshop Problem 7: Asymmetrical Conductor with a Hole
! Transient 3D eddy current simulation
! Based on elmer-elmag/TEAM7/TEAM7.sif (Jonathan Velasco, CSC)

Header
  CHECK KEYWORDS Warn
  Mesh DB "." "TEAM7"
  Results Directory "res"
End

Simulation
  Coordinate System = String "Cartesian 3D"
  Coordinate Mapping(3) = 1 2 3
  Simulation Type = String "Transient"
  Steady State Max Iterations = 1
  TimeStepping Method = BDF
  BDF Order = 1
  Timestep Sizes(1) = Real {timestep_size}
  TimeStep Intervals(1) = {timestep_interval}
  Output Intervals(1) = 1
  Max Output Level = 7

  Use Mesh Names = True
End

Constants
  Permittivity of Vacuum = 8.8542e-12
  Permeability of Vacuum = 1.256e-6
End

Body 1
  Name = "Coil"
  Equation = 1
  Material = 1
  Body Force = 1
End

Body Force 1
  Current Density 1 = Variable "time", "CoilCurrent e 1"
      Real LUA "cos(2*3.14*50*tx[0])*tx[1]"
  Current Density 2 = Variable "time", "CoilCurrent e 2"
      Real LUA "cos(2*3.14*50*tx[0])*tx[1]"
  Current Density 3 = Variable "time", "CoilCurrent e 3"
      Real LUA "cos(2*3.14*50*tx[0])*tx[1]"
End

Body 2
  Name = "Air"
  Equation = 2
  Material = 1
End

Body 3
  Name = "Plate"
  Equation = 2
  Material = 2
End

Material 1
  Name = "Air"
  Relative Permeability = Real 1.0
  Relative Permittivity = Real 1.0
End

Material 2
  Name = "Aluminum"
  Electric Conductivity = 3.526e7
  Relative Permittivity = 1.0
  Relative Permeability = 1.0
End

Boundary Condition 1
  Name = "Inf"
  A {{e}} = Real 0.0
  Jfix  = Real 0.0
End

Initial Condition 1
  Name = "Initial state: magnetodynamics"
  A {{e}} = real 0
  A = real 0
  Jfix = real 0.0
End

Solver 1
  Equation = "Coil Solver"

  Exec Solver = "before all"
  Procedure = "CoilSolver" "CoilSolver"
  Coil Closed = Logical True
  Desired Coil Current = Real -2742

  Normalize Coil Current = Logical True
  Narrow Interface = Logical True
  Save Coil Set = Logical False
  Save Coil Index = Logical False
  Calculate Nodal Fields = Logical True
  Calculate Elemental Fields = Logical True

  Linear System Solver = Iterative
  Linear System Iterative Method = idrs
  Linear System Convergence Tolerance = 1.e-08
  Linear System preconditioning = ILU0
  Linear System Max Iterations = 3000
  Linear System Residual Output = 1
  Idrs Parameter = 4

  Nonlinear System Consistent Norm = True

  Coil Normal(3) = Real 0. 0. 1.
End

Solver 2
  Equation = "MGDynamics Transient"
  Procedure = "MagnetoDynamics" "WhitneyAVSolver"
  Variable = "A"

  NonLinear System Max Iterations = 1
  NonLinear System Relaxation Factor = 1
  Nonlinear System Consistent Norm = True

  Linear System Solver = Iterative
  Linear System Iterative Method = bicgstabl
  Linear System GCR Restart = 400
  Linear System Convergence Tolerance = 1.e-07

  Linear System preconditioning = none
  Linear System Max Iterations = 3000
  Linear System Residual Output = 10
  Idrs Parameter = 4
  BicgstabL polynomial degree = 6
  Steady State Convergence Tolerance = 1e-06

  Fix Input Current Density = Logical True

  jfix: Linear System Solver = Iterative
  jfix: Linear System Iterative Method = BiCGStabl
  jfix: Linear System Convergence Tolerance = 1.0e-10
  jfix: Linear System preconditioning = ILU0
  jfix: Linear System Max Iterations = 3000
  jfix: Linear System Residual Output = 10
End

Solver 3
  Equation = "MGDynamicsCalc"
  Procedure = "MagnetoDynamics" "MagnetoDynamicsCalcFields"

  Potential Variable = String "A"
  Steady State Convergence Tolerance = 1.0e-6
  Nonlinear System Consistent Norm = True

  Linear System Solver = Iterative
  Linear System Symmetric = True
  Linear System Iterative Method = CG
  Linear System Max Iterations = 5000
  Linear System Convergence Tolerance = 1.0e-8
  Linear System Preconditioning = ILU0
  Linear System Abort Not Converged = False
  Linear System Residual Output = 10

  Calculate Current Density = Logical True
  Calculate Nodal Fields = False
  Calculate Elemental Fields = True
End

Solver 4
  Equation = String "ResultOutput"
  Procedure = "ResultOutputSolve" "ResultOutputSolver"
  Output File Name = "transient"
  Discontinuous Bodies = Logical True
  Vtu Format = Logical True
  Save Geometry Ids = Logical True
  Save Bulk Only = Logical True
End

Equation 1
  Name = "MagDyn Coil Only"
  Active Solvers(4) = 1 2 3 4
End

Equation 2
  Name = "MagDyn in Plate + Air"
  Active Solvers(3) = 2 3 4
End
"""

    sif_path = working_dir / sif_name
    sif_path.write_text(sif_content, encoding="utf-8")
    return sif_path


# ---------------------------------------------------------------------------
# ELMERSOLVER_STARTINFO writer
# ---------------------------------------------------------------------------

def write_startinfo(working_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    path = working_dir / "ELMERSOLVER_STARTINFO"
    path.write_text(f"{sif_name}\n1\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Mesh copy helper
# ---------------------------------------------------------------------------

def copy_team7_mesh(working_dir: Path, mesh_source_dir: Path | None = None) -> list[str]:
    """
    Copy the TEAM7 Elmer mesh files into working_dir/TEAM7/.

    Elmer expects the mesh in a subdirectory named 'TEAM7' because the SIF
    contains: Mesh DB "." "TEAM7"

    Returns list of copied file names.
    """
    src = mesh_source_dir if mesh_source_dir else TEAM7_MESH_SOURCE
    dest = working_dir / "TEAM7"
    dest.mkdir(parents=True, exist_ok=True)

    copied = []
    for f in src.glob("mesh.*"):
        shutil.copy2(f, dest / f.name)
        copied.append(f.name)

    # Also copy mesh.names if present (used by 'Use Mesh Names = True')
    names_file = src / "mesh.names"
    if names_file.exists():
        shutil.copy2(names_file, dest / "mesh.names")
        if "mesh.names" not in copied:
            copied.append("mesh.names")

    # Copy entities.sif if present
    entities_file = src / "entities.sif"
    if entities_file.exists():
        shutil.copy2(entities_file, dest / "entities.sif")

    return copied


# ---------------------------------------------------------------------------
# Solver runner
# ---------------------------------------------------------------------------

def run_team7(working_dir: Path, timeout: int = 600) -> dict[str, Any]:
    """
    Execute ElmerSolver in working_dir.

    TEAM7 runs 16 transient timesteps with 3 solvers (CoilSolver + WhitneyAV +
    CalcFields) — expect 2–10 minutes depending on hardware.

    Returns dict with: converged, elapsed_seconds, returncode, log_snippet.
    """
    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    existing_path = env.get("PATH", "")
    elmer_bin_str = str(ELMER_BIN)
    if elmer_bin_str not in existing_path:
        env["PATH"] = elmer_bin_str + os.pathsep + existing_path

    t0 = time.time()
    try:
        proc = subprocess.run(
            [str(ELMER_SOLVER)],
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "converged": False,
            "elapsed_seconds": timeout,
            "returncode": -1,
            "log_snippet": f"Solver timed out after {timeout}s",
        }

    elapsed = round(time.time() - t0, 2)
    stdout = proc.stdout + proc.stderr
    converged = "ALL DONE" in stdout

    return {
        "converged": converged,
        "elapsed_seconds": elapsed,
        "returncode": proc.returncode,
        "log_snippet": stdout[-3000:],
    }


# ---------------------------------------------------------------------------
# VTU result parser — magnetic flux density Bz
# ---------------------------------------------------------------------------

def _parse_vtu_appended(vtu_path: Path, field_name: str) -> list[float]:
    """
    Parse a scalar or vector field from a VTU file that uses
    format="appended" encoding="raw" (raw binary blob after XML header).

    This is what ElmerSolver produces for TEAM7 results.

    The XML header contains DataArray elements with:
      - Name attribute (field name)
      - NumberOfComponents (1 or 3)
      - offset attribute (byte offset into the appended blob)
      - type attribute (Float64 typically)

    Each data chunk in the blob is: [uint32 n_bytes] [n_bytes of floats]

    For 3-component vectors, returns the Z-component (index 2).
    """
    import xml.etree.ElementTree as ET

    # Read as bytes to preserve binary data
    raw_bytes = vtu_path.read_bytes()

    # Find the XML header (everything up to <AppendedData ...>)
    # The appended blob starts after the underscore '_' that follows <AppendedData encoding="raw">
    appended_marker = b"<AppendedData"
    app_start = raw_bytes.find(appended_marker)
    if app_start == -1:
        return []

    # Find the underscore that marks start of binary data
    underscore_pos = raw_bytes.find(b"_", app_start)
    if underscore_pos == -1:
        return []
    blob_start = underscore_pos + 1  # binary data starts right after '_'

    # Parse XML header (up to AppendedData tag)
    try:
        xml_header = raw_bytes[:app_start].decode("utf-8", errors="replace")
        # Close unclosed tags to make valid XML
        xml_header += "<AppendedData/></UnstructuredGrid></VTKFile>"
        root = ET.fromstring(xml_header)
    except ET.ParseError:
        # Try with just the piece header
        try:
            header_end = raw_bytes.find(b"</Piece>")
            if header_end == -1:
                return []
            xml_str = raw_bytes[:header_end + 8].decode("utf-8", errors="replace")
            xml_str += "</UnstructuredGrid></VTKFile>"
            root = ET.fromstring(xml_str)
        except Exception:
            return []

    # Find the DataArray matching field_name
    def find_array(root: ET.Element, name: str) -> ET.Element | None:
        for elem in root.iter("DataArray"):
            arr_name = elem.get("Name", "").lower().strip()
            if arr_name == name.lower().strip():
                return elem
        return None

    elem = find_array(root, field_name)
    if elem is None:
        return []

    fmt = elem.get("format", "ascii")
    if fmt != "appended":
        return []

    offset = int(elem.get("offset", "0"))
    n_comp = int(elem.get("NumberOfComponents", "1"))
    dtype_str = elem.get("type", "Float64")
    dtype_size = 8 if "64" in dtype_str else 4
    dtype_fmt = "d" if "64" in dtype_str else "f"

    # Jump to the data block: blob_start + offset
    data_pos = blob_start + offset

    # First 4 bytes = uint32 giving n_bytes of data that follow
    if data_pos + 4 > len(raw_bytes):
        return []
    n_bytes = struct.unpack_from("<I", raw_bytes, data_pos)[0]
    data_pos += 4

    n_values = n_bytes // dtype_size
    if data_pos + n_bytes > len(raw_bytes):
        return []

    values = list(struct.unpack_from(f"<{n_values}{dtype_fmt}", raw_bytes, data_pos))

    if n_comp == 3:
        # Return Z component (index 2)
        return [values[i * 3 + 2] for i in range(len(values) // 3)]
    return values


def get_bz_stats(working_dir: Path) -> dict[str, Any]:
    """
    Read the last VTU file produced by the TEAM7 simulation and return
    statistics for the magnetic flux density Z-component (Bz).

    Elmer writes:  transient_t<N>.vtu  in  working_dir/res/
    Field names in the VTU (appended raw binary format):
      "magnetic flux density e" — elemental vector field (3 components)

    Returns: max_bz, min_bz, mean_bz, abs_max_bz, node_count, vtu_file.
    """
    import xml.etree.ElementTree as ET

    res_dir = working_dir / "res"
    if not res_dir.exists():
        res_dir = working_dir

    vtu_files = sorted(res_dir.glob("transient_t*.vtu"))
    if not vtu_files:
        vtu_files = sorted(working_dir.glob("transient_t*.vtu"))
    if not vtu_files:
        raise RuntimeError(
            f"No transient_t*.vtu files found in {res_dir} or {working_dir}"
        )

    last_vtu = vtu_files[-1]

    # Elmer TEAM7 VTU: "magnetic flux density e" is a 3-component vector
    # _parse_vtu_appended returns Z-component for 3-comp fields
    candidate_names = [
        "magnetic flux density e",
        "magnetic flux density",
        "magnetic flux density 3",
    ]

    bz_values: list[float] = []
    field_used = ""
    for fname in candidate_names:
        bz_values = _parse_vtu_appended(last_vtu, fname)
        if bz_values:
            field_used = fname
            break

    if not bz_values:
        # Inspect what fields actually exist
        try:
            raw = last_vtu.read_bytes()
            app_start = raw.find(b"<AppendedData")
            xml_str = raw[:app_start].decode("utf-8", errors="replace") + "<AppendedData/></UnstructuredGrid></VTKFile>"
            root = ET.fromstring(xml_str)
            available = [e.get("Name", "") for e in root.iter("DataArray")]
        except Exception:
            available = []
        return {
            "error": "Bz field not found in VTU — check available_fields",
            "vtu_file": str(last_vtu),
            "available_fields": available,
            "node_count": 0,
        }

    return {
        "max_bz": max(bz_values),
        "min_bz": min(bz_values),
        "mean_bz": sum(bz_values) / len(bz_values),
        "abs_max_bz": max(abs(v) for v in bz_values),
        "node_count": len(bz_values),
        "field_name": field_used,
        "vtu_file": str(last_vtu),
        "vtu_count": len(vtu_files),
    }
