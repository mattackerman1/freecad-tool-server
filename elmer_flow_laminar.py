"""
Elmer FEM — Tutorial 19: Navier-Stokes laminar incompressible flow past a step.

Functions:
  inspect_step_boundaries  — parse mesh.nodes + mesh.boundary, return tag centroids
  write_step_flow_sif      — write case.sif for 2D N-S flow
  write_startinfo          — write ELMERSOLVER_STARTINFO
  run_flow                 — run ElmerSolver subprocess
  get_flow_stats           — parse VTU result, return velocity/pressure stats
"""

from __future__ import annotations

import os
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


# ---------------------------------------------------------------------------
# Mesh inspection
# ---------------------------------------------------------------------------

def inspect_step_boundaries(mesh_dir: str | Path) -> dict:
    """
    Read mesh.nodes and mesh.boundary; return per-tag stats.

    Returns dict:
      { tag_int: {centroid_x, centroid_y, n_elements, x_min, x_max, y_min, y_max} }
    """
    mesh_dir = Path(mesh_dir)

    # Parse nodes: format is  node_id  dummy  x  y  [z]
    nodes: dict[str, tuple[float, float]] = {}
    with open(mesh_dir / "mesh.nodes", encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 4:
                nid = parts[0]
                x = float(parts[2])
                y = float(parts[3])
                nodes[nid] = (x, y)

    # Parse boundary: elem_idx tag parent1 parent2 elem_type node1 node2 ...
    tag_data: dict[int, dict] = {}
    with open(mesh_dir / "mesh.boundary", encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 6:
                continue
            tag = int(parts[1])
            if tag not in tag_data:
                tag_data[tag] = {"xs": [], "ys": [], "n_elements": 0}
            tag_data[tag]["n_elements"] += 1
            for nid in parts[5:]:
                if nid in nodes:
                    x, y = nodes[nid]
                    tag_data[tag]["xs"].append(x)
                    tag_data[tag]["ys"].append(y)

    result = {}
    for tag, d in tag_data.items():
        xs = d["xs"]
        ys = d["ys"]
        if not xs:
            continue
        result[tag] = {
            "n_elements": d["n_elements"],
            "centroid_x": sum(xs) / len(xs),
            "centroid_y": sum(ys) / len(ys),
            "x_min": min(xs),
            "x_max": max(xs),
            "y_min": min(ys),
            "y_max": max(ys),
        }
    return result


# ---------------------------------------------------------------------------
# SIF writer
# ---------------------------------------------------------------------------

def write_step_flow_sif(
    work_dir: str | Path,
    *,
    wall_tags: list[int],
    inlet_tag: int,
    outlet_tag: int,
    density: float = 1.0,
    viscosity: float = 0.01,
    max_velocity: float = 1.5,
    inlet_y_min: float = 1.0,
    inlet_y_max: float = 2.0,
    steady_state_max_iter: int = 20,
) -> Path:
    """
    Write case.sif for 2D laminar incompressible Navier-Stokes flow past a step.

    The inlet parabolic profile is:
        Vx = max_velocity * 4*(y - y_min)*(y_max - y) / (y_max - y_min)^2
    which peaks at (y_min + y_max)/2 and gives mean ~ 2/3 * max_velocity.

    For the FlowStep mesh: inlet at x=0, y=[1,2], so y_min=1.0, y_max=2.0.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # Build parabolic MATC expression that gives max_velocity at channel center
    # 4*(tx-y_min)*(y_max-tx)/(y_max-y_min)^2 * max_velocity
    h = inlet_y_max - inlet_y_min
    # MATC expression: 4*max_velocity*(tx-ymin)*(ymax-tx)/h^2
    matc_expr = f"4*{max_velocity}*(tx-{inlet_y_min})*({inlet_y_max}-tx)/({h}^2)"

    # Wall tags as Elmer list
    wall_tag_str = " ".join(str(t) for t in wall_tags)
    n_wall_tags = len(wall_tags)

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
    s(f"  Steady State Max Iterations = {steady_state_max_iter}")
    s("  Output Intervals(1) = 1")
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
    s("  Equation = Navier-Stokes")
    s("  Variable = Flow Solution[Velocity:2 Pressure:1]")
    s('  Procedure = "FlowSolve" "FlowSolver"')
    s("  Exec Solver = Always")
    s("  Stabilize = True")
    s("  Optimize Bandwidth = True")
    s("  Steady State Convergence Tolerance = 1.0e-5")
    s("  Nonlinear System Convergence Tolerance = 1.0e-5")
    s("  Nonlinear System Max Iterations = 20")
    s("  Nonlinear System Newton After Iterations = 3")
    s("  Nonlinear System Newton After Tolerance = 1.0e-3")
    s("  Nonlinear System Relaxation Factor = 1")
    s("  Linear System Solver = Iterative")
    s("  Linear System Iterative Method = BiCGStab")
    s("  Linear System Max Iterations = 500")
    s("  Linear System Convergence Tolerance = 1.0e-8")
    s("  Linear System Preconditioning = ILU0")
    s("  Linear System Abort Not Converged = False")
    s("  Linear System Residual Output = 10")
    s("End")
    s()
    s("Equation 1")
    s('  Name = "Navier-Stokes"')
    s("  Active Solvers(1) = 1")
    s("End")
    s()
    s("Material 1")
    s('  Name = "Fluid"')
    s(f"  Density = {density}")
    s(f"  Viscosity = {viscosity}")
    s("  Compressibility Model = Incompressible")
    s("End")
    s()
    # Boundary condition 1: Walls (no-slip)
    s("Boundary Condition 1")
    s(f"  Target Boundaries({n_wall_tags}) = {wall_tag_str}")
    s('  Name = "Walls"')
    s("  Velocity 1 = 0.0")
    s("  Velocity 2 = 0.0")
    s("End")
    s()
    # Boundary condition 2: Inlet with parabolic velocity profile
    s("Boundary Condition 2")
    s(f"  Target Boundaries(1) = {inlet_tag}")
    s('  Name = "Inlet"')
    s("  Velocity 2 = 0.0")
    s("  Velocity 1 = Variable Coordinate 2")
    s(f"    Real MATC \"{matc_expr}\"")
    s("End")
    s()
    # Boundary condition 3: Outlet (zero normal velocity, free tangential)
    s("Boundary Condition 3")
    s(f"  Target Boundaries(1) = {outlet_tag}")
    s('  Name = "Outlet"')
    s("  Velocity 2 = 0.0")
    s("End")
    s()

    sif_path = work_dir / "case.sif"
    # Write UTF-8 without BOM
    sif_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sif_path


# ---------------------------------------------------------------------------
# ELMERSOLVER_STARTINFO
# ---------------------------------------------------------------------------

def write_startinfo(work_dir: str | Path) -> Path:
    """Write ELMERSOLVER_STARTINFO pointing to case.sif."""
    work_dir = Path(work_dir)
    p = work_dir / "ELMERSOLVER_STARTINFO"
    p.write_text("case.sif\n1\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Run solver
# ---------------------------------------------------------------------------

def run_flow(work_dir: str | Path, timeout_seconds: int = 300) -> dict:
    """Run ElmerSolver in work_dir. Returns returncode, stdout, stderr."""
    work_dir = Path(work_dir)
    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    existing_path = env.get("PATH", "")
    if str(ELMER_BIN) not in existing_path:
        env["PATH"] = str(ELMER_BIN) + os.pathsep + existing_path

    t0 = time.time()
    proc = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )
    elapsed = round(time.time() - t0, 2)
    converged = "ALL DONE" in proc.stdout or "ALL DONE" in proc.stderr
    return {
        "returncode": proc.returncode,
        "converged": converged,
        "elapsed_seconds": elapsed,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "log_snippet": (proc.stdout + proc.stderr)[-3000:],
    }


# ---------------------------------------------------------------------------
# VTU result parser
# ---------------------------------------------------------------------------

def _read_vtu_xml_root(vtu_path: Path):
    """Read a VTK XML unstructured grid file; return (root_element, binary_data_or_None)."""
    raw = vtu_path.read_bytes()

    # Check for binary appended data marker
    marker = b"_"
    appended_pos = raw.find(b"<AppendedData")
    if appended_pos == -1:
        # Pure ASCII VTU
        return ET.fromstring(raw.decode("utf-8", errors="replace")), None

    # Find the "_" that starts the binary blob
    underscore_pos = raw.find(marker, appended_pos)
    if underscore_pos == -1:
        return ET.fromstring(raw.decode("utf-8", errors="replace")), None

    header_bytes = raw[:underscore_pos]
    binary_data = raw[underscore_pos + 1:]

    xml_str = header_bytes.decode("utf-8", errors="replace") + "\n_</AppendedData>\n</VTKFile>"
    return ET.fromstring(xml_str), binary_data


def _parse_vtu_field(vtu_path: Path, field_name: str) -> list[float]:
    """Extract a named field from a VTU file. Returns per-node float list."""
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
    available = []
    for piece in root.iter("Piece"):
        pd = piece.find("PointData")
        if pd is not None:
            available.extend(da.get("Name", "") for da in pd.findall("DataArray"))
    raise RuntimeError(
        f"Field '{field_name}' not found in {vtu_path.name}. "
        f"Available fields: {available}"
    )


def get_flow_stats(work_dir: str | Path) -> dict:
    """
    Parse case_t0001.vtu (or latest *.vtu) for Flow Solution.

    Flow Solution has 3 DOFs per node: [Vx, Vy, P].
    Returns max_velocity_x, max_velocity_magnitude, min_pressure, max_pressure.
    """
    work_dir = Path(work_dir)

    # Prefer case_t0001.vtu, fall back to most recent .vtu
    vtu = work_dir / "case_t0001.vtu"
    if not vtu.exists():
        candidates = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
        if not candidates:
            raise RuntimeError(f"No .vtu files found in {work_dir}")
        vtu = candidates[-1]

    # Try field names in order of likelihood
    vel_field = None
    for candidate in ("Flow Solution", "velocity", "Velocity"):
        try:
            raw = _parse_vtu_field(vtu, candidate)
            vel_field = candidate
            break
        except RuntimeError:
            continue

    if vel_field is None:
        raise RuntimeError(
            f"Could not find velocity field in {vtu.name}. "
            f"Tried: 'Flow Solution', 'velocity', 'Velocity'."
        )

    raw_vel = raw
    n_comp = len(raw_vel)

    if vel_field == "Flow Solution":
        # 3 DOFs per node: Vx, Vy, P
        n_nodes = n_comp // 3
        vx = [raw_vel[3 * i] for i in range(n_nodes)]
        vy = [raw_vel[3 * i + 1] for i in range(n_nodes)]
        p = [raw_vel[3 * i + 2] for i in range(n_nodes)]
        p_min = min(p)
        p_max = max(p)
    else:
        # velocity only — 3 components per node (Vx, Vy, Vz) for 2D meshes in Elmer
        n_nodes = n_comp // 3
        vx = [raw_vel[3 * i] for i in range(n_nodes)]
        vy = [raw_vel[3 * i + 1] for i in range(n_nodes)]
        # Try pressure separately
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
        "max_velocity_x": max(vx),
        "max_velocity_magnitude": max(mags),
        "mean_velocity_x": sum(vx) / n_nodes,
        "min_pressure": p_min,
        "max_pressure": p_max,
    }
