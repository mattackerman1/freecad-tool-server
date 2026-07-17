"""
Elmer FEM — Tutorial 24: Rayleigh-Benard convection (buoyancy-driven flow).

Physics: Coupled Navier-Stokes + Heat Equation with Boussinesq approximation.
A rectangular fluid layer (water) is heated from below and cooled from above.
Gravity-driven convection rolls develop when the Rayleigh number exceeds ~1708.

Reference case: RayleighBenardGUI/egproject.xml
  - 200 transient timesteps, dt = 2.0 s
  - BDF order 1
  - Gravity = 0 -1 0 9.82  (m/s^2 in -Y direction)
  - Water at room temperature:
      density              = 998.3 kg/m^3
      viscosity            = 1.002e-3 Pa.s
      heat conductivity    = 0.58  W/(m.K)
      heat capacity        = 4183  J/(kg.K)
      heat expansion coeff = 0.207e-3 1/K
      reference temperature = 293 K
  - Bottom BC: T = 293.5 K (warm),  velocity = 0
  - Top    BC: T = 293.0 K (cool),  velocity = 0

Functions:
  write_rayleigh_benard_sif  -- write case.sif
  write_startinfo            -- write ELMERSOLVER_STARTINFO (UTF-8 no BOM)
  run_rayleigh_benard        -- run ElmerSolver subprocess; timeout=300 s
  get_stats                  -- parse last VTU, return temperature + velocity stats
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


def write_rayleigh_benard_sif(
    work_dir,
    *,
    timestep_intervals=200,
    timestep_size=2.0,
    bdf_order=1,
    density=998.3,
    viscosity=1.002e-3,
    heat_conductivity=0.58,
    heat_capacity=4183.0,
    heat_expansion_coeff=0.207e-3,
    reference_temperature=293.0,
    bottom_temperature=293.5,
    top_temperature=293.0,
    initial_temperature=293.0,
    initial_velocity_1=1.0e-9,
    bottom_bc_tag=1,
    top_bc_tag=2,
    sif_name="case.sif",
):
    """Write case.sif for the Rayleigh-Benard convection tutorial."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    lines = []

    def s(line=""):
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
    s("  Timestep intervals(1) = {}".format(timestep_intervals))
    s("  Timestep Sizes(1) = {}".format(timestep_size))
    s("  Timestepping Method = BDF")
    s("  BDF Order = {}".format(bdf_order))
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
    s("  Initial Condition = 1")
    s("End")
    s()
    s("Solver 1")
    s("  Equation = Navier-Stokes")
    s("  Variable = Flow Solution[Velocity:2 Pressure:1]")
    s('  Procedure = "FlowSolve" "FlowSolver"')
    s("  Exec Solver = Always")
    s("  Stabilize = True")
    s("  Bubbles = False")
    s("  Lumped Mass Matrix = False")
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
    s("Solver 2")
    s("  Equation = Heat Equation")
    s("  Variable = Temperature")
    s('  Procedure = "HeatSolve" "HeatSolver"')
    s("  Exec Solver = Always")
    s("  Stabilize = True")
    s("  Bubbles = False")
    s("  Lumped Mass Matrix = False")
    s("  Optimize Bandwidth = True")
    s("  Steady State Convergence Tolerance = 1.0e-5")
    s("  Nonlinear System Convergence Tolerance = 1.0e-8")
    s("  Nonlinear System Max Iterations = 1")
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
    s("  Linear System Residual Output = 1")
    s("  Linear System Precondition Recompute = 1")
    s("End")
    s()
    s("Solver 3")
    s("  Equation = Result Output")
    s('  Procedure = "ResultOutputSolve" "ResultOutputSolver"')
    s("  Output File Name = case")
    s("  Output Format = Vtu")
    s("  Exec Solver = After Timestep")
    s("End")
    s()
    s("Equation 1")
    s('  Name = "Equation 1"')
    s("  Convection = Computed")
    s("  Active Solvers(3) = 1 2 3")
    s("End")
    s()
    s("Material 1")
    s('  Name = "Water (room temperature)"')
    s("  Density = {}".format(density))
    s("  Viscosity = {}".format(viscosity))
    s("  Heat Conductivity = {}".format(heat_conductivity))
    s("  Heat Capacity = {}".format(heat_capacity))
    s("  Heat Expansion Coefficient = {}".format(heat_expansion_coeff))
    s("  Reference Temperature = {}".format(reference_temperature))
    s("End")
    s()
    s("Initial Condition 1")
    s('  Name = "Initial Condition 1"')
    s("  Temperature = {}".format(initial_temperature))
    s("  Velocity 1 = {}".format(initial_velocity_1))
    s("  Velocity 2 = 0")
    s("End")
    s()
    s("Boundary Condition 1")
    s("  Target Boundaries(1) = {}".format(bottom_bc_tag))
    s('  Name = "Bottom"')
    s("  Temperature = {}".format(bottom_temperature))
    s("  Velocity 1 = 0.0")
    s("  Velocity 2 = 0.0")
    s("End")
    s()
    s("Boundary Condition 2")
    s("  Target Boundaries(1) = {}".format(top_bc_tag))
    s('  Name = "Top"')
    s("  Temperature = {}".format(top_temperature))
    s("  Velocity 1 = 0.0")
    s("  Velocity 2 = 0.0")
    s("End")
    s()

    sif_path = work_dir / sif_name
    sif_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sif_path


