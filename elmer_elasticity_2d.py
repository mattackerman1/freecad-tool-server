"""
Elmer FEM solver integration for Tutorial 6: 2D Linear Elasticity (loaded elastic beam).

Physics: 2D linear elasticity, steady-state.
Geometry: 1m x 0.1m iron beam, clamped at one end, linearly increasing load on top edge.
"""

from __future__ import annotations

import math
import os
import subprocess
import time
from pathlib import Path

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


def write_elasticity_2d_sif(
    work_dir: Path,
    *,
    poisson_ratio: float = 0.29,
    youngs_modulus: float = 193.053e9,
    density: float = 7870.0,
    wall_bc_tag: int = 4,
    load_bc_tag: int = 3,
    force_magnitude: float = -1.0e7,
    plane_stress: bool = True,
    sif_name: str = "case.sif",
) -> Path:
    """Write a 2D linear elasticity .sif file for the loaded beam tutorial."""
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
    s("  Equation = Linear elasticity")
    s('  Procedure = "StressSolve" "StressSolver"')
    s("  Variable = -dofs 2 Displacement")
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
    s('  Name = "Elasticity"')
    s(f"  Plane Stress = {'True' if plane_stress else 'False'}")
    s("  Active Solvers(1) = 1")
    s("End")
    s()
    s("Material 1")
    s('  Name = "Iron (generic)"')
    s("  Sound speed = 5000.0")
    s("  Heat Capacity = 449.0")
    s("  Mesh Poisson ratio = 0.29")
    s(f"  Poisson ratio = {poisson_ratio}")
    s("  Heat Conductivity = 80.2")
    s("  Heat expansion Coefficient = 11.8e-6")
    s(f"  Youngs modulus = {youngs_modulus}")
    s(f"  Density = {density}")
    s("End")
    s()
    s(f"Boundary Condition 1")
    s(f"  Target Boundaries(1) = {wall_bc_tag}")
    s('  Name = "Wall"')
    s("  Displacement 2 = 0.0")
    s("  Displacement 1 = 0.0")
    s("End")
    s()
    s(f"Boundary Condition 2")
    s(f"  Target Boundaries(1) = {load_bc_tag}")
    s('  Name = "Top"')
    s(f"  Force 2 = Variable Coordinate 1; Real; 0 0; 1 {force_magnitude}; End")
    s("End")
    s()

    sif_path = work_dir / sif_name
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO pointing to the SIF file."""
    (work_dir / "ELMERSOLVER_STARTINFO").write_text(f"{sif_name}\n1\n", encoding="utf-8")


def run_elasticity(work_dir: Path, timeout_seconds: int = 300) -> dict:
    """Run ElmerSolver in work_dir and return structured result."""
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
        timeout=timeout_seconds,
        env=env,
    )
    elapsed = time.time() - t0

    stdout = result.stdout + result.stderr

    return {
        "returncode": result.returncode,
        "stdout": stdout,
        "stderr": result.stderr,
        "elapsed_seconds": round(elapsed, 2),
    }


def get_displacement_stats(work_dir: Path) -> dict:
    """
    Read case_t0001.vtu (or latest .vtu), extract 'Displacement' field (2-component),
    and return max_magnitude_m plus per-component min/max.
    """
    import struct
    import xml.etree.ElementTree as ET

    # Find the VTU file
    vtu_candidates = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
    if not vtu_candidates:
        raise RuntimeError(f"No .vtu result files found in {work_dir}")
    vtu_path = vtu_candidates[-1]

    # Use the same binary-appended VTU parser pattern as elmer_solver.py
    raw = vtu_path.read_bytes()
    marker = b'<AppendedData encoding="raw">'
    idx = raw.find(marker)
    if idx == -1:
        root = ET.fromstring(raw.decode("utf-8", errors="replace"))
        binary_data = None
    else:
        header_bytes = raw[: idx + len(marker)]
        after_marker = raw[idx + len(marker):]
        underscore_pos = after_marker.find(b"_")
        if underscore_pos == -1:
            root = ET.fromstring(raw.decode("utf-8", errors="replace"))
            binary_data = None
        else:
            binary_data = after_marker[underscore_pos + 1:]
            xml_str = header_bytes.decode("utf-8", errors="replace") + "\n_</AppendedData>\n</VTKFile>"
            root = ET.fromstring(xml_str)

    # Find the Displacement DataArray
    displacement_values: list[float] | None = None
    n_components = 2

    for piece in root.iter("Piece"):
        point_data = piece.find("PointData")
        if point_data is None:
            continue
        for da in point_data.findall("DataArray"):
            name = da.get("Name", "")
            if name.lower() != "displacement":
                continue
            n_components = int(da.get("NumberOfComponents", 2))
            fmt = da.get("format", "ascii")
            if fmt == "ascii":
                text = (da.text or "").strip()
                displacement_values = [float(x) for x in text.split() if x]
            elif fmt == "appended" and binary_data is not None:
                offset = int(da.get("offset", 0))
                dtype_str = da.get("type", "Float64")
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
                displacement_values = [float(v) for v in struct.unpack_from(f"<{n_vals}{pack_char}", seg, 4)]
            break
        if displacement_values is not None:
            break

    if displacement_values is None:
        # List available fields for debugging
        fields = []
        for piece in root.iter("Piece"):
            pd = piece.find("PointData")
            if pd is not None:
                fields.extend(da.get("Name", "") for da in pd.findall("DataArray"))
        raise RuntimeError(
            f"'Displacement' field not found in {vtu_path.name}. Available: {fields}"
        )

    # displacement_values is interleaved: [u1_node0, u2_node0, u1_node1, u2_node1, ...]
    n_nodes = len(displacement_values) // n_components
    magnitudes = []
    u1_vals = []
    u2_vals = []

    for i in range(n_nodes):
        u1 = displacement_values[i * n_components]
        u2 = displacement_values[i * n_components + 1]
        u1_vals.append(u1)
        u2_vals.append(u2)
        magnitudes.append(math.sqrt(u1 * u1 + u2 * u2))

    return {
        "max_magnitude_m": max(magnitudes),
        "min_x": min(u1_vals),
        "max_x": max(u1_vals),
        "min_y": min(u2_vals),
        "max_y": max(u2_vals),
        "node_count": n_nodes,
        "vtu_file": str(vtu_path),
    }
