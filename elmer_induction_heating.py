"""
Elmer Tutorial 16 — Induction Heating of a Graphite Crucible.

Physics: Coupled MagnetoDynamics2D (eddy currents) + Heat equation.
An induction coil heats a graphite crucible by eddy currents.

Mesh: C:\Elmer\tutorials\tutorials-GUI-files\InductionHeatingGUI\
Reference SIF: case.sif in that directory.
"""

from __future__ import annotations

import os
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


# ---------------------------------------------------------------------------
# SIF writer
# ---------------------------------------------------------------------------

def write_induction_heating_sif(work_dir: Path, **kwargs) -> Path:
    """
    Write case.sif for the induction heating tutorial (Tutorial 16).

    Matches the reference case.sif exactly:
    - Axi Symmetric coordinate system
    - Steady-state simulation
    - MagnetoDynamics2D harmonic solver (Solver 1)
    - MagnetoDynamics2DPost BSolver (Solver 2)
    - 6 bodies (air, graphite, insulation, powder, coil, air2)
    - Body Force on body 5 (coil): CurrentDensity 2.5e5
    - Farfield BC on tags 24 & 25

    kwargs can override: angular_frequency, current_density, coil_body,
    farfield_tags, graphite_body, insulation_body, powder_body.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    angular_frequency = kwargs.get("angular_frequency", 50.0e3)
    current_density = kwargs.get("current_density", 2.5e5)
    coil_body = kwargs.get("coil_body", 5)
    farfield_tags = kwargs.get("farfield_tags", [24, 25])
    far_tag_str = " ".join(str(t) for t in farfield_tags)
    n_far = len(farfield_tags)

    sif = f"""Header
  CHECK KEYWORDS Warn
  Mesh DB "." "."
  Include Path ""
  Results Directory ""
End

Simulation
  Max Output Level = 5
  Coordinate System = Axi Symmetric
  Coordinate Mapping(3) = 1 2 3
  Simulation Type = Steady state
  Steady State Max Iterations = 1
  Output Intervals = 1
  Timestepping Method = BDF
  BDF Order = 1
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
  Name = "Body Property 1"
  Equation = 1
  Material = 3
End

Body 2
  Target Bodies(1) = 2
  Name = "Body Property 2"
  Equation = 1
  Material = 2
End

Body 3
  Target Bodies(1) = 3
  Name = "Body Property 3"
  Equation = 1
  Material = 4
End

Body 4
  Target Bodies(1) = 4
  Name = "Body Property 4"
  Equation = 1
  Material = 1
End

Body 5
  Target Bodies(1) = {coil_body}
  Name = "Body Property 5"
  Equation = 1
  Material = 1
  Body Force = 1
End

Body 6
  Target Bodies(1) = 6
  Name = "Body Property 6"
  Equation = 1
  Material = 1
End

Solver 2
  Equation = MgDyn2DPost
  Calculate Joule Heating = True
  Procedure = "MagnetoDynamics2D" "BSolver"
  Target Variable Complex = True
  Exec Solver = Always
  Stabilize = True
  Bubbles = False
  Lumped Mass Matrix = False
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

Solver 1
  Equation = MgDyn2DHarmonic
  Variable = Potential[Potential Re:1 Potential:1]
  Procedure = "MagnetoDynamics2D" "MagnetoDynamics2DHarmonic"
  Exec Solver = Always
  Stabilize = True
  Bubbles = False
  Lumped Mass Matrix = False
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
  Name = "Induction"
  Angular Frequency = {angular_frequency}
  Active Solvers(2) = 2 1
End

Material 1
  Name = "Air"
  Electric Conductivity = 0.0
  Relative Permeability = 1.0
End

Material 2
  Name = "Graphite"
  Relative Permeability = 1.0
  Electric Conductivity = 2.0e4
End

Material 3
  Name = "Insulation"
  Electric Conductivity = 2.0e3
  Relative Permeability = 1.0
End

Material 4
  Name = "Powder"
  Electric Conductivity = 1.0e4
  Relative Permeability = 1.0
