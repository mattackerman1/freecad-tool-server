"""
Elmer FEM — Tutorial 28: Coupled Temperature and Flow in a Toy Glacier.

Steady-state simulation coupling:
  1. Heat Equation — temperature distribution in ice and bedrock
  2. Navier-Stokes — ice flow with temperature-dependent (Arrhenius) viscosity

The glacier geometry comes from the ToyGlacierTemperatureAndFlow tutorial mesh.
Two bodies:
  - Body 1: ice (density=910, Arrhenius viscosity, Boussinesq gravity)
  - Body 2: bedrock (just heat)

Boundary conditions:
  - Surface (glacier top): T = -10 degC, free-slip (no normal velocity)
  - Bedrock bottom: heat flux = 0.02 W/m2, no-slip
  - Sides: no-slip (symmetry)

Temperature-dependent viscosity (Glen's flow law, linearized for Elmer):
  mu = (2 * A(T))^(-1/3)
  A(T) = 3 * 1.916e3 * exp(-139e3 / (8.314 * (T+273.15)))

Functions:
  write_glacier_flow_sif  -- write case.sif
  write_startinfo         -- write ELMERSOLVER_STARTINFO
  run_glacier_flow        -- run ElmerSolver (timeout=300 s)
  get_stats               -- parse last VTU, return temperature and velocity stats
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ELMER_BIN = Path(r"C:\Elmer\ElmerFEM-nogui-nompi-Windows-AMD64\bin")
ELMER_SOLVER = ELMER_BIN / "ElmerSolver.exe"

TUTORIAL_MESH_DIR = Path(
    r"C:\Elmer\tutorials\tutorials-GUI-files\ToyGlacierTemperatureAndFlow"
)


def elmer_available() -> bool:
    return ELMER_SOLVER.exists()


# ---------------------------------------------------------------------------
# SIF writer
# ---------------------------------------------------------------------------

def write_glacier_flow_sif(
    work_dir: str | Path,
    *,
    ice_density: float = 910.0,
    bedrock_density: float = 2800.0,
    ice_heat_capacity: float = 2093.0,
    bedrock_heat_capacity: float = 800.0,
    surface_temperature: float = -10.0,
    bottom_heat_flux: float = 0.02,
    steady_state_max_iter: int = 50,
    nonlinear_max_iter: int = 10,
    ice_body_tag: int = 1,
    bedrock_body_tag: int = 2,
    surface_bc_tag: int = 3,
    bottom_bc_tag: int = 1,
    side_bc_tags: list[int] | None = None,
    **kwargs,
) -> Path:
    """
    Write case.sif for the coupled glacier temperature + flow simulation.

    Ice viscosity follows Glen's flow law (Arrhenius):
      mu = (2*3*1.916e3 * exp(-139e3 / (8.314*(T+273.15))))^(-1/3)
    expressed as a MATC variable-temperature function.

    Heat conductivity of ice (temperature-dependent):
      k_ice = 9.828 * exp(-5.7e-3 * (T+273.15))

    Heat capacity of ice (temperature-dependent):
      Cp_ice = 146.3 + 7.253*(T+273.15)

    Returns path to the written SIF file.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if side_bc_tags is None:
        side_bc_tags = [2, 4]

    side_tag_str = " ".join(str(t) for t in side_bc_tags)
    n_side_tags = len(side_bc_tags)

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
    s("  Simulation Type = Steady state")
    s(f"  Steady State Max Iterations = {steady_state_max_iter}")
    s("  Output Intervals = 1")
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
    # Ice body (Heat + Flow)
    s("Body 1")
    s(f"  Target Bodies(1) = {ice_body_tag}")
    s('  Name = "Ice"')
    s("  Equation = 1")
    s("  Material = 1")
    s("  Body Force = 1")
    s("End")
    s()
    # Bedrock body (Heat only)
    s("Body 2")
    s(f"  Target Bodies(1) = {bedrock_body_tag}")
    s('  Name = "Bedrock"')
    s("  Equation = 2")
    s("  Material = 2")
    s("End")
    s()
    # Solver 1: Heat equation (applies to both bodies via equation sets)
    s("Solver 1")
    s("  Equation = Heat Equation")
    s("  Variable = Temperature")
    s('  Procedure = "HeatSolve" "HeatSolver"')
    s("  Exec Solver = Always")
    s("  Stabilize = True")
    s("  Optimize Bandwidth = True")
    s("  Steady State Convergence Tolerance = 1.0e-5")
    s(f"  Nonlinear System Max Iterations = {nonlinear_max_iter}")
    s("  Nonlinear System Convergence Tolerance = 1.0e-6")
    s("  Nonlinear System Newton After Iterations = 3")
    s("  Nonlinear System Newton After Tolerance = 1.0e-3")
    s("  Nonlinear System Relaxation Factor = 1")
    s("  Linear System Solver = Iterative")
    s("  Linear System Iterative Method = BiCGStab")
    s("  Linear System Max Iterations = 500")
    s("  Linear System Convergence Tolerance = 1.0e-8")
    s("  BiCGstabl polynomial degree = 2")
    s("  Linear System Preconditioning = ILU0")
    s("  Linear System ILUT Tolerance = 1.0e-3")
    s("  Linear System Abort Not Converged = False")
    s("  Linear System Residual Output = 10")
    s("  Linear System Precondition Recompute = 1")
    s("End")
    s()
    # Solver 2: Navier-Stokes (ice only)
    s("Solver 2")
    s("  Equation = Navier-Stokes")
    s("  Variable = Flow Solution[Velocity:2 Pressure:1]")
    s('  Procedure = "FlowSolve" "FlowSolver"')
    s("  Exec Solver = Always")
    s("  Stabilize = True")
    s("  Optimize Bandwidth = True")
    s("  Steady State Convergence Tolerance = 1.0e-4")
    s(f"  Nonlinear System Max Iterations = {nonlinear_max_iter}")
    s("  Nonlinear System Convergence Tolerance = 1.0e-4")
    s("  Nonlinear System Newton After Iterations = 3")
    s("  Nonlinear System Newton After Tolerance = 1.0e-3")
    s("  Nonlinear System Relaxation Factor = 1")
    s("  Linear System Solver = Iterative")
    s("  Linear System Iterative Method = BiCGStab")
    s("  Linear System Max Iterations = 500")
    s("  Linear System Convergence Tolerance = 1.0e-8")
    s("  BiCGstabl polynomial degree = 2")
    s("  Linear System Preconditioning = ILU0")
    s("  Linear System ILUT Tolerance = 1.0e-3")
    s("  Linear System Abort Not Converged = False")
    s("  Linear System Residual Output = 10")
    s("  Linear System Precondition Recompute = 1")
    s("End")
    s()
    # Equation 1: ice (heat + flow)
    s("Equation 1")
    s('  Name = "Heat and Flow"')
    s("  Active Solvers(2) = 1 2")
    s("  Convection = Computed")
    s("End")
    s()
    # Equation 2: bedrock (heat only)
    s("Equation 2")
    s('  Name = "Just Heat"')
    s("  Active Solvers(1) = 1")
    s("End")
    s()
    # Material 1: ice with temperature-dependent properties
    s("Material 1")
    s('  Name = "Ice"')
    s(f"  Density = {ice_density}")
    s('  Viscosity = Variable Temperature')
    s('    Real MATC "(2.0*3.0*1.916E03 * exp( -139.0E03/(8.314 *(tx+273.15))))^(-1.0/3.0)"')
    s('  Heat Capacity = Variable Temperature')
    s('    Real MATC "146.3+(7.253*(tx+273.15))"')
    s('  Heat Conductivity = Variable Temperature')
    s('    Real MATC "9.828*exp(-5.7E-03*(tx+273.15))"')
    s("End")
    s()
    # Material 2: bedrock (constant properties)
    s("Material 2")
    s('  Name = "Bedrock"')
    s(f"  Density = {bedrock_density}")
    s(f"  Heat Capacity = {bedrock_heat_capacity}")
    s("  Heat Conductivity = 3.0")
    s("End")
    s()
    # Body force: gravity on ice (Force 2 = rho*g in -y direction)
    s("Body Force 1")
    s('  Name = "Gravity"')
    s(f"  Force 2 = Real {-ice_density * 9.82}")
    s("End")
    s()
    # Boundary Condition 1: glacier surface (cold, free surface in y)
    s("Boundary Condition 1")
    s(f"  Target Boundaries(1) = {surface_bc_tag}")
    s('  Name = "Tsurface"')
    s(f"  Temperature = {surface_temperature}")
    s("  Velocity 2 = 0.0")
    s("End")
    s()
    # Boundary Condition 2: bedrock bottom (geothermal flux, no-slip)
    s("Boundary Condition 2")
    s(f"  Target Boundaries(1) = {bottom_bc_tag}")
    s('  Name = "Tflux"')
    s(f"  Heat Flux = {bottom_heat_flux}")
    s("  Velocity 1 = 0.0")
    s("  Velocity 2 = 0.0")
    s("End")
    s()
    # Boundary Condition 3: side walls (no-slip, zero horizontal velocity)
    s("Boundary Condition 3")
    s(f"  Target Boundaries({n_side_tags}) = {side_tag_str}")
    s('  Name = "Symmetry"')
    s("  Velocity 1 = 0.0")
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

