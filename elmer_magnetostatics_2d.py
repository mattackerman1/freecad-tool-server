"""
Elmer Tutorial 15 — 2D Magnetostatics: horseshoe permanent magnet.
Solves for the z-component of the magnetic vector potential (Az).
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"
ELMER_GRID = ELMER_BIN / "ElmerGrid.exe"


# ---------------------------------------------------------------------------
# Step 1: Convert Gmsh mesh → Elmer format
# ---------------------------------------------------------------------------

def convert_gmsh_mesh(mesh_dir: Path) -> bool:
    """
    Run ElmerGrid to convert horseshoe.msh (Gmsh format 14) to Elmer native format.
    Returns True if successful (or if mesh files already exist).
    mesh_dir: directory containing horseshoe.msh
    """
    mesh_dir = Path(mesh_dir)
    # Check if already converted
    if (mesh_dir / "mesh.nodes").exists() and (mesh_dir / "mesh.elements").exists():
        return True

    msh_file = mesh_dir / "horseshoe.msh"
    if not msh_file.exists():
        raise FileNotFoundError(f"horseshoe.msh not found in {mesh_dir}")

    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)

    result = subprocess.run(
        [str(ELMER_GRID), "14", "2", str(msh_file), "-out", "."],
        cwd=str(mesh_dir),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Step 2: Inspect body indices from mesh.elements + mesh.nodes
# ---------------------------------------------------------------------------

def inspect_bodies(mesh_dir: Path) -> dict[int, dict]:
    """
    Read mesh.elements and mesh.nodes, compute centroid of each body index.
    Returns {body_idx: {centroid_x, centroid_y, n_elements}}.
    """
    mesh_dir = Path(mesh_dir)

    nodes: dict[int, tuple[float, float]] = {}
    with open(mesh_dir / "mesh.nodes") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 4:
                nodes[int(parts[0])] = (float(parts[2]), float(parts[3]))

    bodies: dict[int, dict] = {}
    with open(mesh_dir / "mesh.elements") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 4:
                continue
            body_idx = int(parts[1])
            node_ids = list(map(int, parts[3:]))
            xs = [nodes[n][0] for n in node_ids if n in nodes]
            ys = [nodes[n][1] for n in node_ids if n in nodes]
            if not xs:
                continue
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            if body_idx not in bodies:
                bodies[body_idx] = {"xs": [], "ys": [], "n_elements": 0}
            bodies[body_idx]["xs"].append(cx)
            bodies[body_idx]["ys"].append(cy)
            bodies[body_idx]["n_elements"] += 1

    result: dict[int, dict] = {}
    for body_idx, info in bodies.items():
        cx = sum(info["xs"]) / len(info["xs"])
        cy = sum(info["ys"]) / len(info["ys"])
        result[body_idx] = {
            "centroid_x": round(cx, 5),
            "centroid_y": round(cy, 5),
            "n_elements": info["n_elements"],
            "dist_from_origin": round(math.sqrt(cx**2 + cy**2), 5),
        }
    return result


# ---------------------------------------------------------------------------
# Step 3: Inspect boundary tags from mesh.boundary + mesh.nodes
# ---------------------------------------------------------------------------

def inspect_boundaries(mesh_dir: Path) -> dict[int, dict]:
    """
    Read mesh.boundary and mesh.nodes.
    Returns {bc_tag: {centroid_x, centroid_y, max_dist_from_origin, n_elements}}.

    Elmer mesh.boundary format:
      elem_id  bc_tag  parent1  parent2  elem_type  node1  node2 ...
    """
    mesh_dir = Path(mesh_dir)

    nodes: dict[int, tuple[float, float]] = {}
    with open(mesh_dir / "mesh.nodes") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 4:
                nodes[int(parts[0])] = (float(parts[2]), float(parts[3]))

    bounds: dict[int, dict] = {}
    with open(mesh_dir / "mesh.boundary") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 6:
                continue
            bc_tag = int(parts[1])
            node_ids = list(map(int, parts[5:]))
            xs = [nodes[n][0] for n in node_ids if n in nodes]
            ys = [nodes[n][1] for n in node_ids if n in nodes]
            if bc_tag not in bounds:
                bounds[bc_tag] = {"xs": [], "ys": [], "n_elements": 0}
            bounds[bc_tag]["xs"].extend(xs)
            bounds[bc_tag]["ys"].extend(ys)
            bounds[bc_tag]["n_elements"] += 1

    result: dict[int, dict] = {}
    for bc_tag, info in bounds.items():
        xs = info["xs"]
        ys = info["ys"]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        max_dist = max(math.sqrt(x**2 + y**2) for x, y in zip(xs, ys))
        result[bc_tag] = {
            "centroid_x": round(cx, 5),
            "centroid_y": round(cy, 5),
            "max_dist_from_origin": round(max_dist, 5),
            "n_elements": info["n_elements"],
        }
    return result


# ---------------------------------------------------------------------------
# Step 4: Write case.sif
# ---------------------------------------------------------------------------

def write_magnetostatics_sif(
    work_dir: Path,
    air_body: int = 4,
    iron_body: int = 2,
    ironplus_body: int = 1,
    ironminus_body: int = 3,
    outer_bc_tags: list[int] | None = None,
    magnetization: float = 750.0e3,
    relative_permeability: float = 5000.0,
    **kwargs: Any,
) -> Path:
    """Write case.sif for the 2D magnetostatics horseshoe magnet simulation."""
    work_dir = Path(work_dir)
    if outer_bc_tags is None:
        outer_bc_tags = [15, 16, 17, 18]

    outer_bc_str = " ".join(str(t) for t in outer_bc_tags)
    n_outer = len(outer_bc_tags)

    sif = f"""\