End

Body Force 1
  Name = "CurrentSource"
  Current Density = {current_density}
End

Boundary Condition 1
  Target Boundaries({n_far}) = {far_tag_str}
  Name = "Farfield"
  Infinity BC = True
End
"""

    sif_path = work_dir / "case.sif"
    sif_path.write_text(sif, encoding="utf-8")
    return sif_path


# ---------------------------------------------------------------------------
# ELMERSOLVER_STARTINFO writer
# ---------------------------------------------------------------------------

def write_startinfo(work_dir: Path) -> Path:
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    work_dir = Path(work_dir)
    si = work_dir / "ELMERSOLVER_STARTINFO"
    si.write_text("case.sif\n1\n", encoding="utf-8")
    return si


# ---------------------------------------------------------------------------
# Solver runner
# ---------------------------------------------------------------------------

def run_induction_heating(work_dir: Path, timeout: int = 300) -> dict:
    """
    Run ElmerSolver in work_dir.
    Returns dict with returncode, stdout, stderr, converged.
    """
    work_dir = Path(work_dir)
    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    existing_path = env.get("PATH", "")
    elmer_bin_str = str(ELMER_BIN)
    if elmer_bin_str not in existing_path:
        env["PATH"] = elmer_bin_str + os.pathsep + existing_path

    proc = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    combined = proc.stdout + proc.stderr
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "converged": "ALL DONE" in combined,
    }


# ---------------------------------------------------------------------------
# VTU parser — binary appended format
# ---------------------------------------------------------------------------

def _read_vtu_xml_root(vtu_path: Path):
    """
    Parse a VTK XML (.vtu) file that may contain raw binary appended data.
    The binary section corrupts the XML parser, so we strip it and parse only
    the XML header. Returns (ET.Element root, raw_bytes_or_None).
    """
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
    """
    Extract a named scalar (or vector magnitude) field from a VTK XML (.vtu) file.
    Handles both ASCII inline and raw-binary appended formats.
    Returns a list of per-node float values.
    """
    root, binary_data = _read_vtu_xml_root(vtu_path)

    # Collect all DataArray elements
    all_arrays = root.findall(".//" + "DataArray")

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
            # Return magnitude for vector fields
            result = []
            for i in range(0, len(raw_vals), n_components):
                vec = raw_vals[i:i + n_components]
                result.append(sum(v * v for v in vec) ** 0.5)
            return result
        return raw_vals

    # Binary appended format
    if binary_data is None:
        raise RuntimeError(f"Expected binary data section in {vtu_path.name} but found none.")

    offset = int(target.get("offset", "0"))
    # The first 4 or 8 bytes at offset encode the block byte length
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


def get_temperature_stats(work_dir: Path) -> dict:
    """
    Read the most-recent VTU file in work_dir and extract Joule Heating
    (or Temperature if available) field statistics.

    Returns dict with: max_value, min_value, mean_value, node_count, field_name, vtu_file.
    """
    work_dir = Path(work_dir)
    vtu_files = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
    if not vtu_files:
        raise RuntimeError(f"No .vtu result files found in {work_dir}")

    vtu_path = vtu_files[-1]

    # Try Joule Heating first (the key output of this tutorial), then Temperature
    # Note: Elmer writes lowercase field names in VTU files
    for field in ["joule heating", "joule field", "potential re", "Joule Heating", "Temperature"]:
        try:
            values = _parse_vtu_field(vtu_path, field)
            if values:
                return {
                    "field_name": field,
                    "max_value": max(values),
                    "min_value": min(values),
                    "mean_value": sum(values) / len(values),
                    "node_count": len(values),
                    "vtu_file": vtu_path.name,
                }
        except RuntimeError:
            continue

    # Last resort: list available fields
    root, _ = _read_vtu_xml_root(vtu_path)
    available = [da.get("Name") for da in root.findall(".//DataArray")]
    raise RuntimeError(
        f"Could not find any expected field in {vtu_path.name}. "
        f"Available fields: {available}"
    )
