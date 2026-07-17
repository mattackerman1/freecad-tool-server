from __future__ import annotations

import math
from pathlib import Path

import FreeCAD
import Import


ROOT = Path(__file__).resolve().parents[1]
STEP = ROOT / "output" / "codex_bike_stem_researched_v6_lightweight.step"


def axis_name(vec) -> str:
    comps = {"x": abs(vec.x), "y": abs(vec.y), "z": abs(vec.z)}
    return max(comps, key=comps.get)


def main() -> None:
    doc = FreeCAD.newDocument("bike_stem_face_probe")
    Import.insert(str(STEP), doc.Name)
    doc.recompute()

    solids = [
        o for o in doc.Objects
        if hasattr(o, "Shape") and o.Shape.ShapeType == "Solid" and o.Shape.Volume > 1.0
    ]
    solids.sort(key=lambda o: o.Shape.Volume, reverse=True)
    body = solids[0]
    print(f"body={body.Name} label={body.Label} volume={body.Shape.Volume:.1f}")
    print("idx type axis radius area center bbox")
    for idx, face in enumerate(body.Shape.Faces, start=1):
        surf = face.Surface
        stype = type(surf).__name__
        center = face.CenterOfMass
        bb = face.BoundBox
        radius = getattr(surf, "Radius", None)
        axis = ""
        if hasattr(surf, "Axis"):
            axis = axis_name(surf.Axis)
        if stype in {"Cylinder", "Plane"} or radius:
            print(
                f"{idx:3d} {stype:12s} {axis:1s} "
                f"{radius if radius is not None else 0:8.3f} "
                f"{face.Area:10.1f} "
                f"({center.x:7.2f},{center.y:7.2f},{center.z:7.2f}) "
                f"X[{bb.XMin:6.1f},{bb.XMax:6.1f}] "
                f"Y[{bb.YMin:6.1f},{bb.YMax:6.1f}] "
                f"Z[{bb.ZMin:6.1f},{bb.ZMax:6.1f}]"
            )

    FreeCAD.closeDocument(doc.Name)


if __name__ == "__main__":
    main()