def write_startinfo(work_dir, sif_name="case.sif"):
    """Write ELMERSOLVER_STARTINFO (UTF-8, no BOM)."""
    work_dir = Path(work_dir)
    p = work_dir / "ELMERSOLVER_STARTINFO"
    p.write_text("{}\n1\n".format(sif_name), encoding="utf-8")
    return p


def run_rayleigh_benard(work_dir, timeout=300):
    """
    Run ElmerSolver in work_dir for the Rayleigh-Benard case.

    Returns dict with returncode, stdout, stderr, converged, elapsed_seconds, log_snippet.
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
            "stdout": stdout[-3000:],
            "stderr": "Timed out after {}s\n".format(timeout) + stderr[-1000:],
            "log_snippet": stdout[-2000:],
        }

    elapsed = round(time.time() - t0, 2)
    combined = proc.stdout + proc.stderr
    converged = "ALL DONE" in combined
    return {
        "returncode": proc.returncode,
        "converged": converged,
        "elapsed_seconds": elapsed,
        "stdout": proc.stdout[-3000:],
        "stderr": proc.stderr[-1000:],
        "log_snippet": combined[-2000:],
    }


def _read_vtu_xml_root(vtu_path):
    """Parse a VTK XML unstructured grid file; return (root_element, binary_data_or_None)."""
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


def _parse_vtu_field(vtu_path, field_name):
    """Extract a named field from a VTU file. Returns flat float list."""
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
                values = list(struct.unpack_from("<{}{}".format(n_vals, pack_char), seg, 4))
                return [float(v) for v in values]

    available = []
    for piece in root.iter("Piece"):
        pd = piece.find("PointData")
        if pd is not None:
            available.extend(da.get("Name", "") for da in pd.findall("DataArray"))
    raise RuntimeError(
        "Field '{}' not found in {}. Available: {}".format(field_name, vtu_path.name, available)
    )


def get_stats(work_dir):
    """
    Parse the last .vtu file from the Rayleigh-Benard run.

    Returns temperature min/max/mean and velocity max magnitude.
    """
    work_dir = Path(work_dir)

    candidates = sorted(work_dir.glob("*.vtu"), key=lambda f: f.stat().st_mtime)
    if not candidates:
        raise RuntimeError("No .vtu files found in {}".format(work_dir))
    vtu = candidates[-1]

    result = {"vtu_file": vtu.name}

    # Temperature
    try:
        temps = _parse_vtu_field(vtu, "Temperature")
        result["temperature_min"] = round(min(temps), 6)
        result["temperature_max"] = round(max(temps), 6)
        result["temperature_mean"] = round(sum(temps) / len(temps), 6)
        result["temperature_node_count"] = len(temps)
    except RuntimeError as exc:
        result["temperature_error"] = str(exc)

    # Flow Solution: [Vx, Vy, P] interleaved per node
    try:
        flow = _parse_vtu_field(vtu, "Flow Solution")
        n_nodes = len(flow) // 3
        vx = [flow[3 * i] for i in range(n_nodes)]
        vy = [flow[3 * i + 1] for i in range(n_nodes)]
        p = [flow[3 * i + 2] for i in range(n_nodes)]
        mags = [(vx[i] ** 2 + vy[i] ** 2) ** 0.5 for i in range(n_nodes)]
        result["max_velocity_magnitude"] = round(max(mags), 8)
        result["max_velocity_x"] = round(max(abs(v) for v in vx), 8)
        result["max_velocity_y"] = round(max(abs(v) for v in vy), 8)
        result["pressure_min"] = round(min(p), 6)
        result["pressure_max"] = round(max(p), 6)
        result["velocity_node_count"] = n_nodes
    except RuntimeError:
        try:
            vel = _parse_vtu_field(vtu, "Velocity")
            n_nodes = len(vel) // 2
            vx = [vel[2 * i] for i in range(n_nodes)]
            vy = [vel[2 * i + 1] for i in range(n_nodes)]
            mags = [(vx[i] ** 2 + vy[i] ** 2) ** 0.5 for i in range(n_nodes)]
            result["max_velocity_magnitude"] = round(max(mags), 8)
            result["velocity_node_count"] = n_nodes
        except RuntimeError as exc:
            result["velocity_error"] = str(exc)

    return result
