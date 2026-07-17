"""
Elmer FEM solver integration — Tutorial 8: Non-linear Elasticity 3D (Loaded Elastic U-curve).

A U-shaped steel hook is pressed from both ends so the two sides close toward each other.
Transient simulation with large displacements, 20 timesteps x 0.05s = 1 second total.

Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\ElasticHookNonlinear\\
  - 12288 trilinear hex elements, 13585 nodes
  - Boundary tags: 1 (one end, near x=0), 2 (curved middle, free), 3 (other end, x=-2)
  - Mesh is in cm; coordinate_scaling = 0.01 converts to SI meters
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


# ---------------------------------------------------------------------------
# SIF writer
# ---------------------------------------------------------------------------

def write_nonlinear_elasticity_sif(
    work_dir: Path,
    *,
    density: float = 7900.0,
    youngs_modulus: float = 197.0e9,
    poisson_ratio: float = 0.27,
    n_timesteps: int = 20,
    timestep_size: float = 0.05,
    coordinate_scaling: float = 0.01,
    moving_right_bc_tag: int = 1,
    moving_left_bc_tag: int = 3,
    displacement_amplitude: float = 0.006,
    calculate_stresses: bool = True,
) -> Path:
    """Write case.sif for the 3D non-linear elasticity U-hook problem."""
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
    s("  Simulation Type = Transient")
    s("  Steady State Max Iterations = 1")
    s("  Output Intervals = 1")
    s(f"  Timestep intervals = {n_timesteps}")
    s(f"  Timestep Sizes = {timestep_size}")
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
    s("  Equation = Nonlinear elasticity")
    s('  Procedure = "ElasticSolve" "ElasticSolver"')
    s("  Variable = -dofs 3 Displacement")
    s("  Exec Solver = Always")
    s(f"  Calculate Stresses = {'True' if calculate_stresses else 'False'}")
    s(f"  Calculate Principal = {'True' if calculate_stresses else 'False'}")
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
    s("  Linear System Abort Not Converged = False")
    s("  Linear System Residual Output = 10")
    s("  Linear System Precondition Recompute = 1")
    s("End")
    s()
    s("Equation 1")
    s('  Name = "Elasticity"')
    s("  Active Solvers(1) = 1")
    s("End")
    s()
    s("Material 1")
    s('  Name = "Steel"')
    s(f"  Density = {density}")
    s(f"  Youngs modulus = {youngs_modulus}")
    s(f"  Poisson ratio = {poisson_ratio}")
    s("End")
    s()
    s("Boundary Condition 1")
    s(f"  Target Boundaries(1) = {moving_right_bc_tag}")
    s('  Name = "MovingRight"')
    s("  Displacement 2 = 0.0")
    s("  Displacement 3 = 0.0")
    s('  Displacement 1 = Variable "time"')
    s(f'    Real MATC "{displacement_amplitude}*tx"')
    s("End")
    s()
    s("Boundary Condition 2")
    s(f"  Target Boundaries(1) = {moving_left_bc_tag}")
    s('  Name = "MovingLeft"')
    s("  Displacement 2 = 0.0")
    s("  Displacement 3 = 0.0")
    s('  Displacement 1 = Variable "time"')
    s(f'    Real MATC "-{displacement_amplitude}*tx"')
    s("End")
    s()

    sif_path = work_dir / "case.sif"
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> None:
    (work_dir / "ELMERSOLVER_STARTINFO").write_text(f"{sif_name}\n1\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Run ElmerSolver
# ---------------------------------------------------------------------------

def run_nonlinear_elasticity(work_dir: Path, timeout: int = 300) -> dict:
    """Run ElmerSolver in work_dir; return dict with returncode, stdout, stderr."""
    if not ELMER_SOLVER.exists():
        raise RuntimeError(f"ElmerSolver not found at {ELMER_SOLVER}")

    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)

    t0 = time.time()
    result = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    elapsed = time.time() - t0

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "elapsed_seconds": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Parse VTU results
# ---------------------------------------------------------------------------

def _read_vtu_xml_root(vtu_path: Path):
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


def _list_vtu_fields(vtu_path: Path) -> list[str]:
    root, _ = _read_vtu_xml_root(vtu_path)
    fields = []
    for piece in root.iter("Piece"):
        pd = piece.find("PointData")
        if pd is not None:
            fields.extend(da.get("Name", "") for da in pd.findall("DataArray"))
    return fields


def _parse_vtu_field(vtu_path: Path, field_name: str) -> list[float]:
    root, binary_data = _read_vtu_xml_root(vtu_path)
    for piece in root.iter("Piece"):
        point_data = piece.find("PointData")
        if point_data is None:
            continue
        for da in point_data.findall("DataArray"):
            name = da.get("Name", "")
            if name.lower() != field_name.lower():
                continue
            fmt = da.get("format", "ascii")
            if fmt == "ascii":
                text = (da.text or "").strip()
                return [float(x) for x in text.split() if x]
            elif fmt == "appended" and binary_data is not None:
                offset = int(da.get("offset", 0))
                dtype_str = da.get("type", "Float64")
                n_comp = int(da.get("NumberOfComponents", 1))
                dtype_map = {
                    "Float32": ("f", 4),
                    "Float64": ("d", 8),
                    "Int32": ("i", 4),
                    "Int64": ("q", 8),
                }
                pack_char, item_size = dtype_map.get(dtype_str, ("d", 8))
                seg = binary_data[offset:]
                byte_len = struct.unpack_from("<I", seg, 0)[0]
                n_vals = byte_len // item_size
                values = list(struct.unpack_from(f"<{n_vals}{pack_char}", seg, 4))
                return [float(v) for v in values]

    available = _list_vtu_fields(vtu_path)
    raise RuntimeError(
        f"Field '{field_name}' not found in {vtu_path.name}. "
        f"Available fields: {available}"
    )


def get_final_stress_stats(work_dir: Path, n_timesteps: int = 20) -> dict:
    """
    Read the final VTU file and extract von Mises stress statistics.
    Returns max_vonmises_pa, mean_vonmises_pa, and available_fields.
    """
    vtu_name = f"case_t{n_timesteps:04d}.vtu"
    vtu_path = work_dir / vtu_name
    if not vtu_path.exists():
        # Try to find the last available VTU
        vtu_files = sorted(work_dir.glob("case_t*.vtu"))
        if not vtu_files:
            raise RuntimeError(f"No VTU files found in {work_dir}")
        vtu_path = vtu_files[-1]

    available = _list_vtu_fields(vtu_path)

    # Try candidate field names for von Mises stress
    candidates = ["vonmises", "VonMises", "vonmises stress", "von mises stress",
                  "Stress", "stress", "equivalent stress"]
    # Also try displacement magnitude
    stress_field = None
    for cand in candidates:
        if any(f.lower() == cand.lower() for f in available):
            for f in available:
                if f.lower() == cand.lower():
                    stress_field = f
                    break
        if stress_field:
            break

    # If not found by exact name, look for anything with "mises" or "stress"
    if stress_field is None:
        for f in available:
            if "mises" in f.lower() or "vonmis" in f.lower():
                stress_field = f
                break

    result = {
        "vtu_file": str(vtu_path),
        "available_fields": available,
    }

    if stress_field:
        values = _parse_vtu_field(vtu_path, stress_field)
        if values:
            result["stress_field_name"] = stress_field
            result["max_vonmises_pa"] = max(values)
            result["mean_vonmises_pa"] = sum(values) / len(values)

    # Also try to get displacement magnitude
    disp_field = None
    for f in available:
        if "displacement" in f.lower() and "magnitude" in f.lower():
            disp_field = f
            break
    if disp_field is None:
        for f in available:
            if f.lower() in ("displacement", "disp"):
                disp_field = f
                break

    if disp_field:
        dvals = _parse_vtu_field(vtu_path, disp_field)
        if dvals:
            result["displacement_field_name"] = disp_field
            result["max_displacement_m"] = max(abs(v) for v in dvals)

    return result
