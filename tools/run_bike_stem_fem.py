from __future__ import annotations

import json
import math
import os
import shutil
import time
from pathlib import Path

import FreeCAD
import Import
import ObjectsFem
import Part


ROOT = Path(__file__).resolve().parents[1]
STEP = ROOT / "output" / "codex_bike_stem_researched_v6_lightweight.step"
OUT = ROOT / "output" / "fem" / "bike_stem_v6_lightweight"
CCX = Path(r"C:\Program Files\FreeCAD 1.1\bin\ccx.exe")
GMSH = Path(r"C:\Program Files\FreeCAD 1.1\bin\gmsh.exe")

STEERER_FACE = "Face3"
HANDLEBAR_FACE = "Face94"
STEERER_AXIS_X = 0.75
HANDLEBAR_CENTER_X = 45.15
MOMENT_ARM_MM = HANDLEBAR_CENTER_X - STEERER_AXIS_X


LOAD_CASES = [
    {
        "name": "severe",
        "steering_torque_nm": 100.0,
        "vertical_n": -600.0,
        "fore_aft_n": -600.0,
    },
    {
        "name": "extreme",
        "steering_torque_nm": 175.0,
        "vertical_n": -1200.0,
        "fore_aft_n": -1200.0,
    },
]


def assert_environment() -> dict:
    checks = {
        "freecad_version": FreeCAD.Version(),
        "step_exists": STEP.exists(),
        "ccx_exists": CCX.exists(),
        "gmsh_exists": GMSH.exists(),
    }
    import Part  # noqa: F401
    from femtools import ccxtools  # noqa: F401
    from femmesh import gmshtools  # noqa: F401
    checks["freecad_fem_modules"] = True
    if not checks["step_exists"]:
        raise FileNotFoundError(STEP)
    if not checks["ccx_exists"]:
        raise FileNotFoundError(CCX)
    if not checks["gmsh_exists"]:
        raise FileNotFoundError(GMSH)
    return checks


def imported_body(doc):
    Import.insert(str(STEP), doc.Name)
    doc.recompute()
    solids = [
        o for o in doc.Objects
        if hasattr(o, "Shape") and o.Shape.ShapeType == "Solid" and o.Shape.Volume > 1.0
    ]
    solids.sort(key=lambda o: o.Shape.Volume, reverse=True)
    if not solids:
        raise RuntimeError("No solid body found in STEP import.")
    body = solids[0]
    body.Label = "BikeStemBodyOnly"
    for obj in list(doc.Objects):
        if obj is body:
            continue
        try:
            has_shape = hasattr(obj, "Shape")
            name = obj.Name
        except ReferenceError:
            continue
        if has_shape:
            try:
                doc.removeObject(name)
            except ReferenceError:
                pass
    doc.recompute()
    return body


def add_material(doc, analysis):
    mat = ObjectsFem.makeMaterialSolid(doc, "Aluminum_6061_T6")
    mat.Material = {
        "Name": "Aluminum 6061-T6 approximation",
        "YoungsModulus": "68900 MPa",
        "PoissonRatio": "0.33",
        "Density": "2700 kg/m^3",
    }
    analysis.addObject(mat)
    return mat


def make_gmsh_mesh(doc, analysis, body, workdir: Path):
    mesh = ObjectsFem.makeMeshGmsh(doc, "GmshMesh")
    mesh.Shape = body
    mesh.CharacteristicLengthMax = 5.0
    mesh.CharacteristicLengthMin = 1.2
    mesh.ElementOrder = "1st"
    mesh.ElementDimension = "3D"
    mesh.Algorithm3D = "Automatic"
    mesh.OptimizeStd = True
    mesh.WorkingDirectory = str(workdir)
    analysis.addObject(mesh)
    doc.recompute()

    from femmesh import gmshtools

    gmsh = gmshtools.GmshTools(mesh)
    gmsh.gmsh_bin = str(GMSH)
    err = gmsh.create_mesh()
    doc.recompute()
    if err:
        raise RuntimeError(f"Gmsh failed: {err}")
    if mesh.FemMesh.VolumeCount <= 0:
        raise RuntimeError("Gmsh returned no volume elements.")
    return mesh