def run_glacier_flow(work_dir: str | Path, timeout: int = 300) -> dict:
    """
    Run ElmerSolver in work_dir for the coupled glacier flow case.

    Returns dict with keys: returncode, stdout, stderr, converged, elapsed_seconds,
    log_snippet.
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
        combined = stdout + stderr
        return {
            "returncode": -1,
            "converged": False,
            "elapsed_seconds": elapsed,
            "stdout": stdout[-2000:],
            "stderr": f"ElmerSolver timed out after {timeout}s\n" + stderr[-500:],
            "log_snippet": combined[-3000:],
        }

    elapsed = round(time.time() - t0, 2)
    combined = proc.stdout + proc.stderr
    converged = "ALL DONE" in combined
    return {
        "returncode": proc.returncode,
        "converged": converged,
        "elapsed_seconds": elapsed,
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-1000:],
        "log_snippet": combined[-3000:],
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
# Statistics from last VTU output
# ---------------------------------------------------------------------------

def get_stats(work_dir: str | Path) -> dict:
    """
    Parse the last output VTU file and return temperature and velocity statistics.

    Returns:
      vtu_file              -- name of the VTU parsed
      n_nodes               -- number of nodes
      min_temperature       -- minimum temperature (degC)
      max_temperature       -- maximum temperature (degC)
      temperature_range     -- max - min temperature (degC)
      max_velocity_magnitude -- peak ice flow speed (m/s)
      max_velocity_x        -- max horizontal velocity
      max_velocity_y        -- max vertical velocity
    """
    work_dir = Path(work_dir)

    candidates = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
    if not candidates:
        raise RuntimeError(f"No .vtu files found in {work_dir}")
    vtu = candidates[-1]

    # Temperature field
    temp_data: list[float] | None = None
    for t_name in ("Temperature", "temperature"):
        try:
            temp_data = _parse_vtu_field(vtu, t_name)
            break
        except RuntimeError:
            continue

    t_min = min(temp_data) if temp_data else None
    t_max = max(temp_data) if temp_data else None
    t_range = (t_max - t_min) if (t_min is not None and t_max is not None) else None
    n_nodes = len(temp_data) if temp_data else 0

    # Velocity field
    max_vel = None
    max_vx = None
    max_vy = None
    try:
        raw_flow: list[float] | None = None
        for v_name in ("Flow Solution", "velocity", "Velocity"):
            try:
                raw_flow = _parse_vtu_field(vtu, v_name)
                break
            except RuntimeError:
                continue
        if raw_flow:
            n_dof = len(raw_flow)
            if n_dof % 3 == 0:
                nn = n_dof // 3
                vx = [raw_flow[3 * i] for i in range(nn)]
                vy = [raw_flow[3 * i + 1] for i in range(nn)]
            else:
                nn = n_dof // 2
                vx = [raw_flow[2 * i] for i in range(nn)]
                vy = [raw_flow[2 * i + 1] for i in range(nn)]
            mags = [(vx[i] ** 2 + vy[i] ** 2) ** 0.5 for i in range(nn)]
            max_vel = max(mags)
            max_vx = max(abs(v) for v in vx)
            max_vy = max(abs(v) for v in vy)
    except Exception:
        pass

    return {
        "vtu_file": vtu.name,
        "n_nodes": n_nodes,
        "min_temperature": round(t_min, 4) if t_min is not None else None,
        "max_temperature": round(t_max, 4) if t_max is not None else None,
        "temperature_range": round(t_range, 4) if t_range is not None else None,
        "max_velocity_magnitude": max_vel,
        "max_velocity_x": max_vx,
        "max_velocity_y": max_vy,
    }
