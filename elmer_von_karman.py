"""
Elmer FEM — Tutorial 23: Von Karman vortex street (transient Navier-Stokes around a cylinder).

Functions:
  write_von_karman_sif  — write case.sif matching the reference VonKarmanGUI/case.sif
  write_startinfo       — write ELMERSOLVER_STARTINFO (UTF-8 no BOM)
  run_von_karman        — run ElmerSolver subprocess; returns dict with returncode/stdout/stderr
  get_vortex_stats      — parse last output VTU, return max velocity magnitude and max pressure
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


# ---------------------------------------------------------------------------
# SIF writer — matches VonKarmanGUI/case.sif exactly
# ---------------------------------------------------------------------------

def write_von_karman_sif(
    work_dir: str | Path,
    *,
    timestep_intervals: int = 200,
    timestep_size_expr: str = "$8.0/200",
    density: float = 1.0,
    viscosity: float = 0.001,
    inlet_bc_tag: int = 1,
    outlet_bc_tag: int = 2,
    wall_bc_tags: list[int] | None = None,
    inlet_velocity_expr: str = "4*1.5*tx*(0.41-tx)/0.41^2",
    **kwargs,
) -> Path:
    """
    Write case.sif for the Von Karman vortex street simulation.

    The reference case (VonKarmanGUI/case.sif) is a transient incompressible
    Navier-Stokes simulation around a cylinder in a channel:
      - 200 timesteps of dt = 8/200 s
      - Parabolic inlet: Vx = 4*1.5*y*(0.41-y)/0.41^2  (max ~1.5 m/s at y=0.205)
      - No-slip on walls (boundary tags 3 and 4) and cylinder surface
      - Zero normal velocity at outlet (boundary tag 2)
      - BDF2 time integration

    Returns the path to the written SIF file.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if wall_bc_tags is None:
        wall_bc_tags = [3, 4]

    wall_tag_str = " ".join(str(t) for t in wall_bc_tags)
    n_wall_tags = len(wall_bc_tags)

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
    s("  Max Output Level = 4")
    s("  Coordinate System = Cartesian")
    s("  Coordinate Mapping(3) = 1 2 3")
    s("  Simulation Type = Transient")
    s("  Steady State Max Iterations = 1")
    s("  Output Intervals(1) = 1")
    s(f"  Timestep intervals(1) = {timestep_intervals}")
    s(f"  Timestep Sizes(1) = {timestep_size_expr}")
    s("  Timestepping Method = BDF")
    s("  BDF Order = 2")
    s("  Solver Input File = case.sif")
    s("  Post File = case.vtu")
    s("End")
    s()
    s("Constants")
    s("  Gravity(4) = 0 -1 0 9.82")
    s("  Stefan Boltzmann = 5.67e-08")
    s("  Permittivity of Vacuum = 8.8542e-12")
    s("  Permeability of Vacuum = 1.25663706e-6")
    s("  Boltzmann Constant = 1.3807e-23")
    s("  Unit Charge = 1.602e-19")
    s("End")
    s()
    s("Body 1")
    s("  Target Bodies(1) = 1")
    s('  Name = "Body Property 1"')
    s("  Equation = 1")
    s("  Material = 1")
    s("End")
    s()
    s("Solver 1")
    s("  Equation = Navier-Stokes")
    s("  Variable = Flow Solution[Velocity:2 Pressure:1]")
    s('  Procedure = "FlowSolve" "FlowSolver"')
    s("  Exec Solver = Always")
    s("  Stabilize = True")
    s("  Optimize Bandwidth = True")
    s("  Steady State Convergence Tolerance = 1.0e-5")
    s("  Nonlinear System Convergence Tolerance = 1.0e-4")
    s("  Nonlinear System Max Iterations = 20")
    s("  Nonlinear System Newton After Iterations = 3")
    s("  Nonlinear System Newton After Tolerance = 1.0e-3")
    s("  Nonlinear System Relaxation Factor = 1")
    s("  Linear System Solver = Iterative")
    s("  Linear System Iterative Method = BiCGStab")
    s("  Linear System Max Iterations = 500")
    s("  Linear System Convergence Tolerance = 1.0e-6")
    s("  BiCGstabl polynomial degree = 2")
    s("  Linear System Preconditioning = ILU0")
    s("  Linear System ILUT Tolerance = 1.0e-3")
    s("  Linear System Abort Not Converged = False")
    s("  Linear System Residual Output = 1")
    s("  Linear System Precondition Recompute = 1")
    s("End")
    s()
    s("Equation 1")
    s('  Name = "Navier-Stokes"')
    s("  Active Solvers(1) = 1")
    s("End")
    s()
    s("Material 1")
    s('  Name = "Ideal"')
    s(f"  Viscosity = {viscosity}")
    s(f"  Density = {density}")
    s("End")
    s()
    s("Boundary Condition 1")
    s(f"  Target Boundaries(1) = {inlet_bc_tag} ")
    s('  Name = "Inlet"')
    s(f"  Velocity 1 = Variable Coordinate 2; Real MATC \"{inlet_velocity_expr}\"")
    s("  Velocity 2 = 0.0")
    s("End")
    s()
    s("Boundary Condition 2")
    s(f"  Target Boundaries({n_wall_tags}) = {wall_tag_str} ")
    s('  Name = "Walls"')
    s("  Velocity 2 = 0.0")
    s("  Velocity 1 = 0.0")
    s("End")
    s()
    s("Boundary Condition 3")
    s(f"  Target Boundaries(1) = {outlet_bc_tag} ")
    s('  Name = "Outlet"')
    s("  Velocity 2 = 0.0")
    s("End")
    s()

    sif_path = work_dir / "case.sif"
    sif_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sif_path


