"""
Elmer passive/active elements support for transient heat simulations.
Allows parts of geometry to be activated/deactivated during simulation.

Tutorial reference: Heat Equation – 2D – Active and Passive elements
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def write_passive_elements_sif(
    working_dir: Path,
    *,
    bodies: list[dict],
    materials: list[dict],
    body_forces: list[dict],
    initial_conditions: list[dict],
    boundary_conditions: list[dict],
    timestep_intervals: int,
    timestep_sizes: float,
    bdf_order: int = 2,
    output_intervals: int = 1,
    sif_name: str = "case.sif",
) -> Path:
    """
    Write a transient heat equation .sif file with passive element support.

    Parameters
    ----------
    bodies : list of dicts with keys:
        target_body_idx  : int   – Elmer body index from mesh
        material_idx     : int   – 1-based index into materials list
        body_force_idx   : int | None
        ic_idx           : int | None
    materials : list of dicts with keys:
        density, heat_capacity, heat_conductivity
    body_forces : list of dicts with keys:
        type : "heat_source" | "passive"
        value : float  (for heat_source)
        table : list of (time, value) tuples  (for passive)
    initial_conditions : list of dicts with keys:
        temperature : float
    boundary_conditions : list of dicts with keys:
        tag : int
        temperature : float
        name : str (optional)
    """
    lines: list[str] = []

    # Header
    lines += [
        "Header",
        '  CHECK KEYWORDS Warn',
        '  Mesh DB "." "."',
        '  Include Path ""',
        '  Results Directory ""',
        "End",
        "",
    ]

    # Simulation
    lines += [
        "Simulation",
        "  Max Output Level = 5",
        "  Coordinate System = Cartesian",
        "  Coordinate Mapping(3) = 1 2 3",
        "  Simulation Type = Transient",
        "  Steady State Max Iterations = 1",
        f"  Output Intervals = {output_intervals}",
        "  Timestepping Method = BDF",
        f"  BDF Order = {bdf_order}",
        f"  Timestep intervals = {timestep_intervals}",
        f"  Timestep Sizes = {timestep_sizes}",
        "  Solver Input File = case.sif",
        "  Post File = case.vtu",
        "End",
        "",
    ]

    # Constants
    lines += [
        "Constants",
        "  Gravity(4) = 0 -1 0 9.82",
        "  Stefan Boltzmann = 5.67e-08",
        "  Permittivity of Vacuum = 8.8542e-12",
        "  Boltzmann Constant = 1.3807e-23",
        "  Unit Charge = 1.602e-19",
        "End",
        "",
    ]

    # Bodies
    for i, body in enumerate(bodies, start=1):
        lines.append(f"Body {i}")
        lines.append(f"  Target Bodies(1) = {body['target_body_idx']}")
        lines.append(f"  Equation = 1")
        lines.append(f"  Material = {body['material_idx']}")
        if body.get("body_force_idx") is not None:
            lines.append(f"  Body Force = {body['body_force_idx']}")
        if body.get("ic_idx") is not None:
            lines.append(f"  Initial Condition = {body['ic_idx']}")
        lines.append("End")
        lines.append("")

    # Equation
    lines += [
        "Equation 1",
        '  Name = "Heat"',
        "  Active Solvers(1) = 1",
        "End",
        "",
    ]

    # Solver
    lines += [
        "Solver 1",
        '  Equation = "Heat Equation"',
        "  Variable = Temperature",
        '  Procedure = "HeatSolve" "HeatSolver"',
        "  Exec Solver = Always",
        "  Stabilize = True",
        "  Steady State Convergence Tolerance = 1.0e-5",
        "  Nonlinear System Convergence Tolerance = 1.0e-7",
        "  Nonlinear System Max Iterations = 20",
        "  Nonlinear System Newton After Iterations = 3",
        "  Nonlinear System Newton After Tolerance = 1.0e-3",
        "  Nonlinear System Relaxation Factor = 1",
        "  Linear System Solver = Iterative",
        "  Linear System Iterative Method = BiCGStab",
        "  Linear System Max Iterations = 500",
        "  Linear System Convergence Tolerance = 1.0e-10",
        "  Linear System Preconditioning = ILU0",
        "  Linear System Abort Not Converged = False",
        "  Linear System Residual Output = 10",
        "End",
        "",
    ]

    # Materials
    for i, mat in enumerate(materials, start=1):
        name = mat.get("name", f"Material{i}")
        lines.append(f"Material {i}")
        lines.append(f'  Name = "{name}"')
        lines.append(f"  Density = {mat['density']}")
        lines.append(f"  Heat Capacity = {mat['heat_capacity']}")
        lines.append(f"  Heat Conductivity = {mat['heat_conductivity']}")
        lines.append("End")
        lines.append("")

    # Body Forces
    for i, bf in enumerate(body_forces, start=1):
        name = bf.get("name", f"BodyForce{i}")
        lines.append(f"Body Force {i}")
        lines.append(f'  Name = "{name}"')
        if bf["type"] == "heat_source":
            lines.append(f"  Heat Source = {bf['value']}")
        elif bf["type"] == "passive":
            table = bf["table"]
            lines.append("  Temperature Passive = Variable time")
            lines.append("    Real")
            for t, v in table:
                lines.append(f"      {t} {v}")
            lines.append("    End")
        lines.append("End")
        lines.append("")

    # Initial Conditions
    for i, ic in enumerate(initial_conditions, start=1):
        name = ic.get("name", f"InitialCondition{i}")
        lines.append(f"Initial Condition {i}")
        lines.append(f'  Name = "{name}"')
        lines.append(f"  Temperature = {ic['temperature']}")
        lines.append("End")
        lines.append("")

    # Boundary Conditions
    for i, bc in enumerate(boundary_conditions, start=1):
        name = bc.get("name", f"BC{i}")
        lines.append(f"Boundary Condition {i}")
        lines.append(f"  Target Boundaries(1) = {bc['tag']}")
        lines.append(f'  Name = "{name}"')
        lines.append(f"  Temperature = {bc['temperature']}")
        lines.append("End")
        lines.append("")

    sif_text = "\n".join(lines)
    out_path = Path(working_dir) / sif_name
    out_path.write_text(sif_text)
    return out_path
