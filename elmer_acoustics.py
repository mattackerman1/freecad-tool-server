"""
Elmer FEM solver integration for Tutorial 17: Helmholtz 2D Acoustic Waves in a Cavity.

Provides:
 1. write_acoustics_sif() - writes case.sif for Helmholtz equation
 2. write_startinfo() - writes ELMERSOLVER_STARTINFO
 3. run_acoustics() - runs ElmerSolver as a subprocess
 4. get_pressure_stats() - parses VTU result and returns pressure magnitude stats
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


def write_acoustics_sif(
    work_dir: Path,
    *,
    angular_frequency: float = 628.3,
    sound_speed: float = 343.0,
    density: float = 1.224,
    source_bc_tag: int = 1,
    rigid_bc_tag: int = 2,
    impedance_bc_tag: int = 3,
    wave_flux: float = 1.0,
    wave_impedance: float = -343.0,
    sif_name: str = "case.sif",
) -> Path:
    """Write a Helmholtz acoustic case.sif file."""
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
    s("  Output Intervals(1) = 1")
    s(f"  Solver Input File = {sif_name}")
    s("  Post File = case.vtu")
    s("End")
    s()
    s("Constants")
    s("  Gravity(4) = 0 -1 0 9.82")
    s("  Stefan Boltzmann = 5.670374419e-08")
    s("  Permittivity of Vacuum = 8.85418781e-12")
    s("  Permeability of Vacuum = 1.25663706e-6")
    s("  Boltzmann Constant = 1.380649e-23")
    s("  Unit Charge = 1.6021766e-19")
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
    s("  Equation = Helmholtz Equation")
    s('  Procedure = "HelmholtzSolve" "HelmholtzSolver"')
    s("  Variable = -dofs 2 Pressure Wave")
    s("  Exec Solver = Always")
    s("  Stabilize = True")
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
    s('  Name = "Helmholtz"')
    s(f"  Angular Frequency = {angular_frequency}")
    s("  Convection Velocity 1 = 0.0")
    s("  Convection Velocity 2 = 0.0")
    s("  Active Solvers(1) = 1")
    s("End")
    s()
    s("Material 1")
    s('  Name = "Material 1"')
    s(f"  Sound speed = {sound_speed}")
    s(f"  Density = {density}")
    s("  Sound damping = 0.0")
    s("End")
    s()
    # Source BC (vibrating membrane)
    s("Boundary Condition 1")
    s(f"  Target Boundaries(1) = {source_bc_tag}")
    s('  Name = "Constraint1"')
    s(f"  Wave Flux 1 = {wave_flux}")
    s("  Wave Flux 2 = 0")
    s("End")
    s()
    # Rigid wall BC
    s("Boundary Condition 2")
    s(f"  Target Boundaries(1) = {rigid_bc_tag}")
    s('  Name = "Constraint2"')
    s("  Wave Flux 2 = 0")
    s("  Wave Flux 1 = 0")
    s("End")
    s()
    # Impedance BC (open pipe)
    s("Boundary Condition 3")
    s(f"  Target Boundaries(1) = {impedance_bc_tag}")
    s('  Name = "Constraint3"')
    s(f"  Wave impedance 1 = {wave_impedance}")
    s("  Wave impedance 2 = 0")
    s("End")
    s()

    sif_path = work_dir / sif_name
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO, UTF-8 no BOM."""
    (work_dir / "ELMERSOLVER_STARTINFO").write_text(f"{sif_name}\n1\n", encoding="utf-8")


def run_acoustics(work_dir: Path, timeout_seconds: int = 300) -> dict:
    """Run ElmerSolver in work_dir and return dict with returncode, stdout, stderr."""
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

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "elapsed_seconds": round(elapsed, 2),
        "converged": "ALL DONE" in (result.stdout + result.stderr),
    }


# ---------------------------------------------------------------------------
# VTU parsing (reuse pattern from elmer_solver.py)
# ---------------------------------------------------------------------------

def _read_vtu_xml_root(vtu_path: Path):
    """Parse a VTK XML (.vtu) file that may contain raw binary appended data."""
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
    """Extract a named field from a VTK XML (.vtu) file. Returns flat list of floats."""
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

    # List available fields to help with debugging
    available = []
    for piece in root.iter("Piece"):
        pd = piece.find("PointData")
        if pd is not None:
            available.extend(da.get("Name", "") for da in pd.findall("DataArray"))
    raise RuntimeError(
        f"Field '{field_name}' not found in {vtu_path.name}. "
        f"Available fields: {available}"
    )


def get_pressure_stats(work_dir: Path) -> dict:
    """
    Read case_t0001.vtu and extract 'Pressure Wave' field (2 DOFs: real, imag).
    Returns max_magnitude, min_magnitude, max_real, max_imag.

    For N nodes the field has 2N floats interleaved: [real0, imag0, real1, imag1, ...]
    """
    # Try the standard output file name first, then fall back to most recent vtu
    vtu_path = work_dir / "case_t0001.vtu"
    if not vtu_path.exists():
        vtu_files = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
        if not vtu_files:
            raise RuntimeError(f"No .vtu result files found in {work_dir}")
        vtu_path = vtu_files[-1]

    # "Pressure Wave" is a 2-component vector field
    floats = _parse_vtu_field(vtu_path, "Pressure Wave")

    if len(floats) < 2:
        raise RuntimeError(f"Pressure Wave field has too few values ({len(floats)}) in {vtu_path.name}")

    # Interleaved real/imag: node i → real=floats[2i], imag=floats[2i+1]
    n_nodes = len(floats) // 2
    magnitudes = []
    reals = []
    imags = []
    for i in range(n_nodes):
        real = floats[2 * i]
        imag = floats[2 * i + 1]
        mag = math.sqrt(real * real + imag * imag)
        magnitudes.append(mag)
        reals.append(real)
        imags.append(imag)

    return {
        "max_magnitude": max(magnitudes),
        "min_magnitude": min(magnitudes),
        "mean_magnitude": sum(magnitudes) / len(magnitudes),
        "max_real": max(reals),
        "min_real": min(reals),
        "max_imag": max(imags),
        "min_imag": min(imags),
        "node_count": n_nodes,
        "vtu_file": str(vtu_path),
    }