def force(analysis, doc, body, ref: str, name: str, magnitude: float, direction):
    v = FreeCAD.Vector(*direction)
    v.normalize()
    line = doc.addObject("Part::Feature", f"{name}_direction")
    line.Shape = Part.makeLine(FreeCAD.Vector(0, 0, 0), v)
    if getattr(line, "ViewObject", None) is not None:
        line.ViewObject.Visibility = False
    doc.recompute()

    con = ObjectsFem.makeConstraintForce(doc, name)
    con.References = [(body, ref)]
    con.Force = FreeCAD.Units.Quantity(f"{abs(float(magnitude))} N")
    con.Direction = (line, ["Edge1"])
    con.Reversed = bool(magnitude < 0)
    analysis.addObject(con)
    return con


def setup_case(doc, body, case: dict, workdir: Path):
    analysis = ObjectsFem.makeAnalysis(doc, f"Analysis_{case['name']}")
    analysis.addObject(body)
    add_material(doc, analysis)

    fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed_steerer_bore")
    fixed.References = [(body, STEERER_FACE)]
    analysis.addObject(fixed)

    steering_force_n = case["steering_torque_nm"] * 1000.0 / MOMENT_ARM_MM
    force(analysis, doc, body, HANDLEBAR_FACE, "Load_vertical", case["vertical_n"], (0, 0, 1))
    force(analysis, doc, body, HANDLEBAR_FACE, "Load_fore_aft", case["fore_aft_n"], (1, 0, 0))
    force(analysis, doc, body, HANDLEBAR_FACE, "Load_steering_torque_equiv", steering_force_n, (0, 1, 0))

    mesh = make_gmsh_mesh(doc, analysis, body, workdir)

    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "SolverCcx")
    solver.AnalysisType = "static"
    solver.GeometricalNonlinearity = "linear"
    solver.ThermoMechSteadyState = False
    solver.MatrixSolverType = "spooles"
    analysis.addObject(solver)
    doc.recompute()
    return analysis, solver, mesh, steering_force_n


def run_ccx(doc, analysis, solver, workdir: Path):
    from femtools import ccxtools

    pref = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
    pref.SetString("ccxBinaryPath", str(CCX))

    fea = ccxtools.FemToolsCcx(analysis, solver)
    fea.update_objects()
    fea.setup_working_dir(str(workdir))
    prereq = fea.check_prerequisites()
    if prereq:
        raise RuntimeError(f"FEM prerequisites not met: {prereq}")
    msg = fea.write_inp_file()
    start = time.time()
    run_msg = fea.ccx_run()
    elapsed = time.time() - start
    fea.load_results()
    doc.recompute()
    result = next((o for o in doc.Objects if o.isDerivedFrom("Fem::FemResultObject")), None)
    if result is None:
        raise RuntimeError("CalculiX finished but no FemResultObject was loaded.")
    return result, {"write_message": str(msg or ""), "run_message": str(run_msg or ""), "elapsed_seconds": elapsed}


def stats(result) -> dict:
    vm = list(getattr(result, "vonMises", []) or [])
    disp = list(getattr(result, "DisplacementLengths", []) or [])
    disp_vec = list(getattr(result, "DisplacementVectors", []) or [])
    return {
        "result_object": result.Name,
        "node_count": len(vm) or len(disp),
        "max_von_mises_mpa": max(vm) if vm else None,
        "min_von_mises_mpa": min(vm) if vm else None,
        "max_displacement_mm": max(disp) if disp else None,
        "max_displacement_vector_xyz_mm": (
            [
                disp_vec[disp.index(max(disp))].x,
                disp_vec[disp.index(max(disp))].y,
                disp_vec[disp.index(max(disp))].z,
            ]
            if disp and disp_vec else None
        ),
    }