Header
  CHECK KEYWORDS Warn
  Mesh DB "." "."
  Include Path ""
  Results Directory ""
End

Simulation
  Max Output Level = 5
  Coordinate System = Cartesian
  Coordinate Mapping(3) = 1 2 3
  Simulation Type = Steady state
  Steady State Max Iterations = 1
  Output Intervals = 1
  Solver Input File = case.sif
  Post File = case.vtu
End

Constants
  Gravity(4) = 0 -1 0 9.82
  Stefan Boltzmann = 5.67e-08
  Permittivity of Vacuum = 8.85418781e-12
  Permeability of Vacuum = 1.25663706e-6
  Boltzmann Constant = 1.3807e-23
  Unit Charge = 1.602e-19
End

Body 1
  Target Bodies(1) = {air_body}
  Name = "Air"
  Equation = 1
  Material = 1
End

Body 2
  Target Bodies(1) = {iron_body}
  Name = "Iron"
  Equation = 1
  Material = 2
End

Body 3
  Target Bodies(1) = {ironplus_body}
  Name = "IronPlus"
  Equation = 1
  Material = 3
End

Body 4
  Target Bodies(1) = {ironminus_body}
  Name = "IronMinus"
  Equation = 1
  Material = 4
End

Solver 1
  Equation = MgDyn2D
  Procedure = "MagnetoDynamics2D" "MagnetoDynamics2D"
  Variable = Az
  Exec Solver = Always
  Stabilize = True
  Optimize Bandwidth = True
  Steady State Convergence Tolerance = 1.0e-5
  Nonlinear System Convergence Tolerance = 1.0e-8
  Nonlinear System Max Iterations = 20
  Nonlinear System Newton After Iterations = 3
  Nonlinear System Newton After Tolerance = 1.0e-3
  Nonlinear System Relaxation Factor = 1
  Linear System Solver = Iterative
  Linear System Iterative Method = BiCGStab
  Linear System Max Iterations = 500
  Linear System Convergence Tolerance = 1.0e-8
  BiCGstabl polynomial degree = 2
  Linear System Preconditioning = ILU0
  Linear System Abort Not Converged = False
  Linear System Residual Output = 10
End

Equation 1
  Name = "MgDyn"
  Active Solvers(1) = 1
End

Material 1
  Name = "Air"
  Relative Permeability = 1.0
End

Material 2
  Name = "Iron"
  Relative Permeability = {relative_permeability}
End

Material 3
  Name = "IronPlus"
  Relative Permeability = {relative_permeability}
  Magnetization 1 = Real {magnetization:.6e}
End

Material 4
  Name = "IronMinus"
  Relative Permeability = {relative_permeability}
  Magnetization 1 = Real {-magnetization:.6e}
End

Boundary Condition 1
  Target Boundaries({n_outer}) = {outer_bc_str}
  Name = "Farfield"
  Az = 0.0
