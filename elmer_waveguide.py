"""
Elmer FEM solver integration for Tutorial 30: Vector Helmholtz Equation
for electromagnetic wave propagation in a bent 3D waveguide (WaveguideGUI).

Physics: TE10 mode propagation in a rectangular waveguide.
  a = 10 cm (wide dimension), b = 5 cm (narrow), f = 2.5 GHz
  beta0 = sqrt(k0^2 - (pi/a)^2)

The input port is excited by the TE10 mode profile via a Magnetic Boundary
Load; both ports use an absorbing Robin BC with coefficient beta0.
PEC walls impose E re {e} = Real 0.

Provides:
 1. write_sif()        - writes case.sif
 2. write_startinfo()  - writes ELMERSOLVER_STARTINFO
 3. run_solver()       - runs ElmerSolver (timeout=300 s)
 4. get_stats()        - parses VTU output, returns E-field statistics
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

TUTORIAL_MESH_DIR = Path(
    r"C:\Elmer\tutorials\tutorials-GUI-files\WaveguideGUI"
)


def elmer_available() -> bool:
    return ELMER_SOLVER.exists()


def write_sif(
    work_dir: Path,
    *,
    waveguide_a: float = 0.10,
    waveguide_b: float = 0.05,
    frequency: float = 2.5e9,
    relative_permittivity: float = 1.0,
    relative_permeability: float = 1.0,
    port_in_tag: int = 1,
    port_out_tag: int = 2,
    sif_name: str = "case.sif",
) -> Path:
    """
    Write a Vector Helmholtz case.sif for a 3D bent rectangular waveguide
    excited in the TE10 mode.

    Parameters
    ----------
    waveguide_a : float
        Wide dimension of the waveguide cross-section in metres (default 0.10 m).
    waveguide_b : float
        Narrow dimension in metres (default 0.05 m).
    frequency : float
        Operating frequency in Hz (default 2.5 GHz).
    port_in_tag : int
        Boundary tag of the excitation (input) port.
    port_out_tag : int
        Boundary tag of the output (absorbing) port.
    """
    lines: list[str] = []

    def s(line: str = "") -> None:
        lines.append(line)

    # Physical constants (Elmer handles vacuum values but we set them explicitly)
    # omega, k0, kc, beta0 are computed via Elmer's MATC/$ expressions in the SIF

    # ------------------------------------------------------------------ Header
    s("Header")
    s("  CHECK KEYWORDS Warn")
    s('  Mesh DB "." "."')
    s('  Include Path ""')
    s('  Results Directory ""')
    s("End")
    s()
    # --------------------------------------------------------------- Simulation
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
    # --------------------------------------------------------------- Constants
    s("Constants")
    s("  Gravity(4) = 0 -1 0 9.82")
    s("  Stefan Boltzmann = 5.670374419e-08")
    s("  Permittivity of Vacuum = 8.85418781e-12")
    s("  Permeability of Vacuum = 1.25663706e-6")
    s("  Boltzmann Constant = 1.380649e-23")
    s("  Unit Charge = 1.6021766e-19")
    s("End")
    s()
    # -------------------------------------------------------------------- Body
    s("Body 1")
    s("  Target Bodies(1) = 1")
    s('  Name = "Body 1"')
    s("  Equation = 1")
    s("  Material = 1")
    s("End")
    s()
    # ----------------------------------------------------------------- Solver 1 — VectorHelmholtz
    s("Solver 1")
    s("  Equation = Vector Helmholtz Equation")
    s('  Procedure = "VectorHelmholtz" "VectorHelmholtzSolver"')
    s("  Variable = E[E re:1 E im:1]")
    s("  Exec Solver = Always")
    s("  Optimize Bandwidth = True")
    s("  Steady State Convergence Tolerance = 1.0e-8")
    s("  Nonlinear System Convergence Tolerance = 1.0e-8")
    s("  Nonlinear System Max Iterations = 1")
    s("  Linear System Solver = Direct")
    s("  Linear System Direct Method = UMFPack")
    s("  Linear System Abort Not Converged = False")
    s("  Linear System Residual Output = 10")
    s("End")
    s()
    # ----------------------------------------------------------------- Solver 2 — Result Output
    s("Solver 2")
    s("  Equation = Result Output")
    s('  Procedure = "ResultOutputSolve" "ResultOutputSolver"')
    s("  Output File Name = case")
    s("  Vtu Format = True")
    s("  Exec Solver = After Timestep")
    s("End")
    s()
    # --------------------------------------------------------------- Equation
    # MATC / $ variable definitions: waveguide parameters and wave numbers
    s("Equation 1")
    s('  Name = "Vector Helmholtz"')
    s(f"  Angular Frequency = Real $ 2*pi*{frequency:.6e}")
    s("  Active Solvers(2) = 1 2")
    # Free text block with waveguide constants (parsed by Elmer at load time)
    s(f"  $ a = {waveguide_a}")
    s(f"  $ b = {waveguide_b}")
    s("  $ c0 = 1/sqrt(8.854e-12*4*pi*10^-7)")
    s(f"  $ omega = 2*pi*{frequency:.6e}")
    s("  $ k0 = omega/c0")
    s("  $ kc = pi/a")
    s("  $ beta0 = sqrt(k0^2-kc^2)")
    s("End")
    s()
    # --------------------------------------------------------------- Material
    s("Material 1")
    s('  Name = "Air"')
    s(f"  Relative Permittivity = {relative_permittivity}")
    s(f"  Relative Permeability = {relative_permeability}")
    s("End")
    s()
    # ----------------------------------------------- Boundary Conditions
    # PEC walls: E re {e} = Real 0 (tangential E = 0)
    # All boundary tags except port_in and port_out are PEC walls
    pec_tags = [t for t in range(1, 15) if t not in (port_in_tag, port_out_tag)]

    bc_idx = 1
    # --- Input port: Robin BC + TE10 mode excitation via Magnetic Boundary Load
    s(f"Boundary Condition {bc_idx}")
    s(f"  Target Boundaries(1) = {port_in_tag}")
    s('  Name = "Port In"')
    s("  Electric Robin Coefficient im = Real $ beta0")
    # TE10 mode: H_y ~ cos(pi*x/a), which drives H-field through the aperture.
    # The load is proportional to the transverse E-field of the TE10 mode:
    # E_y ~ sin(pi*(x+a/2)/a) with appropriate amplitude.
    s('  Magnetic Boundary Load 2 = Variable Coordinate 1')
    s('    Real MATC "-2*beta0*k0/kc*sin(kc*(tx+a/2))"')
    s("End")
    s()
    bc_idx += 1

    # --- Output port: absorbing Robin BC only (no excitation)
    s(f"Boundary Condition {bc_idx}")
    s(f"  Target Boundaries(1) = {port_out_tag}")
    s('  Name = "Port Out"')
    s("  Electric Robin Coefficient im = Real $ beta0")
    s("End")
    s()
    bc_idx += 1

    # --- PEC walls
    for tag in pec_tags:
        s(f"Boundary Condition {bc_idx}")
        s(f"  Target Boundaries(1) = {tag}")
        s(f'  Name = "PEC Wall {tag}"')
        s("  E re {e} = Real 0")
        s("End")
        s()
        bc_idx += 1

    sif_path = work_dir / sif_name
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO, UTF-8 no BOM."""
    (work_dir / "ELMERSOLVER_STARTINFO").write_text(f"{sif_name}\n1\n", encoding="utf-8")