def result_points(result):
    mesh_obj = getattr(result, "Mesh", None)
    fem_mesh = getattr(mesh_obj, "FemMesh", None)
    if fem_mesh is None:
        return [], [], []
    node_ids = list(getattr(result, "NodeNumbers", []) or fem_mesh.Nodes)
    pts = [fem_mesh.getNodeById(int(i)) for i in node_ids]
    vm = list(getattr(result, "vonMises", []) or [])
    disp = list(getattr(result, "DisplacementLengths", []) or [])
    return pts, vm, disp


def write_plot(result, case: dict, out_png: Path, value_kind: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pts, vm, disp = result_points(result)
    vals = vm if value_kind == "stress" else disp
    title = "Von Mises stress (MPa)" if value_kind == "stress" else "Displacement magnitude (mm)"
    if not pts or not vals:
        raise RuntimeError(f"No result points available for {value_kind} plot.")
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    fig = plt.figure(figsize=(10, 7), dpi=160)
    ax = fig.add_subplot(111, projection="3d")
    sc = ax.scatter(xs, ys, zs, c=vals, s=2, cmap="turbo")
    ax.set_title(f"Bike stem FEM {case['name']}: {title}")
    ax.set_xlabel("X mm")
    ax.set_ylabel("Y mm")
    ax.set_zlabel("Z mm")
    ax.view_init(elev=22, azim=-55)
    fig.colorbar(sc, ax=ax, shrink=0.72, pad=0.08, label=title)
    fig.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)


def run_case(case: dict) -> dict:
    workdir = OUT / f"{case['name']}_{int(time.time())}"
    workdir.mkdir(parents=True)

    doc = FreeCAD.newDocument(f"bike_stem_fem_{case['name']}")
    try:
        body = imported_body(doc)
        analysis, solver, mesh, steering_force_n = setup_case(doc, body, case, workdir)
        result, solver_info = run_ccx(doc, analysis, solver, workdir)
        stress_png = OUT / f"bike_stem_v6_{case['name']}_von_mises.png"
        disp_png = OUT / f"bike_stem_v6_{case['name']}_displacement.png"
        write_plot(result, case, stress_png, "stress")
        write_plot(result, case, disp_png, "displacement")
        fcstd = OUT / f"bike_stem_v6_{case['name']}.FCStd"
        doc.saveAs(str(fcstd))
        return {
            "case": case,
            "body_volume_mm3": body.Shape.Volume,
            "fixed_reference": STEERER_FACE,
            "load_reference": HANDLEBAR_FACE,
            "moment_arm_mm": MOMENT_ARM_MM,
            "steering_equivalent_lateral_force_n": steering_force_n,
            "mesh": {
                "nodes": mesh.FemMesh.NodeCount,
                "volume_elements": mesh.FemMesh.VolumeCount,
                "max_cell_size_mm": 5.0,
                "min_cell_size_mm": 1.2,
                "element_order": "linear tetrahedral",
            },
            "solver": solver_info,
            "results": stats(result),
            "files": {
                "fcstd": str(fcstd),
                "stress_png": str(stress_png),
                "displacement_png": str(disp_png),
                "working_dir": str(workdir),
            },
        }
    finally:
        FreeCAD.closeDocument(doc.Name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {
        "environment": assert_environment(),
        "source_step": str(STEP),
        "assumptions": [
            "Main stem body only; separate faceplate omitted and clamp load is transferred to the body handlebar bore.",
            f"Steerer bore constrained with fixed support on {STEERER_FACE}.",
            f"Handlebar loads distributed on cylindrical clamp bore {HANDLEBAR_FACE}.",
            "Steering torque represented as an equivalent lateral force at the handlebar clamp centerline.",
            "Linear static CalculiX solve with aluminum 6061-T6 approximation.",
        ],
        "cases": [],
    }
    for case in LOAD_CASES:
        summary["cases"].append(run_case(case))
    summary_path = OUT / "bike_stem_v6_fem_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