End
"""

    sif_path = work_dir / "case.sif"
    sif_path.write_text(sif, encoding="utf-8")
    return sif_path


# ---------------------------------------------------------------------------
# Step 5: Write ELMERSOLVER_STARTINFO
# ---------------------------------------------------------------------------

def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    work_dir = Path(work_dir)
    startinfo = work_dir / "ELMERSOLVER_STARTINFO"
    startinfo.write_text(f"{sif_name}\n1\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Step 6: Run ElmerSolver
# ---------------------------------------------------------------------------

def run_magnetostatics(work_dir: Path, timeout: int = 300) -> dict:
    """
    Run ElmerSolver in work_dir. Returns dict with returncode, stdout, stderr.
    """
    work_dir = Path(work_dir)
    env = os.environ.copy()
    env["ELMER_HOME"] = str(ELMER_BIN.parent)
    existing_path = env.get("PATH", "")
    elmer_bin_str = str(ELMER_BIN)
    if elmer_bin_str not in existing_path:
        env["PATH"] = elmer_bin_str + os.pathsep + existing_path

    result = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "converged": "ALL DONE" in result.stdout,
    }


# ---------------------------------------------------------------------------
# Step 7: Parse VTU results for Az field
# ---------------------------------------------------------------------------

def _parse_vtu_scalar(vtu_path: Path, field_name: str) -> list[float]:
    """
    Parse a scalar field from a VTU file produced by Elmer.
    Supports inline ASCII and raw-appended binary (Elmer's default).
    Returns a list of float values.
    """
    import re

    content = vtu_path.read_bytes()

    # Split XML header from appended binary data
    appended_marker = content.find(b"<AppendedData")
    if appended_marker >= 0:
        xml_text = content[:appended_marker].decode("latin-1", errors="replace")
        # Data starts after the underscore separator
        underscore_pos = content.find(b"_", appended_marker) + 1
    else:
        xml_text = content.decode("latin-1", errors="replace")
        underscore_pos = -1

    # Find the DataArray tag for the requested field (self-closing or with content)
    # Match self-closing: <DataArray ... Name="az" ... />
    sc_pattern = re.compile(
        r'<DataArray\s+([^>]+?)\s*/>', re.IGNORECASE | re.DOTALL
    )
    # Match with content: <DataArray ... Name="az" ...>...</DataArray>
    lc_pattern = re.compile(
        r'<DataArray\s+([^>]+)>(.*?)</DataArray>', re.IGNORECASE | re.DOTALL
    )

    target_attrs: dict | None = None
    inline_content: str | None = None

    for m in sc_pattern.finditer(xml_text):
        attr_str = m.group(1)
        nm = re.search(r'Name="([^"]+)"', attr_str, re.IGNORECASE)
        if nm and nm.group(1).lower() == field_name.lower():
            attrs = {
                am.group(1).lower(): am.group(2)
                for am in re.finditer(r'(\w+)="([^"]*)"', attr_str)
            }
            target_attrs = attrs
            break

    if target_attrs is None:
        for m in lc_pattern.finditer(xml_text):
            attr_str = m.group(1)
            nm = re.search(r'Name="([^"]+)"', attr_str, re.IGNORECASE)
            if nm and nm.group(1).lower() == field_name.lower():
                attrs = {
                    am.group(1).lower(): am.group(2)
                    for am in re.finditer(r'(\w+)="([^"]*)"', attr_str)
                }
                target_attrs = attrs
                inline_content = m.group(2).strip()
                break

    if target_attrs is None:
        raise ValueError(f"Field '{field_name}' not found in {vtu_path}")

    fmt = target_attrs.get("format", "ascii").lower()
    dtype = target_attrs.get("type", "Float64").lower()
    float_size = 8 if "64" in dtype else 4
    float_fmt = "d" if float_size == 8 else "f"

    # Raw appended binary
    if fmt == "appended" and underscore_pos >= 0:
        offset = int(target_attrs.get("offset", "0"))
        abs_pos = underscore_pos + offset
        # 4-byte UInt32 block size header
        n_bytes = struct.unpack_from("<I", content, abs_pos)[0]
        data_pos = abs_pos + 4
        n_values = n_bytes // float_size
        return list(struct.unpack_from(f"<{n_values}{float_fmt}", content, data_pos))

    # Inline base64 binary
    if fmt in ("binary", "base64") and inline_content:
        import base64 as _b64
        raw = _b64.b64decode("".join(inline_content.split()))
        n_bytes = struct.unpack_from("<I", raw, 0)[0]
        n_values = n_bytes // float_size
        return list(struct.unpack_from(f"<{n_values}{float_fmt}", raw, 4))

    # Inline ASCII
    if inline_content:
        return [float(v) for v in inline_content.split() if v.strip()]

    raise ValueError(f"Could not parse field '{field_name}' from {vtu_path}")


def get_az_stats(work_dir: Path) -> dict:
    """
    Read case_t0001.vtu (or case.vtu) and extract "Az" field statistics.
    Returns dict with max_az, min_az, mean_az, node_count.
    """
    work_dir = Path(work_dir)

    # Look for VTU files
    candidates = sorted(work_dir.glob("case_t*.vtu")) + sorted(work_dir.glob("case.vtu"))
    if not candidates:
        raise FileNotFoundError(f"No VTU files found in {work_dir}")

    vtu_path = candidates[0]
    # Try "Az" then "az" (Elmer lowercases the variable name in VTU output)
    try:
        vals = _parse_vtu_scalar(vtu_path, "Az")
    except ValueError:
        vals = _parse_vtu_scalar(vtu_path, "az")

    if not vals:
        raise ValueError(f"Az field is empty in {vtu_path}")

    return {
        "max_az": max(vals),
        "min_az": min(vals),
        "mean_az": sum(vals) / len(vals),
        "node_count": len(vals),
        "vtu_file": vtu_path.name,
    }
