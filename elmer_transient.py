"""
Transient heat equation support for the FreeCAD Tool Server.

Provides:
  write_transient_heat_sif  — write a transient heat .sif file
  write_startinfo           — re-exported from elmer_solver for convenience
  get_all_vtu_stats         — parse all .vtu files in a directory and return time-series stats
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from elmer_solver import _parse_vtu_field, write_startinfo  # noqa: F401


# ---------------------------------------------------------------------------
# SIF writer — transient heat equation
# ---------------------------------------------------------------------------

def write_transient_heat_sif(
    working_dir: Path,
    *,
    heat_conductivity: float = 2.5,
    density: float = 2700.0,
    heat_capacity: float = 1250.0,
    timestep_intervals: int = 10000,
    timestep_size_expr: str = "$10*365*24*3600",
    bdf_order: int = 2,
    output_intervals: int = 100,
    initial_conditions: list[dict],
    boundary_conditions: list[dict],
    heat_source: float = 0.0,
    coordinate_scaling: Optional[float] = None,
    sif_name: str = "case.sif",
) -> Path:
    """
    Write a transient heat equation .sif file.

    Parameters
    ----------
    working_dir : Path
        Directory to write the .sif into (must already contain mesh files).
    heat_conductivity : float
        W/(m·K).
    density : float
        kg/m³.
    heat_capacity : float
        J/(kg·K).
    timestep_intervals : int
        Number of time steps.
    timestep_size_expr : str
        Elmer expression for step size in seconds.
        May be a numeric string ("315360000") or an Elmer variable expression
        ("$10*365*24*3600").
    bdf_order : int
        BDF order (1 or 2). 2 = second-order accurate in time.
    output_intervals : int
        Write VTU every N steps.
    initial_conditions : list[dict]
        Each entry must have:
          - "body_indices": list[int]  — which Body IDs to apply this IC to
          - "type": "constant" | "tabular"
          For "constant":
            - "value": float
          For "tabular":
            - "variable": str   e.g. "coordinate 2"
            - "table": list of [coord, value] pairs
    boundary_conditions : list[dict]
        Each entry must have:
          - "tags": list[int]          — boundary tag integers
          Optionally:
          - "temperature": float       — Dirichlet BC
          - "heat_flux": float         — Neumann BC
    heat_source : float
        Volumetric heat source W/kg. 0.0 = no body force written.
    coordinate_scaling : float | None
        If provided, added to Simulation section.
    sif_name : str
        Filename of the .sif output.

    Returns
    -------
    Path
        Absolute path to the written .sif file.
    """
    lines: list[str] = []

    def s(line: str = "") -> None:
        lines.append(line)

    # ---- Header ----
    s("Header")
    s("  CHECK KEYWORDS Warn")
    s('  Mesh DB "." "."')
    s('  Include Path ""')
    s('  Results Directory ""')
    s("End")
    s()

    # ---- Simulation ----
    s("Simulation")
    s("  Max Output Level = 5")
    s("  Coordinate System = Cartesian")
    s("  Coordinate Mapping(3) = 1 2 3")
    if coordinate_scaling is not None:
        s(f"  Coordinate Scaling = {coordinate_scaling}")
    s("  Simulation Type = Transient")
    s("  Steady State Max Iterations = 1")
    s(f"  Output Intervals = {output_intervals}")
    s("  Timestepping Method = BDF")
    s(f"  BDF Order = {bdf_order}")
    s(f"  Timestep intervals = {timestep_intervals}")
    s(f"  Timestep Sizes = {timestep_size_expr}")
    s('  Solver Input File = "case.sif"')
    s('  Post File = "case.vtu"')
    s("End")
    s()

    # ---- Constants ----
    s("Constants")
    s("  Gravity(4) = 0 -1 0 9.82")
    s("  Stefan Boltzmann = 5.67e-08")
    s("  Permittivity of Vacuum = 8.8542e-12")
    s("  Boltzmann Constant = 1.3807e-23")
    s("  Unit Charge = 1.602e-19")
    s("End")
    s()

    # ---- Bodies — one per IC group, or just Body 1 if all share the same IC ----
    # Build a mapping from body_index → IC number
    body_to_ic: dict[int, int] = {}
    for ic_idx, ic in enumerate(initial_conditions, start=1):
        for body_idx in ic.get("body_indices", [1]):
            body_to_ic[body_idx] = ic_idx

    # Collect all unique body indices
    all_body_indices = sorted(body_to_ic.keys()) if body_to_ic else [1]

    for body_idx in all_body_indices:
        s(f"Body {body_idx}")
        s(f"  Target Bodies(1) = {body_idx}")
        s(f'  Name = "Body {body_idx}"')
        s("  Equation = 1")
        s("  Material = 1")
        ic_num = body_to_ic.get(body_idx)
        if ic_num is not None:
            s(f"  Initial condition = {ic_num}")
        if heat_source != 0.0:
            s("  Body Force = 1")
        s("End")
        s()

    # ---- Solver ----
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

    # ---- Equation ----
    s("Equation 1")
    s('  Name = "Heat Equation"')
    s("  Active Solvers(1) = 1")
    s("End")
    s()

    # ---- Material ----
    s("Material 1")
    s('  Name = "Material"')
    s(f"  Heat Capacity = {heat_capacity}")
    s(f"  Heat Conductivity = {heat_conductivity}")
    s(f"  Density = {density}")
    s("End")
    s()

    # ---- Body Force (optional) ----
    if heat_source != 0.0:
        s("Body Force 1")
        s('  Name = "Heating"')
        s(f"  Heat Source = {heat_source}")
        s("End")
        s()

    # ---- Initial Conditions ----
    for ic_idx, ic in enumerate(initial_conditions, start=1):
        ic_type = ic.get("type", "constant")
        s(f"Initial Condition {ic_idx}")
        s(f'  Name = "IC{ic_idx}"')
        if ic_type == "constant":
            val = ic.get("value", 293.0)
            s(f"  Temperature = {val}")
        elif ic_type == "tabular":
            variable = ic.get("variable", "coordinate 2")
            table = ic.get("table", [])
            s(f"  Temperature = Variable {variable}")
            s("   Real")
            for coord, val in table:
                s(f"     {coord} {val}")
            s("  End")
        s("End")
        s()

    # ---- Boundary Conditions ----
    for i, bc in enumerate(boundary_conditions, start=1):
        tags = bc.get("tags", [])
        tag_str = " ".join(str(t) for t in tags)
        n = len(tags)
        s(f"Boundary Condition {i}")
        s(f'  Name = "BC{i}"')
        s(f"  Target Boundaries({n}) = {tag_str}")
        if "temperature" in bc:
            s(f"  Temperature = {bc['temperature']}")
        if "heat_flux" in bc:
            s(f"  Heat Flux = {bc['heat_flux']}")
        s("End")
        s()

    sif_path = working_dir / sif_name
    sif_path.write_text("\n".join(lines), encoding="utf-8")
    return sif_path


# ---------------------------------------------------------------------------
# VTU time-series statistics
# ---------------------------------------------------------------------------

def get_all_vtu_stats(
    working_dir: Path,
    field_name: str = "Temperature",
) -> dict:
    """
    Parse ALL .vtu files in working_dir and return time-series statistics.

    Returns a dict with:
      - "steps": list of {vtu_file, step_num, min, max, mean}  (sorted by step)
      - "final_min", "final_max", "final_mean": from the last VTU file
      - "field_name": the queried field name
      - "vtu_count": number of VTU files processed
    """
    vtu_files = sorted(working_dir.glob("*.vtu"))
    if not vtu_files:
        raise RuntimeError(f"No .vtu files found in {working_dir}")

    steps = []
    errors = []
    for vtu in vtu_files:
        # Extract step number from filename, e.g. case_t0001.vtu → 1
        stem = vtu.stem
        step_num: int | None = None
        # Try to parse trailing digits after last underscore or 't'
        import re
        m = re.search(r'[_t](\d+)$', stem)
        if m:
            step_num = int(m.group(1))
        try:
            values = _parse_vtu_field(vtu, field_name)
            if not values:
                errors.append(f"{vtu.name}: empty field")
                continue
            n = len(values)
            steps.append({
                "vtu_file": str(vtu),
                "step_num": step_num,
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / n,
                "node_count": n,
            })
        except Exception as exc:
            errors.append(f"{vtu.name}: {exc}")

    if not steps:
        raise RuntimeError(
            f"Could not parse any VTU files for field '{field_name}'. Errors: {errors}"
        )

    last = steps[-1]
    return {
        "field_name": field_name,
        "vtu_count": len(steps),
        "steps": steps,
        "final_min": last["min"],
        "final_max": last["max"],
        "final_mean": last["mean"],
        "parse_errors": errors,
    }