# ---------------------------------------------------------------------------
# ELMERSOLVER_STARTINFO
# ---------------------------------------------------------------------------

def write_startinfo(work_dir: str | Path) -> Path:
    """Write ELMERSOLVER_STARTINFO pointing to case.sif (UTF-8, no BOM)."""
    work_dir = Path(work_dir)
    p = work_dir / "ELMERSOLVER_STARTINFO"
    p.write_text("case.sif\n1\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Run solver
# ---------------------------------------------------------------------------

def run_von_karman(work_dir: str | Path, timeout: int = 300) -> dict:
    """
    Run ElmerSolver in work_dir for the Von Karman case.

    Returns dict with keys: returncode, stdout, stderr, converged, elapsed_seconds.
    """
    work_dir = Path(work_dir)
    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    existing_path = env.get("PATH", "")
    if str(ELMER_BIN) not in existing_path:
        env["PATH"] = str(ELMER_BIN) + os.pathsep + existing_path

    t0 = time.time()
    try:
        proc = subprocess.run(
            [str(ELMER_SOLVER)],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = round(time.time() - t0, 2)
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return {
            "returncode": -1,
            "converged": False,
            "elapsed_seconds": elapsed,
            "stdout": stdout,
            "stderr": f"ElmerSolver timed out after {timeout}s\n" + stderr,
        }

    elapsed = round(time.time() - t0, 2)
    converged = "ALL DONE" in proc.stdout or "ALL DONE" in proc.stderr
    return {
        "returncode": proc.returncode,
        "converged": converged,
        "elapsed_seconds": elapsed,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


# ---------------------------------------------------------------------------
# Raw-binary VTU parser
# ---------------------------------------------------------------------------

def _read_vtu_xml_root(vtu_path: Path):
    """Read a VTK XML unstructured grid file; return (root_element, binary_data_or_None)."""
    raw = vtu_path.read_bytes()

    appended_pos = raw.find(b"<AppendedData")
    if appended_pos == -1:
        return ET.fromstring(raw.decode("utf-8", errors="replace")), None

    underscore_pos = raw.find(b"_", appended_pos)
    if underscore_pos == -1:
        return ET.fromstring(raw.decode("utf-8", errors="replace")), None

    header_bytes = raw[:underscore_pos]
    binary_data = raw[underscore_pos + 1:]

    xml_str = header_bytes.decode("utf-8", errors="replace") + "\n_</AppendedData>\n</VTKFile>"
    return ET.fromstring(xml_str), binary_data


def _parse_vtu_field(vtu_path: Path, field_name: str) -> list[float]:
    """Extract a named field from a VTU file. Returns flat per-node float list."""
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

    # Field not found — list available fields for debugging
    available: list[str] = []
    for piece in root.iter("Piece"):
        pd = piece.find("PointData")
        if pd is not None:
            available.extend(da.get("Name", "") for da in pd.findall("DataArray"))
    raise RuntimeError(
        f"Field '{field_name}' not found in {vtu_path.name}. "
        f"Available fields: {available}"
    )


# ---------------------------------------------------------------------------
# Vortex statistics from last VTU output
# ---------------------------------------------------------------------------

def get_vortex_stats(work_dir: str | Path) -> dict:
    """
    Parse the last output VTU file and return max velocity magnitude and max pressure.

    The VTU stores 'Flow Solution' with 3 DOFs per node: [Vx, Vy, P].
    Returns:
      vtu_file           — name of the VTU parsed
      n_nodes            — number of nodes
      max_velocity_magnitude — peak speed (m/s)
      max_velocity_x     — max Vx component
      max_velocity_y     — max |Vy| component (vortex shedding signature)
      min_pressure       — minimum pressure in domain
      max_pressure       — maximum pressure in domain
    """
    work_dir = Path(work_dir)

    # Find the last-written VTU file (transient produces case_t*.vtu files)
    candidates = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
    if not candidates:
        raise RuntimeError(f"No .vtu files found in {work_dir}")
    vtu = candidates[-1]

    # Try field names produced by Elmer's FlowSolver
    raw_data: list[float] | None = None
    vel_field: str | None = None
    for candidate in ("Flow Solution", "velocity", "Velocity"):
        try:
            raw_data = _parse_vtu_field(vtu, candidate)
            vel_field = candidate
            break
        except RuntimeError:
            continue

    if raw_data is None or vel_field is None:
        raise RuntimeError(
            f"Could not find velocity field in {vtu.name}. "
            "Tried: 'Flow Solution', 'velocity', 'Velocity'."
        )

    if vel_field == "Flow Solution":
        # 3 DOFs per node: Vx, Vy, P
        n_nodes = len(raw_data) // 3
        vx = [raw_data[3 * i] for i in range(n_nodes)]
        vy = [raw_data[3 * i + 1] for i in range(n_nodes)]
        p = [raw_data[3 * i + 2] for i in range(n_nodes)]
        p_min = min(p)
        p_max = max(p)
    else:
        # Separate velocity and pressure arrays
        n_comp = len(raw_data)
        n_nodes = n_comp // 3 if n_comp % 3 == 0 else n_comp // 2
        if n_comp % 3 == 0:
            vx = [raw_data[3 * i] for i in range(n_nodes)]
            vy = [raw_data[3 * i + 1] for i in range(n_nodes)]
        else:
            vx = [raw_data[2 * i] for i in range(n_nodes)]
            vy = [raw_data[2 * i + 1] for i in range(n_nodes)]
        try:
            p_raw = _parse_vtu_field(vtu, "pressure")
            p_min = min(p_raw)
            p_max = max(p_raw)
        except RuntimeError:
            p_min = None
            p_max = None

    mags = [(vx[i] ** 2 + vy[i] ** 2) ** 0.5 for i in range(n_nodes)]

    return {
        "vtu_file": vtu.name,
        "n_nodes": n_nodes,
        "max_velocity_magnitude": max(mags),
        "max_velocity_x": max(vx),
        "max_velocity_y": max(abs(v) for v in vy),
        "min_pressure": p_min,
        "max_pressure": p_max,
    }
