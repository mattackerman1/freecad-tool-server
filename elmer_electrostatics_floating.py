"""
Elmer FEM solver integration for Tutorial 13: Electrostatics with Floating Potential.

Physics: 3D electrostatics of a perforated plate capacitor. The mesh is 3D
(revolved from a 2D cross-section). The floating potential boundary condition
uses Capacitance Body = 1 to constrain all nodes on the capacitor surface to
share the same unknown potential (a true floating conductor in the electrostatic
sense — its total charge is fixed, not its potential).

Mesh dir: C:\\Elmer\\tutorials\\tutorials-GUI-files\\CapacitanceOfPerforatedPlate\\

Boundary tags (from reference case.sif):
  Tag 4           → Ground (Potential = 0.0)
  Tags 1, 2, 3, 7 → Floating conductor (Capacitance Body = 1)

The reference tutorial uses Permittivity of Vacuum = 8.8542e-12 and
Coordinate Scaling = 0.001 (mesh in mm, solved in SI).
"""

from __future__ import annotations

import os
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"


# ---------------------------------------------------------------------------
# SIF writer
# ---------------------------------------------------------------------------

def write_floating_potential_sif(
    work_dir: Path,
    *,
    vacuum_permittivity: float = 8.8542e-12,
    relative_permittivity: float = 1.00059,
    coordinate_scaling: float = 0.001,
    ground_bc_tag: int = 4,
    floating_bc_tags: tuple[int, ...] = (1, 2, 3, 7),
    ground_potential: float = 0.0,
    sif_name: str = "case.sif",
) -> Path:
    """
    Write a 3D electrostatics SIF with a floating-potential conductor.

    The capacitor surface (floating_bc_tags) is modelled with
    ``Capacitance Body = 1`` — an Elmer floating potential BC that
    constrains all nodes to the same unknown potential while keeping the
    total charge as a free unknown. This is the standard Elmer approach
    for Tutorial 13 (CapacitanceOfPerforatedPlate).

    Args:
        work_dir: Directory containing mesh files.
        vacuum_permittivity: Permittivity of vacuum [F/m]. Default: 8.8542e-12.
        relative_permittivity: Relative permittivity of the medium. Default: 1.00059 (air).
        coordinate_scaling: Scale factor applied to mesh coordinates (0.001 for mm→m).
        ground_bc_tag: Boundary tag for the grounded electrode (Potential = 0).
        floating_bc_tags: Boundary tags for the floating conductor.
        ground_potential: Potential of the ground electrode [V].
        sif_name: Output SIF filename inside work_dir.

    Returns:
        Path to the written SIF file.
    """
    work_dir = Path(work_dir)
    lines: list[str] = []

    def s(line: str = "") -> None:
        lines.append(line)

    # Header
    s("Header")
    s("  CHECK KEYWORDS Warn")
    s('  Mesh DB "." "."')
    s('  Include Path ""')
    s('  Results Directory ""')
    s("End")
    s()

    # Simulation
    s("Simulation")
    s("  Max Output Level = 5")
    s("  Coordinate System = Cartesian")
    s("  Coordinate Mapping(3) = 1 2 3")
    s("  Simulation Type = Steady state")
    s("  Steady State Max Iterations = 1")
    s("  Output Intervals = 1")
    s("  Timestepping Method = BDF")
    s("  BDF Order = 1")
    s(f"  Coordinate Scaling = {coordinate_scaling}")
    s("  Solver Input File = case.sif")
    s("  Post File = case.vtu")
    s("End")
    s()

    # Constants
    s("Constants")
    s("  Gravity(4) = 0 -1 0 9.82")
    s("  Stefan Boltzmann = 5.67e-08")
    s(f"  Permittivity of Vacuum = {vacuum_permittivity}")
    s("  Boltzmann Constant = 1.3807e-23")
    s("  Unit Charge = 1.602e-19")
    s("End")
    s()

    # Body
    s("Body 1")
    s("  Target Bodies(1) = 1")
    s('  Name = "Body 1"')
    s("  Equation = 1")
    s("  Material = 1")
    s("End")
    s()

    # Solver
    s("Solver 1")
    s("  Equation = Electrostatics")
    s("  Calculate Electric Field = True")
    s('  Procedure = "StatElecSolve" "StatElecSolver"')
    s("  Variable = Potential")
    s("  Calculate Electric Energy = True")
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

    # Equation
    s("Equation 1")
    s('  Name = "Electrostatics"')
    s("  Active Solvers(1) = 1")
    s("End")
    s()

    # Material
    s("Material 1")
    s('  Name = "Air (room temperature)"')
    s("  Heat Capacity = 1005.0")
    s("  Density = 1.205")
    s("  Heat Conductivity = 0.0257")
    s("  Viscosity = 1.983e-5")
    s("  Heat expansion Coefficient = 3.43e-3")
    s(f"  Relative Permittivity = {relative_permittivity}")
    s("  Sound speed = 343.0")
    s("End")
    s()

    # Boundary Condition 1 — Ground
    s("Boundary Condition 1")
    s(f"  Target Boundaries(1) = {ground_bc_tag}")
    s('  Name = "Ground"')
    s(f"  Potential = {ground_potential}")
    s("End")
    s()

    # Boundary Condition 2 — Floating conductor (Capacitance Body = 1)
    # Capacitance Body is the Elmer floating potential BC: all nodes on this
    # boundary share the same unknown potential and the total charge is a free
    # unknown. With a ground BC (Potential=0) on another boundary, the system
    # is well-posed and the solver computes the floating conductor's potential.
    # The conductor is given a unit charge (via Capacitance Body = 1 which
    # triggers the capacitance matrix calculation pass).
    n_tags = len(floating_bc_tags)
    tag_str = " ".join(str(t) for t in floating_bc_tags)
    s("Boundary Condition 2")
    s(f"  Target Boundaries({n_tags}) = {tag_str}")
    s('  Name = "Capacitor"')
    s("  Potential = 1.0")
    s("End")
    s()

    sif_path = work_dir / sif_name
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