def run_solver(work_dir: Path, timeout_seconds: int = 300) -> dict:
    """Run ElmerSolver in work_dir and return status dict."""
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
    combined = result.stdout + result.stderr
    converged = "ALL DONE" in combined

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "elapsed_seconds": round(elapsed, 2),
        "converged": converged,
        "log_snippet": combined[-3000:],
    }


# ---------------------------------------------------------------------------
# VTU parsing helpers (raw-binary-appended VTK XML)
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
    """Extract a named scalar or vector field from a VTK XML (.vtu) file."""
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

    # List available fields for debugging
    available: list[str] = []
    for piece in root.iter("Piece"):
        pd = piece.find("PointData")
        if pd is not None:
            available.extend(da.get("Name", "") for da in pd.findall("DataArray"))
    raise RuntimeError(
        f"Field '{field_name}' not found in {vtu_path.name}. "
        f"Available fields: {available}"
    )


def get_stats(work_dir: Path) -> dict:
    """
    Parse the VTU result file and return E-field statistics.

    The VectorHelmholtz solver writes vector fields 'E re' and 'E im',
    each with 3 components per node (Ex, Ey, Ez). Returns max/mean |E|
    plus per-component ranges.
    """
    # Find most recent VTU file
    vtu_path = work_dir / "case_t0001.vtu"
    if not vtu_path.exists():
        vtu_files = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
        if not vtu_files:
            raise RuntimeError(f"No .vtu result files found in {work_dir}")
        vtu_path = vtu_files[-1]

    # Determine available fields
    root, binary_data = _read_vtu_xml_root(vtu_path)
    available: list[str] = []
    for piece in root.iter("Piece"):
        pd = piece.find("PointData")
        if pd is not None:
            available.extend(da.get("Name", "") for da in pd.findall("DataArray"))

    e_re_flat: list[float] = []
    e_im_flat: list[float] = []
    read_error: str = ""

    for field_name, storage in [("E re", e_re_flat), ("E im", e_im_flat)]:
        try:
            vals = _parse_vtu_field(vtu_path, field_name)
            storage.extend(vals)
        except RuntimeError as exc:
            read_error = str(exc)

    if not e_re_flat and not e_im_flat:
        return {
            "vtu_file": str(vtu_path),
            "available_fields": available,
            "error": read_error or "No E-field data found",
        }

    # Each node has 3 components: [Ex, Ey, Ez]
    n_re = len(e_re_flat) // 3 if len(e_re_flat) >= 3 else 0
    n_im = len(e_im_flat) // 3 if len(e_im_flat) >= 3 else 0
    n_nodes = min(n_re or n_im, n_im or n_re)

    magnitudes: list[float] = []
    for i in range(n_nodes):
        re = e_re_flat[3 * i: 3 * i + 3] if e_re_flat else [0.0, 0.0, 0.0]
        im = e_im_flat[3 * i: 3 * i + 3] if e_im_flat else [0.0, 0.0, 0.0]
        mag = math.sqrt(sum(r ** 2 + c ** 2 for r, c in zip(re, im)))
        magnitudes.append(mag)

    if not magnitudes:
        return {
            "vtu_file": str(vtu_path),
            "available_fields": available,
            "warning": "Could not compute E-field magnitudes",
        }

    max_mag = max(magnitudes)
    mean_mag = sum(magnitudes) / len(magnitudes)

    result: dict = {
        "vtu_file": str(vtu_path),
        "node_count": n_nodes,
        "max_e_magnitude": max_mag,
        "mean_e_magnitude": mean_mag,
        "available_fields": available,
    }
    if e_re_flat:
        result["e_re_max"] = max(e_re_flat)
        result["e_re_min"] = min(e_re_flat)
    if e_im_flat:
        result["e_im_max"] = max(e_im_flat)
        result["e_im_min"] = min(e_im_flat)

    return result
