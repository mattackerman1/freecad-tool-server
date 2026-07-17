"""
Elmer FEM solver integration for Tutorial 29: ModelPDE 3D general PDE.

Solves the general PDE:
    c * du/dt - div(k * grad(u)) + a*u = f

For the steady-state case (c=0, a=0) this reduces to a Poisson equation:
    -div(k * grad(u)) = f

Uses the ModelPDE3D mesh from:
  C:\\Elmer\\tutorials\\tutorials-GUI-files\\ModelPDE3D\\
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


def write_model_pde_sif(
    work_dir: Path,
    *,
    diffusion_coefficient: float = 1.0,
    reaction_coefficient: float = 0.0,
    time_derivative_coefficient: float = 0.0,
    field_source: float = 1.0,
    dirichlet_tags: list[int] | None = None,
    dirichlet_value: float = 0.0,
    neumann_tags: list[int] | None = None,
    neumann_value: float = 0.0,
    coordinate_system: str = "Cartesian",
    sif_name: str = "case.sif",
) -> Path:
    """
    Write a ModelPDE SIF file for the 3D general PDE tutorial.

    The ModelPDE solver solves:
        c * du/dt - div(k * grad(u)) + a * u = f

    Parameters
    ----------
    work_dir : Path
        Directory containing Elmer mesh files and where SIF will be written.
    diffusion_coefficient : float
        k — diffusion coefficient (default 1.0).
    reaction_coefficient : float
        a — reaction/absorption coefficient (default 0.0).
    time_derivative_coefficient : float
        c — mass/time-derivative coefficient (0 = steady-state, default 0.0).
    field_source : float
        f — volumetric source term (default 1.0).
    dirichlet_tags : list[int]
        Boundary tags for Dirichlet (Field = dirichlet_value) conditions.
        Defaults to all 7 boundaries [1..7].
    dirichlet_value : float
        Dirichlet field value (default 0.0).
    neumann_tags : list[int]
        Boundary tags for Neumann (zero flux) — if None, only Dirichlet used.
    neumann_value : float
        Neumann flux value (default 0.0, i.e. insulating).
    coordinate_system : str
        Elmer coordinate system string (default "Cartesian").
    sif_name : str
        Output SIF filename (default "case.sif").
    """
    if dirichlet_tags is None:
        dirichlet_tags = list(range(1, 8))  # Tags 1–7 from ModelPDE3D mesh

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
    s(f"  Coordinate System = {coordinate_system}")
    s("  Coordinate Mapping(3) = 1 2 3")
    s("  Simulation Type = Steady state")
    s("  Steady State Max Iterations = 1")
    s("  Output Intervals = 1")
    s(f"  Solver Input File = {sif_name}")
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
    s("  Body Force = 1")
    s("End")
    s()
    s("Solver 1")
    s('  Equation = "Adv-Diff"')
    s('  Procedure = "ModelPDE" "AdvDiffSolver"')
    s("  Variable = Field")
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
    s("Solver 2")
    s('  Exec Solver = after all')
    s('  Equation = "ResultOutput"')
    s('  Procedure = "ResultOutputSolve" "ResultOutputSolver"')
    s("  Output File Name = case")
    s("  Vtu Format = True")
    s("End")
    s()
    s("Equation 1")
    s('  Name = "AdvDiff"')
    s("  Active Solvers(2) = 1 2")
    s("End")
    s()
    s("Material 1")
    s('  Name = "Material 1"')
    s(f"  Diffusion Coefficient = {diffusion_coefficient}")
    if reaction_coefficient != 0.0:
        s(f"  Reaction Coefficient = {reaction_coefficient}")
    if time_derivative_coefficient != 0.0:
        s(f"  Time Derivative Coefficient = {time_derivative_coefficient}")
    s("End")
    s()
    s("Body Force 1")
    s('  Name = "Source"')
    s(f"  Field Source = {field_source}")
    s("End")
    s()

    # Dirichlet boundary conditions
    bc_idx = 1
    if dirichlet_tags:
        tags_str = " ".join(str(t) for t in dirichlet_tags)
        n_tags = len(dirichlet_tags)
        s(f"Boundary Condition {bc_idx}")
        s(f"  Target Boundaries({n_tags}) = {tags_str}")
        s('  Name = "Dirichlet"')
        s(f"  Field = {dirichlet_value}")
        s("End")
        bc_idx += 1
        s()

    # Neumann boundary conditions (if any)
    if neumann_tags:
        tags_str = " ".join(str(t) for t in neumann_tags)
        n_tags = len(neumann_tags)
        s(f"Boundary Condition {bc_idx}")
        s(f"  Target Boundaries({n_tags}) = {tags_str}")
        s('  Name = "Neumann"')
        s(f"  Field Flux = {neumann_value}")
        s("End")
        s()

    sif_path = work_dir / sif_name
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    (work_dir / "ELMERSOLVER_STARTINFO").write_text(
        f"{sif_name}\n1\n", encoding="utf-8"
    )


def run_model_pde(work_dir: Path, timeout: int = 120) -> dict:
    """
    Run ElmerSolver in work_dir for the ModelPDE simulation.

    Returns a dict with keys: returncode, stdout, stderr, converged, elapsed_seconds.
    """
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
    elapsed = round(time.time() - t0, 2)

    combined = result.stdout + result.stderr
    converged = "ALL DONE" in combined

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "converged": converged,
        "elapsed_seconds": elapsed,
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

    xml_str = (
        header_bytes.decode("utf-8", errors="replace")
        + "\n_</AppendedData>\n</VTKFile>"
    )
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


def get_field_stats(work_dir: Path, field_name: str = "Field") -> dict:
    """
    Read the VTU result file and extract field statistics.

    Returns min_value, max_value, mean_value, node_count, vtu_file.
    """
    # Try case_t0001.vtu first, then most recent .vtu
    vtu_path = work_dir / "case_t0001.vtu"
    if not vtu_path.exists():
        vtu_files = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
        if not vtu_files:
            raise RuntimeError(f"No .vtu result files found in {work_dir}")
        vtu_path = vtu_files[-1]

    values = _parse_vtu_field(vtu_path, field_name)

    # If the named field is missing, try "Field" as fallback
    if not values and field_name.lower() != "field":
        values = _parse_vtu_field(vtu_path, "Field")

    if not values:
        raise RuntimeError(
            f"Field '{field_name}' has no data in {vtu_path.name}"
        )

    return {
        "min_value": min(values),
        "max_value": max(values),
        "mean_value": sum(values) / len(values),
        "node_count": len(values),
        "vtu_file": str(vtu_path),
        "field_name": field_name,
    }