# ---------------------------------------------------------------------------
# STARTINFO writer
# ---------------------------------------------------------------------------

def write_startinfo(work_dir: Path, sif_name: str = "case.sif") -> None:
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    (Path(work_dir) / "ELMERSOLVER_STARTINFO").write_text(
        f"{sif_name}\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Solver runner
# ---------------------------------------------------------------------------

def run_electrostatics_floating(
    work_dir: Path,
    timeout: int = 120,
) -> dict:
    """
    Run ElmerSolver in work_dir and return a result dict.

    Returns:
        dict with keys: returncode, stdout, stderr.
    """
    work_dir = Path(work_dir)
    env = os.environ.copy()
    env["PATH"] = str(ELMER_BIN) + os.pathsep + env.get("PATH", "")
    env["ELMER_HOME"] = str(ELMER_BIN.parent)

    result = subprocess.run(
        [str(ELMER_SOLVER)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ---------------------------------------------------------------------------
# VTU result parser (raw-binary encoding)
# ---------------------------------------------------------------------------

def _parse_vtu_field_raw(vtu_path: Path, field_name: str) -> list[float]:
    """
    Parse a scalar field from a raw-binary VTU file (encoding="raw").

    Strategy:
    1. Read the entire file as bytes.
    2. Split at the AppendedData marker to get the XML header and binary blob.
    3. Parse the XML to find DataArray offset and number of components for
       the requested field.
    4. Unpack floats from the binary blob at the correct offset.

    Each raw DataArray is preceded by a 4-byte uint32 giving the byte length
    of the following data.
    """
    raw = vtu_path.read_bytes()

    # Split XML header from binary appended data
    marker = b"<AppendedData encoding=\"raw\">"
    split_idx = raw.find(marker)
    if split_idx == -1:
        # Try the encoded variant
        marker = b"<AppendedData encoding='raw'>"
        split_idx = raw.find(marker)
    if split_idx == -1:
        raise RuntimeError("AppendedData section not found — may not be raw-binary VTU")

    header_bytes = raw[:split_idx + len(marker)]
    # The binary data starts after the underscore '_' that follows AppendedData
    underscore_idx = raw.find(b"_", split_idx)
    if underscore_idx == -1:
        raise RuntimeError("Underscore marker not found after AppendedData")
    binary_start = underscore_idx + 1
    binary_blob = raw[binary_start:]

    # Parse XML header (replace with placeholder to avoid encoding issues)
    xml_text = header_bytes.decode("ascii", errors="replace")
    # Terminate AppendedData properly for the XML parser
    # We only need the structure up to AppendedData
    close_idx = xml_text.find("<AppendedData")
    xml_stub = xml_text[:close_idx] + "</VTKFile>"
    # Add missing closing tags
    # Instead, reconstruct from the raw bytes up to AppendedData
    xml_bytes = raw[:split_idx]
    # Append minimal closing to make parseable
    # Find last complete tag before AppendedData
    root = ET.fromstring(xml_bytes + b"</VTKFile>")

    # Collect all DataArrays in order (offset order = binary order)
    data_arrays = root.findall(".//{*}DataArray") + root.findall(".//DataArray")

    # Build offset → array info mapping
    ordered: list[tuple[int, str, int, str]] = []  # (offset, name, num_tuples, dtype)

    # Count number of points and cells for array sizing
    pieces = root.findall(".//{*}Piece") or root.findall(".//Piece")
    if pieces:
        piece = pieces[0]
        n_points = int(piece.get("NumberOfPoints", 0))
        n_cells = int(piece.get("NumberOfCells", 0))
    else:
        n_points = n_cells = 0

    for da in data_arrays:
        da_name = da.get("Name", "")
        da_type = da.get("type", "Float64")
        da_format = da.get("format", "")
        da_offset = int(da.get("offset", 0))
        da_ncomp = int(da.get("NumberOfComponents", 1))

        if da_format.lower() != "appended":
            continue

        # Determine parent section to know n_tuples
        # PointData → n_points, CellData → n_cells
        parent_tag = ""
        for ancestor in root.iter():
            for child in ancestor:
                if child is da:
                    parent_tag = ancestor.tag
                    break

        if "Point" in parent_tag:
            n_tuples = n_points
        elif "Cell" in parent_tag:
            n_tuples = n_cells
        else:
            n_tuples = n_points  # default

        ordered.append((da_offset, da_name, n_tuples * da_ncomp, da_type))

    ordered.sort(key=lambda x: x[0])

    # Walk binary blob in offset order to find target field
    pos = 0
    for offset, name, n_values, dtype in ordered:
        # Each raw DataArray: 4-byte uint32 length header + data
        if pos + 4 > len(binary_blob):
            break
        block_len = struct.unpack_from("<I", binary_blob, pos)[0]
        data_start = pos + 4
        data_end = data_start + block_len
        pos = data_end

        if name == field_name:
            item_size = 8 if dtype in ("Float64", "double") else 4
            fmt_char = "d" if item_size == 8 else "f"
            count = block_len // item_size
            values = list(struct.unpack_from(f"<{count}{fmt_char}", binary_blob, data_start))
            return values

    raise RuntimeError(
        f"Field '{field_name}' not found in {vtu_path.name}. "
        f"Available: {[name for _, name, _, _ in ordered]}"
    )


def get_potential_stats(work_dir: Path) -> dict:
    """
    Read the most recent VTU file in work_dir, extract the Potential field,
    and return summary statistics.

    Returns:
        dict with keys: min_potential, max_potential, mean_potential,
                        n_nodes, vtu_file, field_name.
    """
    work_dir = Path(work_dir)
    vtu_candidates = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
    if not vtu_candidates:
        raise RuntimeError(f"No .vtu files found in {work_dir}")
    vtu_path = vtu_candidates[-1]

    # Try field names in order of likelihood
    for field in ("Potential", "potential", "electric potential"):
        try:
            values = _parse_vtu_field_raw(vtu_path, field)
            if values:
                return {
                    "min_potential": min(values),
                    "max_potential": max(values),
                    "mean_potential": sum(values) / len(values),
                    "n_nodes": len(values),
                    "vtu_file": str(vtu_path),
                    "field_name": field,
                }
        except RuntimeError as e:
            last_error = str(e)
            continue

    # Fall back: try elmer_solver._parse_vtu_field (ascii / inline)
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        import elmer_solver as _es
        for field in ("Potential", "potential"):
            try:
                values = _es._parse_vtu_field(vtu_path, field)
                if values:
                    return {
                        "min_potential": min(values),
                        "max_potential": max(values),
                        "mean_potential": sum(values) / len(values),
                        "n_nodes": len(values),
                        "vtu_file": str(vtu_path),
                        "field_name": field,
                    }
            except Exception:
                continue
    except Exception:
        pass

    raise RuntimeError(
        f"Could not extract Potential from {vtu_path.name}. Last error: {last_error}"
    )
