"""
Elmer FEM solver integration for the FreeCAD Tool Server.

Provides headless ElmerSolver runs:
 1. Write a .sif case file from high-level parameters
 2. Execute ElmerSolver as a subprocess
 3. Parse .vtu result files for field statistics

Elmer installation assumed at C:\\Elmer\\ElmerFEM-nogui-nompi-Windows-AMD64
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"
ELMER_GRID = ELMER_BIN / "ElmerGrid.exe"


def elmer_available() -> bool:
    return ELMER_SOLVER.exists()


# ---------------------------------------------------------------------------
# SIF file writer
# ---------------------------------------------------------------------------

def write_heat_sif(
    working_dir: Path,
    *,
    heat_conductivity: float = 237.0,
    density: float = 2700.0,
    heat_capacity: float = 897.0,
    heat_source: float = 0.01,
    coordinate_scaling: Optional[float] = None,
    boundary_conditions: list[dict],   # [{"tags": [57], "temperature": 293.0}, ...]
    post_file: str = "case.vtu",
    sif_name: str = "case.sif",
) -> Path:
    """
    Write a steady-state heat equation .sif file.

    boundary_conditions entries:
      {"tags": [57], "temperature": 293.0}   → Dirichlet T BC
      {"tags": [3, 24], "heat_flux": 0.0}    → Natural (insulated) BC (default, optional)
    """
    lines: list[str] = []

    def s(line: str = "") -> None:
        lines.append(line)

    s("Header")
    s('  CHECK KEYWORDS Warn')
    s('  Mesh DB "." "."')
    s('  Include Path ""')
    s('  Results Directory ""')
    s("End")
    s()
    s("Simulation")
    s("  Max Output Level = 5")
    s("  Coordinate System = Cartesian")
    s("  Coordinate Mapping(3) = 1 2 3")
    if coordinate_scaling is not None:
        s(f"  Coordinate Scaling = {coordinate_scaling}")
    s("  Simulation Type = Steady state")
    s("  Steady State Max Iterations = 1")
    s("  Output Intervals = 1")
    s(f'  Solver Input File = "{sif_name}"')
    s(f'  Post File = "{post_file}"')
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
    s("  Body Force = 1")
    s("End")
    s()
    s("Equation 1")
    s('  Name = "Heat Equation"')
    s("  Active Solvers(1) = 1")
    s("End")
    s()
    s("Solver 1")
    s("  Equation = Heat Equation")
    s('  Procedure = "HeatSolve" "HeatSolver"')
    s("  Variable = Temperature")
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
    s("Material 1")
    s('  Name = "Material"')
    s(f"  Heat Conductivity = {heat_conductivity}")
    s(f"  Density = {density}")
    s(f"  Heat Capacity = {heat_capacity}")
    s("End")
    s()
    s("Body Force 1")
    s('  Name = "Heating"')
    s(f"  Heat Source = {heat_source}")
    s("End")
    s()

    for i, bc in enumerate(boundary_conditions, start=1):
        tags = bc.get("tags", [])
        tag_str = " ".join(str(t) for t in tags)
        n = len(tags)
        s(f"Boundary Condition {i}")
        s(f'  Name = "BC{i}"')
        s(f"  Target Boundaries({n}) = {tag_str}")
        if "temperature" in bc:
            s(f"  Temperature = {bc['temperature']}")
        s("End")
        s()

    sif_path = working_dir / sif_name
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def write_startinfo(working_dir: Path, sif_name: str = "case.sif") -> None:
    (working_dir / "ELMERSOLVER_STARTINFO").write_text(f"{sif_name}\n1\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Run ElmerSolver
# ---------------------------------------------------------------------------

def run_elmer(working_dir: Path, timeout_seconds: int = 300) -> dict:
    """Run ElmerSolver in working_dir and return structured result."""
    if not ELMER_SOLVER.exists():
        raise RuntimeError(f"ElmerSolver not found at {ELMER_SOLVER}")

    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)

    t0 = time.time()
    result = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(working_dir),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )
    elapsed = time.time() - t0

    stdout = result.stdout + result.stderr
    converged = "ALL DONE" in stdout
    norm = None

    for line in stdout.splitlines():
        if "Result Norm" in line and ":" in line:
            try:
                norm = float(line.split(":")[-1].strip())
            except ValueError:
                pass

    # Find produced VTU files
    vtu_files = list(working_dir.glob("*.vtu"))

    return {
        "converged": converged,
        "result_norm": norm,
        "elapsed_seconds": round(elapsed, 2),
        "return_code": result.returncode,
        "vtu_files": [str(f) for f in vtu_files],
        "log_snippet": stdout[-3000:] if stdout else "",
    }


# ---------------------------------------------------------------------------
# Parse VTU results
# ---------------------------------------------------------------------------

def _read_vtu_xml_root(vtu_path: Path):
    """
    Parse a VTK XML (.vtu) file that may contain raw binary appended data.
    The binary section (after <AppendedData encoding="raw">_) corrupts the
    XML parser, so we strip it out and parse only the header.
    Returns (ET.Element root, raw_bytes_after_underscore_or_None).
    """
    raw = vtu_path.read_bytes()
    # Find the AppendedData marker — raw binary follows the underscore
    marker = b'<AppendedData encoding="raw">'
    idx = raw.find(marker)
    if idx == -1:
        # ASCII / base64 format — safe to parse directly
        return ET.fromstring(raw.decode("utf-8", errors="replace")), None

    header_bytes = raw[: idx + len(marker)]
    # The underscore separator and binary data follow
    after_marker = raw[idx + len(marker):]
    underscore_pos = after_marker.find(b"_")
    if underscore_pos == -1:
        return ET.fromstring(raw.decode("utf-8", errors="replace")), None
    binary_data = after_marker[underscore_pos + 1:]

    # Build a valid XML document: replace the AppendedData content with empty
    xml_str = header_bytes.decode("utf-8", errors="replace") + "\n_</AppendedData>\n</VTKFile>"
    return ET.fromstring(xml_str), binary_data


def _parse_vtu_field(vtu_path: Path, field_name: str) -> list[float]:
    """
    Extract a named scalar field from a VTK XML (.vtu) file.
    Handles both ASCII inline and raw-binary appended formats.
    Returns a list of per-node float values.
    """
    import struct

    root, binary_data = _read_vtu_xml_root(vtu_path)

    # VTU structure: VTKFile / UnstructuredGrid / Piece / PointData / DataArray
    for piece in root.iter("Piece"):
        n_points = int(piece.get("NumberOfPoints", 0))
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
                # VTK raw appended: first 4 bytes at offset = byte length of data
                seg = binary_data[offset:]
                byte_len = struct.unpack_from("<I", seg, 0)[0]
                n_vals = byte_len // item_size
                values = list(struct.unpack_from(f"<{n_vals}{pack_char}", seg, 4))
                return [float(v) for v in values]

    raise RuntimeError(
        f"Field '{field_name}' not found in {vtu_path.name}. "
        f"Available fields: {_list_vtu_fields(vtu_path)}"
    )


def _list_vtu_fields(vtu_path: Path) -> list[str]:
    root, _ = _read_vtu_xml_root(vtu_path)
    fields = []
    for piece in root.iter("Piece"):
        pd = piece.find("PointData")
        if pd is not None:
            fields.extend(da.get("Name", "") for da in pd.findall("DataArray"))
    return fields


def get_field_stats(working_dir: Path, field_name: str = "Temperature") -> dict:
    """
    Extract min/max/mean/norm statistics for a named field from the VTU result.
    """
    # Find the most recent vtu file
    vtu_files = sorted(working_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
    if not vtu_files:
        raise RuntimeError(f"No .vtu result files found in {working_dir}")
    vtu_path = vtu_files[-1]

    values = _parse_vtu_field(vtu_path, field_name)
    if not values:
        raise RuntimeError(f"Field '{field_name}' has no data in {vtu_path.name}")

    import math
    n = len(values)
    v_min = min(values)
    v_max = max(values)
    v_mean = sum(values) / n
    v_norm = math.sqrt(sum(x * x for x in values) / n)

    return {
        "field_name": field_name,
        "vtu_file": str(vtu_path),
        "node_count": n,
        "min_value": v_min,
        "max_value": v_max,
        "mean_value": v_mean,
        "rms_norm": v_norm,
        "available_fields": _list_vtu_fields(vtu_path),
    }


# ---------------------------------------------------------------------------
# Mesh inspection
# ---------------------------------------------------------------------------

def inspect_mesh_boundaries(mesh_dir: Path, max_tags: int = 200) -> list[dict]:
    """
    Parse mesh.nodes and mesh.boundary to return per-tag statistics.

    Returns a list of dicts (one per unique tag, sorted by tag index):
      tag, element_count, node_count, centroid (x/y/z), bbox (x/y/z min/max)
    """
    from collections import defaultdict

    nodes_path = mesh_dir / "mesh.nodes"
    boundary_path = mesh_dir / "mesh.boundary"
    if not nodes_path.exists():
        raise RuntimeError(f"mesh.nodes not found in {mesh_dir}")
    if not boundary_path.exists():
        raise RuntimeError(f"mesh.boundary not found in {mesh_dir}")

    node_coords: dict[int, tuple[float, float, float]] = {}
    for line in nodes_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            node_coords[int(parts[0])] = (float(parts[2]), float(parts[3]), float(parts[4]))
        except ValueError:
            continue

    tag_elem_counts: dict[int, int] = defaultdict(int)
    tag_node_sets: dict[int, set] = defaultdict(set)
    tag_node_lists: dict[int, list] = defaultdict(list)

    for line in boundary_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            tag = int(parts[1])
        except ValueError:
            continue
        if len(tag_elem_counts) >= max_tags and tag not in tag_elem_counts:
            continue
        tag_elem_counts[tag] += 1
        for nid_str in parts[5:]:
            try:
                nid = int(nid_str)
                if nid not in tag_node_sets[tag]:
                    tag_node_sets[tag].add(nid)
                    if nid in node_coords:
                        tag_node_lists[tag].append(node_coords[nid])
            except ValueError:
                continue

    results = []
    for tag in sorted(tag_elem_counts.keys()):
        pts = tag_node_lists[tag]
        if pts:
            xs, ys, zs = [p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts]
            n = len(pts)
            bbox = {"x_min": min(xs), "x_max": max(xs),
                    "y_min": min(ys), "y_max": max(ys),
                    "z_min": min(zs), "z_max": max(zs)}
            centroid = {"x": sum(xs)/n, "y": sum(ys)/n, "z": sum(zs)/n}
        else:
            bbox, centroid = {}, {}
        results.append({
            "tag": tag,
            "element_count": tag_elem_counts[tag],
            "node_count": len(tag_node_sets[tag]),
            "centroid": centroid,
            "bbox": bbox,
        })
    return results


# ---------------------------------------------------------------------------
# High-level: copy mesh + write sif + run + return results
# ---------------------------------------------------------------------------

def run_heat_tutorial(
    mesh_source_dir: Path,
    working_dir: Path,
    boundary_conditions: list[dict],
    material: dict | None = None,
    coordinate_scaling: float | None = None,
    heat_source: float = 0.01,
    timeout_seconds: int = 300,
) -> dict:
    """
    End-to-end: copy mesh → write sif → run solver → return field stats.

    material dict keys: heat_conductivity, density, heat_capacity
    """
    working_dir.mkdir(parents=True, exist_ok=True)

    # Copy mesh files if different directory
    if mesh_source_dir.resolve() != working_dir.resolve():
        for f in mesh_source_dir.glob("mesh.*"):
            shutil.copy2(f, working_dir / f.name)

    mat = material or {}
    sif_path = write_heat_sif(
        working_dir,
        heat_conductivity=mat.get("heat_conductivity", 237.0),
        density=mat.get("density", 2700.0),
        heat_capacity=mat.get("heat_capacity", 897.0),
        heat_source=heat_source,
        coordinate_scaling=coordinate_scaling,
        boundary_conditions=boundary_conditions,
    )
    write_startinfo(working_dir)

    solver_result = run_elmer(working_dir, timeout_seconds=timeout_seconds)
    if not solver_result["converged"]:
        raise RuntimeError(
            f"ElmerSolver did not converge. Log: {solver_result['log_snippet'][-500:]}"
        )

    field_stats = get_field_stats(working_dir, "Temperature")
    return {**solver_result, **field_stats}
