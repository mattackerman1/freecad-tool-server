"""
Elmer FEM solver integration for Tutorial 27: Temperature distribution of a toy glacier.

Steady-state heat equation with:
  - Geothermal heat flux at the bottom boundary
  - Fixed temperature (273.15 K) at the glacier surface
  - Adiabatic (zero flux) sides
"""

from __future__ import annotations

import os
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


def write_glacier_heat_sif(
    work_dir: Path,
    *,
    density: float = 910.0,
    heat_conductivity: float = 2.1,
    heat_capacity: float = 2093.0,
    surface_bc_tag: int = 3,
    bottom_bc_tag: int = 1,
    surface_temperature: float = 273.15,
    bottom_heat_flux: float = 0.02,
) -> Path:
    """Write case.sif for the toy glacier steady-state heat simulation."""
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
    s("  Solver Input File = case.sif")
    s("  Post File = case.vtu")
    s("End")
    s()
    s("Constants")
    s("  Gravity(4) = 0 -1 0 9.82")
    s("  Stefan Boltzmann = 5.67e-08")
    s("  Permittivity of Vacuum = 8.85418781e-12")
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
    s("  Equation = Heat Equation")
    s('  Procedure = "HeatSolve" "HeatSolver"')
    s("  Variable = Temperature")
    s("  Exec Solver = Always")
    s("  Stabilize = True")
    s("  Optimize Bandwidth = True")
    s("  Steady State Convergence Tolerance = 1.0e-5")
    s("  Nonlinear System Convergence Tolerance = 1.0e-8")
    s("  Nonlinear System Max Iterations = 1")
    s("  Linear System Solver = Iterative")
    s("  Linear System Iterative Method = BiCGStab")
    s("  Linear System Max Iterations = 500")
    s("  Linear System Convergence Tolerance = 1.0e-8")
    s("  BiCGstabl polynomial degree = 2")
    s("  Linear System Preconditioning = ILU0")
    s("  Linear System Abort Not Converged = False")
    s("  Linear System Residual Output = 10")
    s("End")
    s()
    s("Equation 1")
    s('  Name = "Heat"')
    s("  Active Solvers(1) = 1")
    s("End")
    s()
    s("Material 1")
    s('  Name = "Ice"')
    s(f"  Density = {density}")
    s(f"  Heat Conductivity = {heat_conductivity}")
    s(f"  Heat Capacity = {heat_capacity}")
    s("End")
    s()
    s("Boundary Condition 1")
    s(f"  Target Boundaries(1) = {surface_bc_tag}")
    s('  Name = "Surface"')
    s(f"  Temperature = {surface_temperature}")
    s("End")
    s()
    s("Boundary Condition 2")
    s(f"  Target Boundaries(1) = {bottom_bc_tag}")
    s('  Name = "Bottom"')
    s(f"  Heat Flux = {bottom_heat_flux}")
    s("End")
    s()

    sif_path = work_dir / "case.sif"
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path) -> None:
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    (work_dir / "ELMERSOLVER_STARTINFO").write_text("case.sif\n1\n", encoding="utf-8")


def run_glacier_heat(work_dir: Path, timeout_seconds: int = 300) -> dict:
    """Run ElmerSolver in work_dir and return returncode, stdout, stderr."""
    if not ELMER_SOLVER.exists():
        raise RuntimeError(f"ElmerSolver not found at {ELMER_SOLVER}")

    env = os.environ.copy()
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


def _read_vtu_xml_root(vtu_path: Path):
    """Parse VTK XML (.vtu) file, handling raw binary appended data."""
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
    """Extract a named scalar field from a VTK XML (.vtu) file."""
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

    raise RuntimeError(f"Field '{field_name}' not found in {vtu_path.name}")


def get_temperature_stats(work_dir: Path) -> dict:
    """
    Read case_t0001.vtu and extract Temperature field statistics.
    Returns max_temperature_k, min_temperature_k, mean_temperature_k.
    """
    # Look for case_t0001.vtu first, then fall back to most recent vtu
    vtu_path = work_dir / "case_t0001.vtu"
    if not vtu_path.exists():
        vtu_files = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
        if not vtu_files:
            raise RuntimeError(f"No .vtu result files found in {work_dir}")
        vtu_path = vtu_files[-1]

    values = _parse_vtu_field(vtu_path, "Temperature")
    if not values:
        raise RuntimeError(f"Temperature field has no data in {vtu_path.name}")

    return {
        "max_temperature_k": max(values),
        "min_temperature_k": min(values),
        "mean_temperature_k": sum(values) / len(values),
        "node_count": len(values),
        "vtu_file": str(vtu_path),
    }
