"""
FreeCAD session manager â€” one active document at a time.

All FreeCAD interactions funnel through FreeCADSession so the rest of the
server never touches the FreeCAD API directly and we have a single place
to add retries, logging, or multi-session support later.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ShapeMeta:
    """Lightweight metadata stored per shape (avoids re-querying FreeCAD for lists)."""
    name: str
    shape_type: str     # "Box" | "Cylinder"
    position: dict      # {"x", "y", "z"}
    dimensions: dict    # shape-specific


@dataclass
class WireMeta:
    """Metadata for a stored wire (path or profile)."""
    name: str
    wire_type: str   # "arc_path" | "rect_profile"
    dimensions: dict


@dataclass
class FEMState:
    """Tracks all FEM objects attached to the current analysis."""
    analysis_name: str = ""
    mesh_name: str = ""
    material_name: str = ""
    fixed_names: list = field(default_factory=list)
    force_names: list = field(default_factory=list)
    solver_name: str = ""
    results_name: str = ""
    target_shape: str = ""
    working_dir: str = ""

@dataclass
class SessionState:
    session_id: str
    document_name: str
    created_at: datetime
    shapes: dict[str, ShapeMeta] = field(default_factory=dict)
    wires: dict = field(default_factory=dict)   # name â†’ (Part.Wire, WireMeta)
    fem: FEMState = field(default_factory=FEMState)

    @property
    def shape_count(self) -> int:
        return len(self.shapes)


class FreeCADSession:
    """
    Wraps a single FreeCAD document and exposes high-level operations.

    All public methods raise RuntimeError on misuse and propagate FreeCAD
    exceptions up to the route handlers, which convert them to ToolResponse errors.
    """

    def __init__(self) -> None:
        self._doc = None
        self._state: Optional[SessionState] = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._doc is not None

    @property
    def state(self) -> Optional[SessionState]:
        return self._state

    def create_document(self, name: str) -> SessionState:
        """Create (or replace) the active FreeCAD document."""
        from freecad_bridge import get_freecad
        FC = get_freecad()

        # Close existing document cleanly
        if self._doc is not None:
            try:
                FC.closeDocument(self._doc.Name)
            except Exception as exc:
                logger.warning("Could not close previous document: %s", exc)
            self._doc = None
            self._state = None

        self._doc = FC.newDocument(name)
        self._state = SessionState(
            session_id=str(uuid.uuid4()),
            document_name=name,
            created_at=datetime.now(timezone.utc),
        )
        logger.info("Document created: '%s'  session=%s", name, self._state.session_id)
        return self._state

    def close_document(self) -> None:
        if self._doc is None:
            return
        from freecad_bridge import get_freecad
        FC = get_freecad()
        try:
            FC.closeDocument(self._doc.Name)
        except Exception as exc:
            logger.warning("Error closing document: %s", exc)
        self._doc = None
        self._state = None

    # ------------------------------------------------------------------
    # Shape creation
    # ------------------------------------------------------------------

    def add_box(
        self,
        name: str,
        length: float,
        width: float,
        height: float,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        rotation_z: float = 0.0,
    ) -> ShapeMeta:
        doc = self._require_doc()
        self._require_unique_name(name)
        from freecad_bridge import get_freecad
        FC = get_freecad()

        obj = doc.addObject("Part::Box", name)
        obj.Length = length
        obj.Width = width
        obj.Height = height
        obj.Placement = FC.Placement(FC.Vector(x, y, z), FC.Rotation(FC.Vector(0, 0, 1), rotation_z))
        doc.recompute()

        meta = ShapeMeta(
            name=name,
            shape_type="Box",
            position={"x": x, "y": y, "z": z},
            dimensions={"length": length, "width": width, "height": height},
        )
        self._state.shapes[name] = meta
        logger.info("Box '%s' added (L=%.2f W=%.2f H=%.2f) at (%.2f,%.2f,%.2f)",
                    name, length, width, height, x, y, z)
        return meta

    def add_cylinder(
        self,
        name: str,
        radius: float,
        height: float,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        axis: str = "z",
    ) -> ShapeMeta:
        doc = self._require_doc()
        self._require_unique_name(name)
        from freecad_bridge import get_freecad
        FC = get_freecad()

        # Rotation to align cylinder axis (default +Z) with requested axis
        _CYL_AXIS_ROTATION = {
            "z": FC.Rotation(),                              # identity
            "x": FC.Rotation(FC.Vector(0, 1, 0), 90),       # tilt +Z â†’ +X
            "y": FC.Rotation(FC.Vector(1, 0, 0), -90),      # tilt +Z â†’ +Y
        }
        if axis not in _CYL_AXIS_ROTATION:
            raise RuntimeError(f"axis must be 'x', 'y', or 'z'; got '{axis}'.")

        obj = doc.addObject("Part::Cylinder", name)
        obj.Radius = radius
        obj.Height = height
        obj.Placement = FC.Placement(FC.Vector(x, y, z), _CYL_AXIS_ROTATION[axis])
        doc.recompute()

        meta = ShapeMeta(
            name=name,
            shape_type="Cylinder",
            position={"x": x, "y": y, "z": z},
            dimensions={"radius": radius, "height": height},
        )
        self._state.shapes[name] = meta
        logger.info("Cylinder '%s' added (R=%.2f H=%.2f axis=%s) at (%.2f,%.2f,%.2f)",
                    name, radius, height, axis, x, y, z)
        return meta

    def add_cone(
        self,
        name: str,
        radius1: float,
        radius2: float,
        height: float,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        axis: str = "z",
    ) -> ShapeMeta:
        """
        Create a cone or frustum (truncated cone).
        radius1 = bottom radius (at z), radius2 = top radius (at z+height).
        Set radius2=0 for a true point-tip cone.
        axis: 'x'|'y'|'z' â€” direction the cone extends.
        """
        import Part as _Part
        from freecad_bridge import get_freecad
        FC = get_freecad()

        doc = self._require_doc()
        self._require_unique_name(name)

        _AXIS_ROT = {
            "z": FC.Rotation(),
            "x": FC.Rotation(FC.Vector(0, 1, 0), 90),
            "y": FC.Rotation(FC.Vector(1, 0, 0), -90),
        }
        if axis not in _AXIS_ROT:
            raise RuntimeError(f"axis must be 'x', 'y', or 'z'; got '{axis}'.")

        obj = doc.addObject("Part::Cone", name)
        obj.Radius1 = radius1
        obj.Radius2 = radius2
        obj.Height = height
        obj.Placement = FC.Placement(FC.Vector(x, y, z), _AXIS_ROT[axis])
        doc.recompute()

        meta = ShapeMeta(
            name=name,
            shape_type="Cone",
            position={"x": x, "y": y, "z": z},
            dimensions={"radius1": radius1, "radius2": radius2, "height": height, "axis": axis},
        )
        self._state.shapes[name] = meta
        logger.info("Cone '%s' R1=%.2f R2=%.2f H=%.2f axis=%s at (%.2f,%.2f,%.2f)",
                    name, radius1, radius2, height, axis, x, y, z)
        return meta

    # ------------------------------------------------------------------
    # Wing generation (NACA airfoil loft)
    # ------------------------------------------------------------------

    @staticmethod
    def _naca_points(m: float, p: float, t: float, chord: float, n: int = 32):
        """
        Generate closed NACA 4-digit airfoil polygon in the XZ plane.
        m=max camber fraction, p=camber position fraction, t=thickness fraction.
        chord in mm.  Returns list of (x, z) tuples starting at TE,
        going upper surface to LE, then lower surface back to TE.
        """
        import math
        betas = [math.pi * i / n for i in range(n + 1)]
        xs = [(1.0 - math.cos(b)) / 2.0 for b in betas]
        upper, lower = [], []
        for xc in xs:
            yt = (5.0 * t * (
                0.2969 * xc ** 0.5
                - 0.1260 * xc
                - 0.3516 * xc ** 2
                + 0.2843 * xc ** 3
                - 0.1015 * xc ** 4
            ))
            if m > 0.0 and p > 0.0:
                if xc < p:
                    yc = m / p**2 * (2*p*xc - xc**2)
                    dyc = 2*m / p**2 * (p - xc)
                else:
                    yc = m / (1-p)**2 * ((1 - 2*p) + 2*p*xc - xc**2)
                    dyc = 2*m / (1-p)**2 * (p - xc)
                theta = math.atan(dyc)
            else:
                yc, theta = 0.0, 0.0
            import math as _m
            xu = (xc - yt * _m.sin(theta)) * chord
            zu = (yc + yt * _m.cos(theta)) * chord
            xl = (xc + yt * _m.sin(theta)) * chord
            zl = (yc - yt * _m.cos(theta)) * chord
            upper.append((xu, zu))
            lower.append((xl, zl))
        # Full closed loop: upper LE→TE, reverse lower TE→LE (skip duplicate LE/TE)
        pts = upper + list(reversed(lower[1:-1]))
        return pts

    @staticmethod
    def _make_airfoil_wire(FC, Part, pts_xz, span_pos: float, span_axis: str = "y",
                           x_off: float = 0.0, transverse_off: float = 0.0):
        """
        Build a closed Part.Wire from (x, thickness) NACA points.

        span_axis="y" — horizontal wing: chord along X, thickness along Z, span along Y.
        span_axis="z" — vertical fin:   chord along X, thickness along Y, span along Z.
        span_pos:       position along the span axis for this cross-section.
        x_off:          offset applied to chord (X) coordinate (sweep).
        transverse_off: offset applied to the out-of-span/chord axis (dihedral for "y", unused for "z").
        """
        if span_axis == "y":
            vecs = [FC.Vector(x + x_off, span_pos, z + transverse_off) for x, z in pts_xz]
        elif span_axis == "z":
            # thickness direction becomes Y; span goes up Z
            vecs = [FC.Vector(x + x_off, z + transverse_off, span_pos) for x, z in pts_xz]
        else:
            raise RuntimeError(f"span_axis must be 'y' or 'z', got '{span_axis}'")
        vecs.append(vecs[0])  # close
        edges = []
        for i in range(len(vecs) - 1):
            a, b = vecs[i], vecs[i + 1]
            if a.distanceToPoint(b) > 1e-4:
                edges.append(Part.LineSegment(a, b).toShape())
        wire = Part.Wire(edges)
        if not wire.isClosed():
            raise RuntimeError("Airfoil wire failed to close — geometry error.")
        return wire

    def add_wing(
        self,
        name: str,
        root_chord: float,
        tip_chord: float,
        half_span: float,
        thickness_ratio: float = 0.12,
        naca_camber: float = 0.02,
        naca_camber_pos: float = 0.40,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        sweep_le: float = 0.0,
        dihedral: float = 0.0,
        span_axis: str = "y",
    ) -> ShapeMeta:
        """
        Generate a tapered wing half via NACA 4-digit airfoil loft.

        Root cross-section is at y; tip is at y + half_span.
        sweep_le: leading-edge sweep in degrees (positive = aft sweep).
        dihedral: dihedral angle in degrees (positive = tip raised).
        The wing extends in the +Y direction; use mirror_shape for the other side.
        """
        import math
        import Part as _Part
        from freecad_bridge import get_freecad
        FC = get_freecad()

        doc = self._require_doc()
        self._require_unique_name(name)

        if span_axis not in ("y", "z"):
            raise RuntimeError(f"span_axis must be 'y' or 'z', got '{span_axis}'")

        m, p, t = naca_camber, naca_camber_pos, thickness_ratio

        root_pts = self._naca_points(m, p, t, root_chord)
        tip_pts = self._naca_points(m, p, t, tip_chord)

        # Tip offsets: sweep shifts chord (X), dihedral shifts transverse axis
        tip_x_off = half_span * math.tan(math.radians(sweep_le))
        tip_transverse_off = half_span * math.tan(math.radians(dihedral))

        if span_axis == "y":
            root_wire = self._make_airfoil_wire(
                FC, _Part, root_pts, span_pos=y, span_axis="y", x_off=x, transverse_off=z)
            tip_wire = self._make_airfoil_wire(
                FC, _Part, tip_pts, span_pos=y + half_span, span_axis="y",
                x_off=x + tip_x_off, transverse_off=z + tip_transverse_off)
        else:  # span_axis == "z"
            root_wire = self._make_airfoil_wire(
                FC, _Part, root_pts, span_pos=z, span_axis="z", x_off=x, transverse_off=y)
            tip_wire = self._make_airfoil_wire(
                FC, _Part, tip_pts, span_pos=z + half_span, span_axis="z",
                x_off=x + tip_x_off, transverse_off=y + tip_transverse_off)

        try:
            loft = _Part.makeLoft([root_wire, tip_wire], True, False, False)
        except Exception as exc:
            raise RuntimeError(f"Wing loft failed: {exc}") from exc

        if not loft.isValid():
            raise RuntimeError("Wing loft produced invalid geometry.")

        root_bb = root_wire.BoundBox
        tip_bb = tip_wire.BoundBox
        approx_vol = (
            0.5 * (root_chord * root_chord * t + tip_chord * tip_chord * t) * half_span
        )

        feature = self._add_feature(doc, name, loft)
        doc.recompute()

        meta = ShapeMeta(
            name=name,
            shape_type="Wing",
            position={"x": x, "y": y, "z": z},
            dimensions={
                "root_chord": root_chord,
                "tip_chord": tip_chord,
                "half_span": half_span,
                "thickness_ratio": thickness_ratio,
                "naca_camber": naca_camber,
                "naca_camber_pos": naca_camber_pos,
                "sweep_le_deg": sweep_le,
                "dihedral_deg": dihedral,
                "span_axis": span_axis,
                "approx_volume_mm3": round(approx_vol),
            },
        )
        self._state.shapes[name] = meta
        logger.info(
            "Wing '%s' NACA %d%d%02d root_c=%.1f tip_c=%.1f span=%.1f sweep=%.1f dih=%.1f",
            name,
            round(naca_camber * 100), round(naca_camber_pos * 10), round(thickness_ratio * 100),
            root_chord, tip_chord, half_span, sweep_le, dihedral,
        )
        return meta

    def mirror_shape(
        self,
        source_name: str,
        plane: str,
        result_name: str,
        keep_original: bool = True,
    ) -> ShapeMeta:
        """
        Mirror a shape across the XY, XZ, or YZ plane through the origin.
        keep_original=True (default): keep the source and add the mirror as a new shape.
        keep_original=False: consume the source, return only the mirror.
        Use boolean_union(source, mirror) afterward to create a symmetric part.
        """
        from freecad_bridge import get_freecad
        FC = get_freecad()

        doc = self._require_doc()
        obj = self._get_obj(doc, source_name)
        if obj is None:
            raise RuntimeError(f"Shape '{source_name}' not found.")
        if not hasattr(obj, "Shape"):
            raise RuntimeError(f"'{source_name}' has no geometry.")

        plane_normals = {
            "xy": FC.Vector(0, 0, 1),
            "xz": FC.Vector(0, 1, 0),
            "yz": FC.Vector(1, 0, 0),
        }
        if plane.lower() not in plane_normals:
            raise RuntimeError(f"plane must be 'xy', 'xz', or 'yz'; got '{plane}'.")

        self._require_unique_name_unless_consuming(result_name, consuming=[] if keep_original else [source_name])

        normal = plane_normals[plane.lower()]
        mirrored = obj.Shape.mirror(FC.Vector(0, 0, 0), normal)

        if not mirrored.isValid() or mirrored.Volume < 0:
            raise RuntimeError(f"Mirror across '{plane}' plane produced invalid geometry.")

        if not keep_original:
            doc.removeObject(obj.Name)
            self._state.shapes.pop(source_name, None)

        feature = doc.addObject("Part::Feature", result_name)
        feature.Shape = mirrored
        doc.recompute()

        meta = ShapeMeta(
            name=result_name,
            shape_type="Mirror",
            position={"x": 0, "y": 0, "z": 0},
            dimensions={
                "mirror_plane": plane,
                "source": source_name,
                "volume_mm3": round(mirrored.Volume, 3),
            },
        )
        self._state.shapes[result_name] = meta
        logger.info("mirror_shape: '%s' â†’ '%s' (plane=%s)", source_name, result_name, plane)
        return meta

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_bounding_box(self) -> dict:
        """
        Return the combined axis-aligned bounding box of all shapes in the document.
        Raises RuntimeError if no shapes exist.
        """
        doc = self._require_doc()
        if not self._state.shapes:
            raise RuntimeError("No shapes in document â€” add at least one shape first.")

        import Part as _Part
        shapes = []
        missing = []
        for obj in doc.Objects:
            if hasattr(obj, "Shape") and obj.Shape.isValid():
                shapes.append(obj.Shape)
            elif obj.Name in self._state.shapes:
                missing.append(obj.Name)

        if not shapes:
            raise RuntimeError("No valid shapes found in document after recompute.")

        compound = _Part.makeCompound(shapes)
        bb = compound.BoundBox

        result = {
            "x_min": round(bb.XMin, 6),
            "y_min": round(bb.YMin, 6),
            "z_min": round(bb.ZMin, 6),
            "x_max": round(bb.XMax, 6),
            "y_max": round(bb.YMax, 6),
            "z_max": round(bb.ZMax, 6),
            "x_size": round(bb.XLength, 6),
            "y_size": round(bb.YLength, 6),
            "z_size": round(bb.ZLength, 6),
            "diagonal_mm": round(bb.DiagonalLength, 6),
            "shape_count": len(shapes),
            "shape_names": list(self._state.shapes.keys()),
        }
        if missing:
            result["_warnings"] = [f"Shape(s) had no valid geometry: {missing}"]
        return result

    def get_shape_info(self, name: str) -> dict:
        """Return volume, surface area, and topology counts for a named shape."""
        doc = self._require_doc()
        obj = self._get_obj(doc, name)
        if obj is None:
            raise RuntimeError(f"Shape '{name}' not found in document.")
        if not hasattr(obj, "Shape"):
            raise RuntimeError(f"Object '{name}' has no Shape attribute.")

        shape = obj.Shape
        meta = self._state.shapes.get(name)
        return {
            "name": name,
            "shape_type": meta.shape_type if meta else "Unknown",
            "volume_mm3": round(shape.Volume, 6),
            "surface_area_mm2": round(shape.Area, 6),
            "face_count": len(shape.Faces),
            "edge_count": len(shape.Edges),
            "position": meta.position if meta else {},
            "dimensions": meta.dimensions if meta else {},
        }

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    _VIEW_ANGLES: dict = {
        "iso":    (30,  45),
        "front":  (0,   0),
        "back":   (0,  180),
        "top":    (90,  0),
        "bottom": (-90, 0),
        "right":  (0,  -90),
        "left":   (0,   90),
    }
    _SHAPE_COLORS = [
        "#4A90D9", "#E67E22", "#27AE60",
        "#8E44AD", "#E74C3C", "#16A085", "#F39C12",
    ]

    def screenshot(
        self,
        shape_name: str = "",
        view: str = "iso",
        width: int = 800,
        height: int = 600,
        output_path: str = "",
    ) -> dict:
        """
        Render a PNG screenshot of the named shape (or all shapes) using
        matplotlib's 3D engine. Returns base64 PNG or writes to output_path.
        Requires matplotlib installed in FreeCAD's Python:
            "C:\\Program Files\\FreeCAD 1.1\\bin\\python.exe" -m pip install matplotlib
        """
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        except ImportError as exc:
            raise RuntimeError(
                "matplotlib is required for screenshots. Install it with:\n"
                r'"C:\Program Files\FreeCAD 1.1\bin\python.exe" -m pip install matplotlib'
            ) from exc

        import base64
        import io
        from pathlib import Path

        doc = self._require_doc()

        if view not in self._VIEW_ANGLES:
            raise RuntimeError(
                f"Unknown view '{view}'. Valid: {list(self._VIEW_ANGLES)}"
            )
        elev, azim = self._VIEW_ANGLES[view]

        # Collect shapes
        if shape_name:
            obj = self._get_obj(doc, shape_name)
            if obj is None:
                raise RuntimeError(f"Shape '{shape_name}' not found.")
            targets = [(shape_name, obj.Shape)]
        else:
            targets = [
                (o.Label, o.Shape)
                for o in doc.Objects
                if hasattr(o, "Shape") and o.Shape.Volume > 1e-6
            ]

        if not targets:
            raise RuntimeError("No shapes with volume in document.")

        dpi = 100
        fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
        ax = fig.add_subplot(111, projection="3d")
        ax.set_facecolor("#1a1a2e")
        fig.patch.set_facecolor("#1a1a2e")

        all_bb = []
        for i, (label, shape) in enumerate(targets):
            bb = shape.BoundBox
            all_bb.append(bb)
            precision = max(bb.DiagonalLength * 0.004, 0.2)
            try:
                verts, faces = shape.tessellate(precision)
            except Exception:
                continue
            if not faces:
                continue
            tris = [[list(verts[idx]) for idx in face] for face in faces]
            poly = Poly3DCollection(
                tris, alpha=0.88, linewidth=0,
                facecolor=self._SHAPE_COLORS[i % len(self._SHAPE_COLORS)],
            )
            ax.add_collection3d(poly)

        # Equal aspect ratio from combined bounding box
        xs = [bb.XMin for bb in all_bb] + [bb.XMax for bb in all_bb]
        ys = [bb.YMin for bb in all_bb] + [bb.YMax for bb in all_bb]
        zs = [bb.ZMin for bb in all_bb] + [bb.ZMax for bb in all_bb]
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        cz = (min(zs) + max(zs)) / 2
        r = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) / 2 or 1.0

        ax.set_xlim(cx - r, cx + r)
        ax.set_ylim(cy - r, cy + r)
        ax.set_zlim(cz - r, cz + r)
        ax.view_init(elev=elev, azim=azim)

        title = shape_name if shape_name else f"{len(targets)} shape(s)"
        ax.set_title(title, color="white", pad=8)
        for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
            pane.fill = False
            pane.set_edgecolor("#444")
        ax.tick_params(colors="#888")
        ax.xaxis.label.set_color("#888")
        ax.yaxis.label.set_color("#888")
        ax.zaxis.label.set_color("#888")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi,
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        png_bytes = buf.read()

        result: dict = {
            "view": view,
            "shape_name": shape_name or "all",
            "shape_count": len(targets),
            "width": width,
            "height": height,
        }
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(png_bytes)
            result["output_path"] = str(output_path)
            result["file_size_bytes"] = len(png_bytes)
        else:
            result["image_base64"] = base64.b64encode(png_bytes).decode("ascii")
            result["image_format"] = "png"
            result["image_size_bytes"] = len(png_bytes)

        logger.info("screenshot: view=%s shapes=%d size=%dx%d",
                    view, len(targets), width, height)
        return result

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_step(self, output_path: str, shape_name: str | None = None) -> dict:
        """Export shapes as a STEP file. If shape_name is given, export only that
        shape; otherwise export all valid shapes in the document."""
        import os
        from pathlib import Path

        doc = self._require_doc()
        if not self._state.shapes:
            raise RuntimeError("Cannot export â€” document has no shapes.")

        out = Path(output_path)
        if not out.parent.exists():
            raise RuntimeError(
                f"Output directory does not exist: {out.parent}. "
                "Create it before exporting."
            )

        if shape_name:
            obj = self._get_obj(doc, shape_name)
            if obj is None:
                raise RuntimeError(f"Shape '{shape_name}' not found in document.")
            shapes_to_export = [obj]
        else:
            shapes_to_export = [
                obj for obj in doc.Objects
                if hasattr(obj, "Shape") and obj.Shape.isValid()
            ]
        if not shapes_to_export:
            raise RuntimeError("No valid shapes to export after recompute.")

        import Part as _Part
        _Part.export(shapes_to_export, str(out))

        file_size = out.stat().st_size
        logger.info("Exported %d shape(s) to '%s' (%d bytes)",
                    len(shapes_to_export), out, file_size)
        return {
            "output_path": str(out),
            "shape_count": len(shapes_to_export),
            "shape_names": [o.Name for o in shapes_to_export],
            "file_size_bytes": file_size,
        }

    def export_stl(self, output_path: str) -> dict:
        """Export all shapes as a binary STL file."""
        from pathlib import Path
        import Mesh as _Mesh

        doc = self._require_doc()
        out = Path(output_path)
        if not out.parent.exists():
            raise RuntimeError(f"Output directory does not exist: {out.parent}.")

        shapes_to_export = [
            obj for obj in doc.Objects
            if hasattr(obj, "Shape") and obj.Shape.isValid()
        ]
        if not shapes_to_export:
            raise RuntimeError("No valid shapes to export.")

        meshes = []
        for obj in shapes_to_export:
            mesh = _Mesh.Mesh(obj.Shape.tessellate(0.1))
            meshes.append(mesh)

        combined = _Mesh.Mesh()
        for m in meshes:
            combined.addMesh(m)
        combined.write(str(out))

        file_size = out.stat().st_size
        return {"output_path": str(out), "file_size_bytes": file_size}

    # ------------------------------------------------------------------
    # Solid validation
    # ------------------------------------------------------------------

    def validate_solid(self, name: str) -> dict:
        """
        Run a full BRep inspection on a named shape in the document.
        Returns a structured report with individual check results and issues list.
        """
        import Part as _Part

        doc = self._require_doc()
        obj = self._get_obj(doc, name)
        if obj is None:
            raise RuntimeError(f"Shape '{name}' not found in document.")

        shape = obj.Shape
        issues = []
        warnings = []
        checks = {}

        # 1. Basic validity
        checks["freecad_isValid"] = shape.isValid()
        if not checks["freecad_isValid"]:
            issues.append("FreeCAD isValid() failed â€” topology is corrupt.")

        # 2. Shape type â€” must be Solid or Compound of Solids
        checks["shape_type"] = shape.ShapeType
        solids = shape.Solids
        checks["solid_count"] = len(solids)
        if shape.ShapeType not in ("Solid", "Compound"):
            issues.append(f"Shape type is '{shape.ShapeType}', expected Solid or Compound.")
        elif len(solids) == 0:
            issues.append("Shape contains no Solids (may be a Shell or Wire only).")
        elif len(solids) > 1:
            warnings.append(f"Shape is a Compound of {len(solids)} solids â€” will export as separate bodies.")

        # 3. Volume and surface area sanity
        checks["volume_mm3"] = round(shape.Volume, 3)
        checks["surface_area_mm2"] = round(shape.Area, 3)
        if shape.Volume <= 0:
            issues.append(f"Volume is {shape.Volume:.3f}mmÂ³ â€” not a solid body.")
        if shape.Area <= 0:
            issues.append("Surface area is zero.")

        # 4. Watertight check â€” use Shell.isClosed() which correctly ignores
        #    parametric seam edges on cylinders/spheres (B-Rep artifacts, not real holes)
        open_shells = []
        for i, solid in enumerate(solids):
            for j, shell in enumerate(solid.Shells):
                if not shell.isClosed():
                    open_shells.append(f"solid[{i}].shell[{j}]")
        checks["open_shell_count"] = len(open_shells)
        checks["watertight"] = len(open_shells) == 0
        if open_shells:
            issues.append(
                f"{len(open_shells)} open shell(s) â€” shape is not watertight: {open_shells}. "
                "Incomplete booleans or missing faces cause this."
            )

        # 5. Non-manifold edges â€” shared by more than 2 faces (causes slicer/CAM failures)
        #    Skip seam edges (seam edges appear on periodic surfaces with 1 face, not >2)
        non_manifold_edges = []
        for edge in shape.Edges:
            try:
                ancestor_faces = shape.ancestorsOfType(edge, _Part.Face)
                if len(ancestor_faces) > 2:
                    non_manifold_edges.append(edge)
            except Exception:
                pass
        checks["non_manifold_edge_count"] = len(non_manifold_edges)
        if non_manifold_edges:
            issues.append(
                f"{len(non_manifold_edges)} non-manifold edge(s) found â€” shared by >2 faces. "
                "These cause failures in slicers, CAM, and Protolabs upload."
            )

        # 6. Degenerate faces (area near zero)
        degenerate_faces = [f for f in shape.Faces if f.Area < 1e-6]
        checks["degenerate_face_count"] = len(degenerate_faces)
        if degenerate_faces:
            issues.append(f"{len(degenerate_faces)} degenerate face(s) with area < 1e-6mmÂ².")

        # 7. Degenerate edges (length near zero â€” can cause boolean failures)
        degenerate_edges = [e for e in shape.Edges if e.Length < 1e-6]
        checks["degenerate_edge_count"] = len(degenerate_edges)
        if degenerate_edges:
            warnings.append(f"{len(degenerate_edges)} near-zero-length edge(s) found.")

        # 8. Shell count per solid (should be 1 per solid for simple parts)
        shell_counts = [len(s.Shells) for s in solids]
        checks["shells_per_solid"] = shell_counts
        for i, sc in enumerate(shell_counts):
            if sc == 0:
                issues.append(f"Solid {i} has no shells.")
            elif sc > 1:
                warnings.append(f"Solid {i} has {sc} shells â€” may indicate internal voids.")

        # 9. BRep checker (catches self-intersections, bad curves, bad surfaces)
        brep_ok = True
        brep_error = None
        try:
            shape.check()
        except Exception as exc:
            brep_ok = False
            brep_error = str(exc)
            issues.append(f"BRep check failed: {brep_error}")
        checks["brep_check_passed"] = brep_ok

        # 10. Face/edge counts (informational)
        checks["face_count"] = len(shape.Faces)
        checks["edge_count"] = len(shape.Edges)
        checks["vertex_count"] = len(shape.Vertexes)

        is_clean = len(issues) == 0
        return {
            "shape_name": name,
            "is_clean": is_clean,
            "checks": checks,
            "issues": issues,
            "warnings": warnings,
            "summary": (
                "Shape is a clean solid." if is_clean
                else f"{len(issues)} issue(s) found â€” shape may fail in CAM/slicer/upload."
            ),
        }

    def validate_step_file(self, step_path: str) -> dict:
        """
        Re-import a STEP file and run the same BRep inspection on the imported shape.
        This confirms the file itself is valid, not just the in-memory geometry.
        """
        import Part as _Part
        from pathlib import Path

        path = Path(step_path)
        if not path.exists():
            raise RuntimeError(f"STEP file not found: {step_path}")

        # Read STEP file â€” try Part.read() first (returns Shape directly),
        # fall back to importing into a temporary document
        imported = None
        read_error = None
        try:
            imported = _Part.read(str(path))
        except Exception as exc:
            read_error = exc

        if imported is None:
            # Fallback: import into a temp FreeCAD document and extract shape
            import FreeCAD as _FC
            tmp_name = "_validate_tmp"
            try:
                tmp_doc = _FC.newDocument(tmp_name)
                import Import as _Import
                _Import.insert(str(path), tmp_name)
                tmp_doc.recompute()
                shapes_in_tmp = [o.Shape for o in tmp_doc.Objects if hasattr(o, "Shape") and o.Shape.Volume > 0]
                if len(shapes_in_tmp) == 1:
                    imported = shapes_in_tmp[0]
                elif len(shapes_in_tmp) > 1:
                    # M6 fix: compound all bodies so multi-body STEP files are fully validated
                    imported = _Part.makeCompound(shapes_in_tmp)
            except Exception as exc2:
                read_error = exc2
            finally:
                try:
                    _FC.closeDocument(tmp_name)
                except Exception:
                    pass

        if imported is None:
            return {
                "step_path": step_path,
                "is_clean": False,
                "checks": {"file_readable": False},
                "issues": [f"Failed to read STEP file: {read_error}"],
                "warnings": [],
                "summary": "STEP file could not be parsed.",
            }

        issues = []
        warnings = []
        checks = {"file_readable": True, "file_size_bytes": path.stat().st_size}

        checks["freecad_isValid"] = imported.isValid()
        if not imported.isValid():
            issues.append("Imported STEP shape failed isValid().")

        solids = imported.Solids
        checks["solid_count"] = len(solids)
        checks["shape_type"] = imported.ShapeType
        if len(solids) == 0:
            issues.append("STEP file contains no solid bodies.")
        elif len(solids) > 1:
            warnings.append(f"STEP file contains {len(solids)} separate solids.")

        checks["volume_mm3"] = round(imported.Volume, 3)
        if imported.Volume <= 0:
            issues.append("Imported shape has zero or negative volume.")

        # Watertight check using Shell.isClosed() (avoids B-Rep seam false positives)
        open_shells = []
        for i, solid in enumerate(solids):
            for j, shell in enumerate(solid.Shells):
                if not shell.isClosed():
                    open_shells.append(f"solid[{i}].shell[{j}]")
        checks["open_shell_count"] = len(open_shells)
        checks["watertight"] = len(open_shells) == 0
        if open_shells:
            issues.append(f"Imported STEP has {len(open_shells)} open shell(s) â€” not watertight.")

        non_manifold = []
        for edge in imported.Edges:
            try:
                if len(imported.ancestorsOfType(edge, _Part.Face)) > 2:
                    non_manifold.append(edge)
            except Exception:
                pass
        checks["non_manifold_edge_count"] = len(non_manifold)
        if non_manifold:
            issues.append(f"Imported STEP has {len(non_manifold)} non-manifold edge(s).")

        brep_ok = True
        try:
            imported.check()
        except Exception as exc:
            brep_ok = False
            issues.append(f"BRep check on imported STEP failed: {exc}")
        checks["brep_check_passed"] = brep_ok

        checks["face_count"] = len(imported.Faces)
        checks["edge_count"] = len(imported.Edges)

        is_clean = len(issues) == 0
        return {
            "step_path": step_path,
            "is_clean": is_clean,
            "checks": checks,
            "issues": issues,
            "warnings": warnings,
            "summary": (
                "STEP file imports as a clean solid." if is_clean
                else f"{len(issues)} issue(s) found in STEP file."
            ),
        }

    # ------------------------------------------------------------------
    # Assembly export
    # ------------------------------------------------------------------

    def export_assembly(
        self,
        parts: list[dict],
        output_path: str,
    ) -> dict:
        """
        Combine multiple STEP files into a single multi-body STEP file.

        parts: list of dicts with keys:
            step_path (str)   â€” absolute path to an existing .step file
            name      (str)   â€” label for this body in the assembly
            x, y, z   (float) â€” optional translation offset in mm (default 0)

        output_path: absolute path for the resulting assembly STEP file.

        Each part is imported into a temporary FreeCAD document, translated,
        and exported together as one STEP file containing multiple named solid bodies.
        CAD viewers (FreeCAD, Fusion 360, STEP viewers) display each body
        as an individually selectable component.
        """
        import Part as _Part
        import FreeCAD as _FC
        from pathlib import Path

        out = Path(output_path)
        if not out.suffix.lower() in (".step", ".stp"):
            raise RuntimeError("output_path must end with .step or .stp")
        out.parent.mkdir(parents=True, exist_ok=True)

        tmp_name = "_assembly_export_tmp"
        # Close any leftover doc from a previous failed run
        try:
            _FC.closeDocument(tmp_name)
        except Exception:
            pass

        tmp_doc = _FC.newDocument(tmp_name)
        loaded = []

        try:
            import Import as _Import

            for entry in parts:
                src = Path(entry["step_path"])
                if not src.exists():
                    raise RuntimeError(f"Part STEP file not found: {src}")

                label = entry.get("name", src.stem)
                dx = float(entry.get("x", 0.0))
                dy = float(entry.get("y", 0.0))
                dz = float(entry.get("z", 0.0))
                rx = float(entry.get("rx", 0.0))
                ry = float(entry.get("ry", 0.0))
                rz = float(entry.get("rz", 0.0))

                # Import into a throw-away sub-document so we can grab the raw Shape
                sub_name = f"_asm_import_{label}"
                try:
                    _FC.closeDocument(sub_name)
                except Exception:
                    pass

                sub_doc = _FC.newDocument(sub_name)
                try:
                    _Import.insert(str(src), sub_name)
                    sub_doc.recompute()
                    shapes = [o.Shape for o in sub_doc.Objects
                              if hasattr(o, "Shape") and o.Shape.Volume > 1e-6]
                    if not shapes:
                        raise RuntimeError(f"No solid found in {src.name}")

                    # FreeCAD may decompose a multi-solid STEP into both constituent
                    # solid objects AND a parent compound, which would double-count if
                    # we naively makeCompound(all).  Strategy: pick the shape with the
                    # most .Solids (= top-level compound when one exists), breaking ties
                    # by volume.  Fall back to makeCompound of solids-only if needed.
                    shapes.sort(key=lambda s: (len(s.Solids), s.Volume), reverse=True)
                    n_solid_objects = sum(1 for s in shapes if s.ShapeType == "Solid")
                    best = shapes[0]
                    if len(best.Solids) >= n_solid_objects:
                        # The top candidate already accounts for all solid geometry
                        shape = best.copy()
                    else:
                        # No single compound covers everything — merge solid objects only
                        solid_shapes = [s for s in shapes if s.ShapeType == "Solid"]
                        shape = _Part.makeCompound(solid_shapes) if len(solid_shapes) > 1 else solid_shapes[0].copy()

                    # Apply rotation then translation
                    import math as _math
                    if abs(rx) + abs(ry) + abs(rz) > 1e-6:
                        rot = _FC.Rotation(
                            _FC.Vector(1, 0, 0), rx
                        ).multiply(
                            _FC.Rotation(_FC.Vector(0, 1, 0), ry)
                        ).multiply(
                            _FC.Rotation(_FC.Vector(0, 0, 1), rz)
                        )
                        mat = rot.toMatrix()
                        shape = shape.transformGeometry(mat)
                    if abs(dx) + abs(dy) + abs(dz) > 1e-6:
                        mat = _FC.Matrix()
                        mat.move(_FC.Vector(dx, dy, dz))
                        shape = shape.transformGeometry(mat)

                    # Add to assembly document as a named feature
                    feat = tmp_doc.addObject("Part::Feature", label)
                    feat.Shape = shape
                    feat.Label = label
                    loaded.append({"name": label, "volume_mm3": round(shape.Volume, 3)})
                finally:
                    try:
                        _FC.closeDocument(sub_name)
                    except Exception:
                        pass

            tmp_doc.recompute()

            if not loaded:
                raise RuntimeError("No parts were successfully loaded into the assembly.")

            # Export all objects in the document as one STEP file
            objs = [o for o in tmp_doc.Objects if hasattr(o, "Shape")]
            _Part.export(objs, str(out))

        finally:
            try:
                _FC.closeDocument(tmp_name)
            except Exception:
                pass

        file_size = out.stat().st_size if out.exists() else 0
        logger.info(
            "Assembly exported: %s (%d parts, %d bytes)", out.name, len(loaded), file_size
        )
        return {
            "output_path": str(out),
            "part_count": len(loaded),
            "parts": loaded,
            "file_size_bytes": file_size,
        }

    # ------------------------------------------------------------------
    # Boolean operations
    # ------------------------------------------------------------------

    def linear_pattern(
        self,
        source_name: str,
        direction: str,
        count: int,
        spacing: float,
        result_name: str,
    ) -> ShapeMeta:
        """
        Create `count` copies of source_name spaced along `direction`, fused into one solid.
        Used for bolt hole arrays, rib patterns, etc. Source shape is consumed.
        """
        doc = self._require_doc()
        obj = self._get_obj(doc, source_name)
        if obj is None:
            raise RuntimeError(f"Shape '{source_name}' not found.")
        if not hasattr(obj, "Shape"):
            raise RuntimeError(f"'{source_name}' has no geometry.")

        self._require_unique_name_unless_consuming(result_name, consuming=[source_name])

        from freecad_bridge import get_freecad
        FC = get_freecad()
        import Part as _Part

        dir_map = {"x": FC.Vector(1, 0, 0), "y": FC.Vector(0, 1, 0), "z": FC.Vector(0, 0, 1)}
        if direction not in dir_map:
            raise RuntimeError(f"direction must be 'x', 'y', or 'z'; got '{direction}'.")
        dir_vec = dir_map[direction]

        base_shape = obj.Shape
        shapes = []
        for i in range(count):
            offset = FC.Vector(dir_vec.x * spacing * i,
                               dir_vec.y * spacing * i,
                               dir_vec.z * spacing * i)
            mat = FC.Matrix()
            mat.move(offset)
            shapes.append(base_shape.transformGeometry(mat))

        result_shape = shapes[0]
        for s in shapes[1:]:
            result_shape = result_shape.fuse(s)
        result_shape = result_shape.removeSplitter()

        if not result_shape.isValid():
            raise RuntimeError("Linear pattern produced invalid geometry.")

        meta = self._state.shapes.get(source_name)
        doc.removeObject(obj.Name)
        self._state.shapes.pop(source_name, None)

        feature = doc.addObject("Part::Feature", result_name)
        feature.Shape = result_shape
        doc.recompute()

        new_meta = ShapeMeta(
            name=result_name,
            shape_type="Pattern",
            position=meta.position if meta else {"x": 0.0, "y": 0.0, "z": 0.0},
            dimensions={"count": count, "spacing": spacing, "direction": direction},
        )
        self._state.shapes[result_name] = new_meta
        logger.info("linear_pattern: '%s' Ã— %d @ %.2fmm along %s â†’ '%s'",
                    source_name, count, spacing, direction, result_name)
        return new_meta

    def boolean_union(self, shape_a: str, shape_b: str, result_name: str) -> ShapeMeta:
        """
        Fuse shape_a and shape_b into one solid. Both originals are consumed.
        The shapes should touch or overlap; a gap produces a non-manifold result.
        """
        doc = self._require_doc()
        obj_a = self._get_obj(doc, shape_a)
        if obj_a is None:
            raise RuntimeError(f"Shape '{shape_a}' not found in document.")
        obj_b = self._get_obj(doc, shape_b)
        if obj_b is None:
            raise RuntimeError(f"Shape '{shape_b}' not found in document.")
        if not hasattr(obj_a, "Shape") or not hasattr(obj_b, "Shape"):
            raise RuntimeError("Both shapes must have geometry.")

        self._require_unique_name_unless_consuming(result_name, consuming=[shape_a, shape_b])

        result_shape = obj_a.Shape.fuse(obj_b.Shape)
        if not result_shape.isValid():
            raise RuntimeError(
                "Boolean union produced invalid geometry. "
                "Ensure the shapes touch or overlap â€” a gap between them creates a non-manifold solid."
            )
        result_shape = result_shape.removeSplitter()  # clean up internal faces at the junction

        # C2 fix: geometry is computed above; now safely remove inputs before adding result.
        # When result_name is one of the inputs (self-update), we must remove first to free
        # the name; addObject before removeObject would cause FreeCAD to auto-increment the name.
        meta_a = self._state.shapes.get(shape_a)
        doc.removeObject(obj_b.Name)
        doc.removeObject(obj_a.Name)
        self._state.shapes.pop(shape_a, None)
        self._state.shapes.pop(shape_b, None)

        feature = self._add_feature(doc, result_name, result_shape)
        doc.recompute()

        meta = ShapeMeta(
            name=result_name,
            shape_type="Union",
            position=meta_a.position if meta_a else {"x": 0.0, "y": 0.0, "z": 0.0},
            dimensions={},
        )
        self._state.shapes[result_name] = meta
        logger.info("boolean_union: '%s' + '%s' â†’ '%s'", shape_a, shape_b, result_name)
        return meta

    def boolean_cut(self, target_name: str, tool_name: str, result_name: str) -> ShapeMeta:
        """
        Subtract tool_name from target_name. Both originals are consumed;
        result_name is the new shape containing the difference geometry.
        """
        doc = self._require_doc()
        target_obj = self._get_obj(doc, target_name)
        if target_obj is None:
            raise RuntimeError(f"Target shape '{target_name}' not found in document.")
        tool_obj = self._get_obj(doc, tool_name)
        if tool_obj is None:
            raise RuntimeError(f"Tool shape '{tool_name}' not found in document.")
        if not hasattr(target_obj, "Shape") or not hasattr(tool_obj, "Shape"):
            raise RuntimeError("Both target and tool shapes must have geometry.")
        if target_name == result_name == tool_name:
            raise RuntimeError("target_shape, tool_shape, and result_name cannot all be identical.")

        self._require_unique_name_unless_consuming(result_name, consuming=[target_name, tool_name])

        volume_before = target_obj.Shape.Volume
        result_shape = target_obj.Shape.cut(tool_obj.Shape)
        if not result_shape.isValid():
            raise RuntimeError(
                "Boolean cut produced invalid geometry. "
                "Ensure the tool shape overlaps or intersects the target."
            )
        try:
            result_shape = result_shape.removeSplitter()
        except Exception:
            pass

        # C2 fix: geometry already computed above. Remove inputs before adding result
        # to avoid FreeCAD name-increment when result_name == target_name.
        target_meta = self._state.shapes.get(target_name)
        doc.removeObject(tool_obj.Name)
        doc.removeObject(target_obj.Name)
        self._state.shapes.pop(tool_name, None)
        self._state.shapes.pop(target_name, None)

        feature = self._add_feature(doc, result_name, result_shape)
        doc.recompute()

        volume_after = result_shape.Volume
        meta = ShapeMeta(
            name=result_name,
            shape_type="Cut",
            position=target_meta.position if target_meta else {"x": 0.0, "y": 0.0, "z": 0.0},
            dimensions={
                "volume_before_mm3": round(volume_before, 3),
                "volume_after_mm3": round(volume_after, 3),
                "volume_removed_mm3": round(volume_before - volume_after, 3),
            },
        )
        self._state.shapes[result_name] = meta
        logger.info("boolean_cut: ‘%s’ - ‘%s’ â†’ ‘%s’ (removed %.1f mm³)",
                    target_name, tool_name, result_name, volume_before - volume_after)
        return meta

    def make_hole(
        self,
        target_name: str,
        diameter: float,
        x: float,
        y: float,
        z: float,
        result_name: str,
        depth: Optional[float] = None,
        axis: str = "z",
    ) -> ShapeMeta:
        """
        Drill a cylindrical hole into target_name at (x, y, z).
        depth=None means through the full Z extent of the target.
        The original target is replaced by result_name.
        """
        doc = self._require_doc()
        target_obj = self._get_obj(doc, target_name)
        if target_obj is None:
            raise RuntimeError(f"Target shape '{target_name}' not found in document.")
        if not hasattr(target_obj, "Shape"):
            raise RuntimeError(f"'{target_name}' has no geometry.")

        self._require_unique_name_unless_consuming(result_name, consuming=[target_name])

        from freecad_bridge import get_freecad
        FC = get_freecad()
        import Part as _Part

        _AXIS_MAP = {
            "x": FC.Vector(1, 0, 0),
            "y": FC.Vector(0, 1, 0),
            "z": FC.Vector(0, 0, 1),
        }
        if axis not in _AXIS_MAP:
            raise RuntimeError(f"axis must be 'x', 'y', or 'z'; got '{axis}'.")
        axis_vec = _AXIS_MAP[axis]

        target_shape = target_obj.Shape
        bb = target_shape.BoundBox

        # M3 fix: through-hole starts at the bounding box face (not user position)
        # so it always punches fully through regardless of where (x,y,z) sits.
        if depth is not None:
            depth_val = depth
            start = FC.Vector(x, y, z)
        elif axis == "x":
            depth_val = bb.XLength + 2.0
            start = FC.Vector(bb.XMin - 1.0, y, z)
        elif axis == "y":
            depth_val = bb.YLength + 2.0
            start = FC.Vector(x, bb.YMin - 1.0, z)
        else:
            depth_val = bb.ZLength + 2.0
            start = FC.Vector(x, y, bb.ZMin - 1.0)

        cyl_shape = _Part.makeCylinder(
            diameter / 2.0,
            depth_val,
            start,
            axis_vec,
        )

        result_shape = target_shape.cut(cyl_shape)
        if not result_shape.isValid():
            raise RuntimeError(
                f"Hole at ({x},{y},{z}) dia={diameter} produced invalid geometry. "
                "Verify the hole center is within the target shape's XY bounds."
            )

        target_meta = self._state.shapes.get(target_name)
        doc.removeObject(target_obj.Name)
        self._state.shapes.pop(target_name, None)

        feature = self._add_feature(doc, result_name, result_shape)
        doc.recompute()

        meta = ShapeMeta(
            name=result_name,
            shape_type="WithHoles" if target_meta and target_meta.shape_type in ("Box", "WithHoles", "Cut") else "Cut",
            position=target_meta.position if target_meta else {"x": 0.0, "y": 0.0, "z": 0.0},
            dimensions={"hole_diameter": diameter, "hole_depth": depth_val},
        )
        self._state.shapes[result_name] = meta
        logger.info("make_hole: drilled dia=%.2f axis=%s at (%.2f,%.2f,%.2f) into '%s' â†’ '%s'",
                    diameter, axis, x, y, z, target_name, result_name)
        return meta

    def fillet_edges(
        self,
        target_name: str,
        radius: float,
        edge_selector: str,
        result_name: str,
    ) -> ShapeMeta:
        """
        Apply a radius fillet to selected edges of target_name.
        edge_selector: 'all_vertical' | 'all' | 'top' | 'bottom'
        The original shape is replaced by result_name.
        """
        doc = self._require_doc()
        target_obj = self._get_obj(doc, target_name)
        if target_obj is None:
            raise RuntimeError(f"Target shape '{target_name}' not found in document.")

        self._require_unique_name_unless_consuming(result_name, consuming=[target_name])

        from freecad_bridge import get_freecad
        FC = get_freecad()

        shape = target_obj.Shape
        bb = shape.BoundBox

        if edge_selector == "all":
            edges = shape.Edges

        elif edge_selector in ("all_vertical", "vertical"):
            z_vec = FC.Vector(0, 0, 1)
            edges = []
            for e in shape.Edges:
                try:
                    t = e.tangentAt(e.FirstParameter)
                    if abs(abs(t.dot(z_vec)) - 1.0) < 0.01:
                        edges.append(e)
                except Exception:
                    pass

        elif edge_selector == "top":
            # Include any edge whose midpoint Z is within 1% of total height from the top
            tol = max(0.1, bb.ZLength * 0.02)
            edges = [
                e for e in shape.Edges
                if (e.BoundBox.ZMin >= bb.ZMax - tol
                    and e.BoundBox.ZMax <= bb.ZMax + tol)
            ]

        elif edge_selector == "bottom":
            tol = max(0.1, bb.ZLength * 0.02)
            edges = [
                e for e in shape.Edges
                if (e.BoundBox.ZMax <= bb.ZMin + tol
                    and e.BoundBox.ZMin >= bb.ZMin - tol)
            ]

        else:
            raise RuntimeError(
                f"Unknown edge_selector '{edge_selector}'. "
                "Valid options: all, all_vertical, top, bottom"
            )

        if not edges:
            _valid = ["all", "all_vertical", "top", "bottom"]
            raise RuntimeError(
                f"No edges matched selector '{edge_selector}' on '{target_name}' "
                f"({len(shape.Edges)} total edges). "
                f"Valid selectors: {_valid}. "
                "If the shape was recently filleted, try 'all' or call /model/get_shape_info "
                "to check edge count before selecting."
            )

        def _try_fillet(s, r, edge_list):
            try:
                result = s.makeFillet(r, edge_list)
                return result if result.isValid() else None
            except Exception:
                return None

        # C3 fix: track which radius tier actually succeeded
        actual_radius = radius
        fallback_warning = None

        # Attempt 1: all edges together at requested radius
        filleted_shape = _try_fillet(shape, radius, edges)

        # Attempt 2: reduce radius by half and retry all edges
        if filleted_shape is None and radius > 0.1:
            filleted_shape = _try_fillet(shape, radius * 0.5, edges)
            if filleted_shape is not None:
                actual_radius = radius * 0.5
                fallback_warning = f"Fillet radius reduced to {actual_radius:.2f}mm (half of requested {radius:.2f}mm) â€” full radius failed on this geometry."

        # Attempt 3: fillet each edge independently, accumulate valid ones
        if filleted_shape is None:
            working = shape
            applied = 0
            for e in edges:
                candidate = _try_fillet(working, radius, [e])
                if candidate is None:
                    candidate = _try_fillet(working, radius * 0.5, [e])
                if candidate is not None:
                    working = candidate
                    applied += 1
            filleted_shape = working if applied > 0 else None
            if filleted_shape is not None:
                actual_radius = radius  # mixed â€” report requested
                fallback_warning = f"Fillet applied per-edge ({applied}/{len(edges)} edges succeeded); some edges may be at reduced radius."

        if filleted_shape is None:
            raise RuntimeError(
                f"Fillet (r={radius}mm, selector='{edge_selector}') failed on all edges. "
                "The geometry may be too complex; try 'all_vertical' or a smaller radius."
            )

        target_meta = self._state.shapes.get(target_name)
        doc.removeObject(target_obj.Name)
        self._state.shapes.pop(target_name, None)

        feature = self._add_feature(doc, result_name, filleted_shape)
        doc.recompute()

        meta = ShapeMeta(
            name=result_name,
            shape_type="Fillet",
            position=target_meta.position if target_meta else {"x": 0.0, "y": 0.0, "z": 0.0},
            dimensions={
                "fillet_radius_requested": radius,
                "fillet_radius_applied": actual_radius,
                "edges_selected": len(edges),
                "fallback_warning": fallback_warning,
            },
        )
        self._state.shapes[result_name] = meta
        logger.info("fillet_edges: '%s' r=%.2f (applied=%.2f) selector='%s' edges=%d â†’ '%s'",
                    target_name, radius, actual_radius, edge_selector, len(edges), result_name)
        return meta

    def chamfer_edges(
        self,
        target_name: str,
        size: float,
        edge_selector: str,
        result_name: str,
    ) -> ShapeMeta:
        """Apply a flat chamfer to selected edges. Same edge selectors as fillet_edges."""
        doc = self._require_doc()
        target_obj = self._get_obj(doc, target_name)
        if target_obj is None:
            raise RuntimeError(f"Target shape '{target_name}' not found.")

        self._require_unique_name_unless_consuming(result_name, consuming=[target_name])

        from freecad_bridge import get_freecad
        FC = get_freecad()
        shape = target_obj.Shape
        bb = shape.BoundBox

        if edge_selector == "all":
            edges = shape.Edges
        elif edge_selector in ("all_vertical", "vertical"):
            z_vec = FC.Vector(0, 0, 1)
            edges = []
            for e in shape.Edges:
                try:
                    t = e.tangentAt(e.FirstParameter)
                    if abs(abs(t.dot(z_vec)) - 1.0) < 0.01:
                        edges.append(e)
                except Exception:
                    pass
        elif edge_selector == "top":
            tol = max(0.1, bb.ZLength * 0.02)
            edges = [e for e in shape.Edges
                     if e.BoundBox.ZMin >= bb.ZMax - tol and e.BoundBox.ZMax <= bb.ZMax + tol]
        elif edge_selector == "bottom":
            tol = max(0.1, bb.ZLength * 0.02)
            edges = [e for e in shape.Edges
                     if e.BoundBox.ZMax <= bb.ZMin + tol and e.BoundBox.ZMin >= bb.ZMin - tol]
        else:
            raise RuntimeError(f"Unknown edge_selector '{edge_selector}'.")

        if not edges:
            _valid = ["all", "all_vertical", "top", "bottom"]
            raise RuntimeError(
                f"No edges matched selector '{edge_selector}' on '{target_name}' "
                f"({len(shape.Edges)} total edges). "
                f"Valid selectors: {_valid}. "
                "If the shape was recently filleted or chamfered, try 'all' or call "
                "/model/get_shape_info to inspect edge count first."
            )

        def _try_chamfer(s, sz, edge_list):
            try:
                r = s.makeChamfer(sz, edge_list)
                return r if r.isValid() else None
            except Exception:
                return None

        # C3 fix: track actual applied size
        actual_size = size
        fallback_warning = None

        # 3-tier fallback: all edges full size â†’ all edges half size â†’ per-edge
        chamfered_shape = _try_chamfer(shape, size, edges)
        if chamfered_shape is None and size > 0.1:
            chamfered_shape = _try_chamfer(shape, size * 0.5, edges)
            if chamfered_shape is not None:
                actual_size = size * 0.5
                fallback_warning = f"Chamfer size reduced to {actual_size:.2f}mm (half of requested {size:.2f}mm)."
        if chamfered_shape is None:
            working = shape
            applied = 0
            for e in edges:
                c = _try_chamfer(working, size, [e])
                if c is None:
                    c = _try_chamfer(working, size * 0.5, [e])
                if c is not None:
                    working = c
                    applied += 1
            chamfered_shape = working if applied > 0 else None
            if chamfered_shape is not None:
                fallback_warning = f"Chamfer applied per-edge ({applied}/{len(edges)} edges succeeded)."

        if chamfered_shape is None:
            raise RuntimeError(
                f"Chamfer (size={size}, selector='{edge_selector}') failed on all "
                f"{len(edges)} edge(s). Try a smaller size or different selector."
            )

        target_meta = self._state.shapes.get(target_name)
        doc.removeObject(target_obj.Name)
        self._state.shapes.pop(target_name, None)

        feature = self._add_feature(doc, result_name, chamfered_shape)
        doc.recompute()

        meta = ShapeMeta(
            name=result_name,
            shape_type="Chamfer",
            position=target_meta.position if target_meta else {"x": 0.0, "y": 0.0, "z": 0.0},
            dimensions={
                "chamfer_size_requested": size,
                "chamfer_size_applied": actual_size,
                "edges_selected": len(edges),
                "fallback_warning": fallback_warning,
            },
        )
        self._state.shapes[result_name] = meta
        logger.info("chamfer_edges: '%s' size=%.2f (applied=%.2f) selector='%s' edges=%d â†’ '%s'",
                    target_name, size, actual_size, edge_selector, len(edges), result_name)
        return meta

    # ------------------------------------------------------------------
    # Revolution (solid of rotation)
    # ------------------------------------------------------------------

    def revolve_profile(
        self,
        name: str,
        profile: list,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
    ) -> ShapeMeta:
        """
        Create a solid of revolution by revolving a 2D profile 360Â° around the Z axis.

        profile: list of [radius, z_pos] pairs tracing the outer cross-section.
                 radius >= 0.  No need to include the axis closing line â€” it is
                 added automatically unless the profile already closes at r=0.
        (x, y, z): offset applied to every profile point before revolving.
                   The revolution axis is the Z-axis through (x, y, 0) + offset.
        """
        import Part as _Part
        from freecad_bridge import get_freecad
        FC = get_freecad()

        doc = self._require_doc()
        self._require_unique_name_unless_consuming(name, consuming=[])

        if len(profile) < 2:
            raise RuntimeError("revolve_profile needs at least 2 profile points.")

        # Map [r, zp] â†’ 3D vector in XZ plane offset by (x, y, z)
        outer = [FC.Vector(float(r) + x, y, float(zp) + z) for r, zp in profile]

        # Auto-close along the axis (r=0 + offset) if not already there
        z_start = float(profile[0][1]) + z
        z_end   = float(profile[-1][1]) + z
        closed  = list(outer)
        if outer[-1].x > 1e-6:                    # last point not on axis
            closed.append(FC.Vector(x, y, z_end))
        if outer[0].x > 1e-6:                     # first point not on axis
            closed.append(FC.Vector(x, y, z_start))
        closed.append(closed[0])                   # close the polygon

        wire = _Part.makePolygon(closed)
        if not wire.isClosed():
            raise RuntimeError("Profile polygon failed to close â€” check for duplicate or collinear points.")

        face = _Part.Face(wire)
        if not face.isValid():
            raise RuntimeError("Could not build a face from the profile â€” profile may self-intersect or have zero-area regions.")

        # Revolve 360Â° around the Z axis passing through (x, y, 0)
        solid = face.revolve(FC.Vector(x, y, 0), FC.Vector(0, 0, 1), 360)

        # revolve() may return a Shell for 360Â° closed shapes; extract Solid
        if solid.ShapeType != "Solid":
            solids = solid.Solids
            if solids:
                solid = solids[0]
            elif solid.Shells:
                try:
                    solid = _Part.Solid(solid.Shells[0])
                except Exception:
                    pass

        if not solid.isValid() or solid.Volume < 1.0:
            raise RuntimeError(
                f"Revolution produced invalid or empty geometry "
                f"(type={solid.ShapeType}, vol={getattr(solid, 'Volume', 0):.1f}mmÂ³). "
                "Check that all radius values are â‰¥ 0 and the profile is non-self-intersecting."
            )

        feature = doc.addObject("Part::Feature", name)
        feature.Shape = solid
        doc.recompute()

        meta = ShapeMeta(
            name=name,
            shape_type="Revolution",
            position={"x": x, "y": y, "z": z},
            dimensions={
                "profile_points": len(profile),
                "volume_mm3": round(solid.Volume, 3),
                "z_min": min(p[1] for p in profile) + z,
                "z_max": max(p[1] for p in profile) + z,
                "r_max": max(p[0] for p in profile),
            },
        )
        self._state.shapes[name] = meta
        logger.info("Revolve '%s': %d pts, vol=%.1fmmÂ³", name, len(profile), solid.Volume)
        return meta

    # ------------------------------------------------------------------
    # Polar (circular) pattern
    # ------------------------------------------------------------------

    def polar_pattern(
        self,
        source_name: str,
        count: int,
        axis: str,
        result_name: str,
    ) -> ShapeMeta:
        """
        Create a circular (polar) pattern: rotate the source shape <count> times
        at equal angular steps (360/count degrees each) around the specified axis
        through the origin, then union all instances into one solid.

        The source shape is consumed (removed from the document).
        Use result_name == source_name to update in place.

        Typical workflow for circular hole arrays:
          1. Create one cutting cylinder at the correct radial offset
          2. polar_pattern it (count=N, axis="z") â†’ union of all N cylinders
          3. boolean_cut that union from the target body
        """
        import Part as _Part
        import math
        from freecad_bridge import get_freecad
        FC = get_freecad()

        doc = self._require_doc()
        obj = self._get_obj(doc, source_name)
        if obj is None:
            raise RuntimeError(f"Shape '{source_name}' not found.")

        if count < 2:
            raise RuntimeError("polar_pattern count must be â‰¥ 2.")

        if axis not in ("x", "y", "z"):
            raise RuntimeError(f"axis must be 'x', 'y', or 'z', got '{axis}'.")

        axis_vec = {"x": FC.Vector(1, 0, 0),
                    "y": FC.Vector(0, 1, 0),
                    "z": FC.Vector(0, 0, 1)}[axis]

        angle_step = 360.0 / count
        source_shape = obj.Shape

        result = source_shape.copy()
        for i in range(1, count):
            angle = angle_step * i
            copy = source_shape.copy()
            copy.rotate(FC.Vector(0, 0, 0), axis_vec, angle)
            try:
                result = result.fuse(copy)
            except Exception as exc:
                raise RuntimeError(
                    f"polar_pattern fuse failed at step {i} (angle={angle:.1f}Â°): {exc}"
                )

        try:
            result = result.removeSplitter()
        except Exception:
            pass

        if not result.isValid() or result.Volume < 1.0:
            raise RuntimeError(
                f"polar_pattern produced invalid geometry after {count} instances."
            )

        # Remove source, store result
        self._require_unique_name_unless_consuming(result_name, consuming=[source_name])
        doc.removeObject(obj.Name)
        self._state.shapes.pop(source_name, None)

        feature = doc.addObject("Part::Feature", result_name)
        feature.Shape = result
        doc.recompute()

        meta = ShapeMeta(
            name=result_name,
            shape_type="PolarPattern",
            position={"x": 0, "y": 0, "z": 0},
            dimensions={
                "instance_count": count,
                "axis": axis,
                "angle_step_deg": round(angle_step, 4),
                "volume_mm3": round(result.Volume, 3),
            },
        )
        self._state.shapes[result_name] = meta
        logger.info("polar_pattern '%s': %d instances, vol=%.1fmmÂ³",
                    result_name, count, result.Volume)
        return meta

    # ------------------------------------------------------------------
    # Polygon extrusion
    # ------------------------------------------------------------------

    def extrude_polygon(
        self,
        name: str,
        points: list,
        height: float,
        axis: str = "z",
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
    ) -> ShapeMeta:
        """
        Extrude a 2D polygon defined by [x, y] point pairs into a solid prism.

        Points are defined in the plane perpendicular to `axis`:
          axis="z" â†’ points are [x, y], extrusion goes in +Z
          axis="x" â†’ points are [y, z], extrusion goes in +X
          axis="y" â†’ points are [x, z], extrusion goes in +Y

        The polygon is automatically closed (first == last not required).
        Position (x, y, z) offsets the entire prism origin.
        """
        import Part as _Part
        from freecad_bridge import get_freecad
        FC = get_freecad()

        doc = self._require_doc()
        self._require_unique_name_unless_consuming(name, consuming=[])

        if len(points) < 3:
            raise RuntimeError("extrude_polygon requires at least 3 points.")

        # Build 3D vectors from 2D points according to axis
        def to_vec(pt):
            a, b = float(pt[0]), float(pt[1])
            if axis == "z":
                return FC.Vector(a + x, b + y, z)
            elif axis == "x":
                return FC.Vector(x, a + y, b + z)
            elif axis == "y":
                return FC.Vector(a + x, y, b + z)
            else:
                raise RuntimeError(f"Unknown axis '{axis}'.")

        vecs = [to_vec(p) for p in points]
        # Ensure closed
        if (vecs[-1] - vecs[0]).Length > 1e-6:
            vecs.append(vecs[0])

        wire = _Part.makePolygon(vecs)
        if not wire.isClosed():
            raise RuntimeError("Polygon wire is not closed â€” check that points form a valid closed boundary.")

        face = _Part.Face(wire)
        if not face.isValid():
            raise RuntimeError("Could not build a face from the polygon â€” points may be self-intersecting.")

        # Extrusion direction vector
        if axis == "z":
            direction = FC.Vector(0, 0, height)
        elif axis == "x":
            direction = FC.Vector(height, 0, 0)
        elif axis == "y":
            direction = FC.Vector(0, height, 0)

        solid = face.extrude(direction)
        if not solid.isValid() or solid.Volume < 1.0:
            raise RuntimeError(
                f"Extrusion produced invalid geometry (vol={solid.Volume:.1f}mmÂ³). "
                "Check that the polygon is planar and non-self-intersecting."
            )

        feature = doc.addObject("Part::Feature", name)
        feature.Shape = solid
        doc.recompute()

        meta = ShapeMeta(
            name=name,
            shape_type="Polygon",
            position={"x": x, "y": y, "z": z},
            dimensions={"point_count": len(points), "height": height, "axis": axis,
                        "volume_mm3": round(solid.Volume, 3)},
        )
        self._state.shapes[name] = meta
        logger.info("Extruded polygon '%s': %d pts, h=%.1fmm, vol=%.1fmmÂ³",
                    name, len(points), height, solid.Volume)
        return meta

    # ------------------------------------------------------------------
    # Wire / sweep API
    # ------------------------------------------------------------------

    def create_arc_path(
        self,
        name: str,
        start: list,
        mid: list,
        end: list,
    ) -> WireMeta:
        """Build a 3-point arc wire and store it for use as a sweep spine."""
        self._require_doc()
        if self._state and name in self._state.wires:
            raise RuntimeError(f"A wire named '{name}' already exists.")

        from freecad_bridge import get_freecad
        FC = get_freecad()
        import Part as _Part

        arc = _Part.Arc(
            FC.Vector(*start),
            FC.Vector(*mid),
            FC.Vector(*end),
        )
        wire = _Part.Wire([arc.toShape()])
        if not wire.isValid():
            raise RuntimeError("Arc wire is invalid â€” check that start, mid, end are not collinear.")

        length = wire.Length
        meta = WireMeta(name=name, wire_type="arc_path",
                        dimensions={"length_mm": round(length, 3),
                                    "start": start, "mid": mid, "end": end})
        self._state.wires[name] = (wire, meta)
        logger.info("create_arc_path: '%s' length=%.2fmm", name, length)
        return meta

    def create_rect_profile(
        self,
        name: str,
        width: float,
        height: float,
        corner_radius: float = 0.0,
    ) -> WireMeta:
        """
        Build a closed rectangular wire at the origin in the YZ plane
        (perpendicular to the X axis, which is where arc spines typically start).
        Width is in Y, height is in Z.
        """
        self._require_doc()
        if self._state and name in self._state.wires:
            raise RuntimeError(f"A wire named '{name}' already exists.")

        from freecad_bridge import get_freecad
        FC = get_freecad()
        import Part as _Part

        w2, h2 = width / 2.0, height / 2.0

        if corner_radius <= 0.0:
            pts = [
                FC.Vector(0, -w2, -h2),
                FC.Vector(0,  w2, -h2),
                FC.Vector(0,  w2,  h2),
                FC.Vector(0, -w2,  h2),
                FC.Vector(0, -w2, -h2),
            ]
            wire = _Part.makePolygon(pts)
        else:
            r = min(corner_radius, w2, h2)
            edges = []
            # Four straight sides with inset corners
            corners = [
                (FC.Vector(0, -w2+r, -h2), FC.Vector(0,  w2-r, -h2)),  # bottom
                (FC.Vector(0,  w2, -h2+r), FC.Vector(0,  w2,  h2-r)),  # right
                (FC.Vector(0,  w2-r,  h2), FC.Vector(0, -w2+r,  h2)),  # top
                (FC.Vector(0, -w2,  h2-r), FC.Vector(0, -w2, -h2+r)),  # left
            ]
            arc_centers = [
                FC.Vector(0,  w2-r, -h2+r),  # bottom-right
                FC.Vector(0,  w2-r,  h2-r),  # top-right
                FC.Vector(0, -w2+r,  h2-r),  # top-left
                FC.Vector(0, -w2+r, -h2+r),  # bottom-left
            ]
            for i, (p1, p2) in enumerate(corners):
                edges.append(_Part.LineSegment(p1, p2).toShape())
                c = arc_centers[i]
                p_arc_end = corners[(i + 1) % 4][0]
                # arc from p2 around corner c to p_arc_end
                arc_edge = _Part.Arc(p2, _Part.ArcOfCircle(
                    _Part.Circle(c, FC.Vector(1, 0, 0), r), 0, 1
                ).toShape().firstVertex().Point, p_arc_end)
                try:
                    edges.append(arc_edge.toShape())
                except Exception:
                    edges.append(_Part.LineSegment(p2, p_arc_end).toShape())
            wire = _Part.Wire(edges)

        if not wire.isClosed():
            raise RuntimeError("Profile wire is not closed â€” geometry error.")

        meta = WireMeta(name=name, wire_type="rect_profile",
                        dimensions={"width": width, "height": height,
                                    "corner_radius": corner_radius})
        self._state.wires[name] = (wire, meta)
        logger.info("create_rect_profile: '%s' %gÃ—%g r=%g", name, width, height, corner_radius)
        return meta

    def sweep(
        self,
        profile_name: str,
        path_name: str,
        result_name: str,
    ) -> ShapeMeta:
        """Sweep a closed profile wire along a path wire, producing a solid."""
        doc = self._require_doc()
        self._require_unique_name(result_name)

        if not self._state or profile_name not in self._state.wires:
            raise RuntimeError(f"Profile wire '{profile_name}' not found. Create it with POST /profiles/rect first.")
        if path_name not in self._state.wires:
            raise RuntimeError(f"Path wire '{path_name}' not found. Create it with POST /paths/create_arc first.")

        profile_wire, _ = self._state.wires[profile_name]
        path_wire, _    = self._state.wires[path_name]

        import Part as _Part

        last_exc = None
        solid = None

        # Method 1: makePipeShell with positional args (FreeCAD 1.x API)
        for make_solid_flag in (True, False):
            if solid is not None:
                break
            try:
                result = path_wire.makePipeShell([profile_wire], make_solid_flag, True)
                for cand in ([result] + list(result.Solids) if result.Solids else [result]):
                    if cand.Volume > 1.0:
                        solid = cand
                        break
            except Exception as exc:
                last_exc = exc

        # Method 2: makePipe fallback
        if solid is None:
            try:
                result2 = path_wire.makePipe(profile_wire)
                candidates = [result2] + list(result2.Solids) if result2.Solids else [result2]
                for cand in candidates:
                    if cand.Volume > 1.0:
                        solid = cand
                        break
                # If still no solid, try sewing the shell
                if solid is None and result2.Shells:
                    try:
                        s = _Part.Solid(result2.Shells[0])
                        if s.Volume > 1.0:
                            solid = s
                    except Exception:
                        pass
                # Last resort: use the compound directly if it has volume
                if solid is None and result2.Volume > 1.0:
                    solid = result2
            except Exception as exc2:
                last_exc = last_exc or exc2

        if solid is None or solid.Volume < 1.0:
            raise RuntimeError(
                f"Sweep failed to produce a solid with volume. "
                f"Last error: {last_exc}. "
                "Ensure the profile wire is closed and placed at the spine start point."
            )

        # Ensure clean BRep topology so boolean operations work
        try:
            cleaned = solid.removeSplitter()
            if cleaned.Volume > 1.0:
                solid = cleaned
        except Exception:
            pass

        feature = doc.addObject("Part::Feature", result_name)
        feature.Shape = solid
        doc.recompute()

        meta = ShapeMeta(
            name=result_name,
            shape_type="Sweep",
            position={"x": 0.0, "y": 0.0, "z": 0.0},
            dimensions={"volume_mm3": round(solid.Volume, 3),
                        "profile": profile_name, "path": path_name},
        )
        self._state.shapes[result_name] = meta
        logger.info("sweep: '%s' along '%s' â†’ '%s' vol=%.1f", profile_name, path_name, result_name, solid.Volume)
        return meta

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_doc(self):
        if self._doc is None:
            raise RuntimeError(
                "No active document. Call POST /document/create first."
            )
        return self._doc

    @staticmethod
    def _get_obj(doc, name: str):
        """
        Look up a FreeCAD document object by Name, falling back to Label search.

        FreeCAD auto-increments object Names on reuse (e.g., removing 'body' then
        adding 'body' produces 'body001'). We always set feature.Label = result_name
        after addObject, so Label-based fallback reliably finds in-place updated shapes.
        """
        obj = doc.getObject(name)   # search by FreeCAD internal Name first
        if obj is not None:
            return obj
        for o in doc.Objects:       # fall back to Label (set by _add_feature)
            if getattr(o, "Label", None) == name:
                return o
        return None

    @staticmethod
    def _add_feature(doc, name: str, shape):
        """
        Add a Part::Feature to the document with the given logical name.
        Sets both Name (best-effort) and Label (guaranteed) so _get_obj always finds it.
        Returns the created feature.
        """
        import Part as _Part
        feature = doc.addObject("Part::Feature", name)
        feature.Label = name   # guarantee Label matches even if FreeCAD renamed Name
        feature.Shape = shape
        return feature

    def _require_unique_name(self, name: str) -> None:
        if self._state and name in self._state.shapes:
            raise RuntimeError(
                f"A shape named '{name}' already exists in this document. "
                "Choose a different name."
            )

    def _require_unique_name_unless_consuming(self, name: str, consuming: list[str]) -> None:
        """Allow result_name to equal a shape that will be consumed (removed) by this op."""
        if self._state and name in self._state.shapes and name not in consuming:
            raise RuntimeError(
                f"A shape named '{name}' already exists. "
                "Choose a different result_name, or set it equal to the target_shape to update in place."
            )



    # ------------------------------------------------------------------
    # FEM — Finite Element Analysis
    # ------------------------------------------------------------------

    _FEM_FACE_SELECTORS = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")

    @staticmethod
    def _face_ref_by_selector(shape, selector: str) -> str:
        """Return 'FaceN' (1-indexed) matching the bounding-box face selector."""
        _VALID = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
        if selector not in _VALID:
            raise RuntimeError(
                f"Unknown face_selector '{selector}'. Valid: {list(_VALID)}"
            )
        bb = shape.BoundBox
        tol = max(bb.DiagonalLength * 0.001, 0.1)
        for i, face in enumerate(shape.Faces):
            fbb = face.BoundBox
            if selector == "xmin" and fbb.XMin <= bb.XMin + tol and fbb.XMax <= bb.XMin + tol:
                return f"Face{i+1}"
            if selector == "xmax" and fbb.XMax >= bb.XMax - tol and fbb.XMin >= bb.XMax - tol:
                return f"Face{i+1}"
            if selector == "ymin" and fbb.YMin <= bb.YMin + tol and fbb.YMax <= bb.YMin + tol:
                return f"Face{i+1}"
            if selector == "ymax" and fbb.YMax >= bb.YMax - tol and fbb.YMin >= bb.YMax - tol:
                return f"Face{i+1}"
            if selector == "zmin" and fbb.ZMin <= bb.ZMin + tol and fbb.ZMax <= bb.ZMin + tol:
                return f"Face{i+1}"
            if selector == "zmax" and fbb.ZMax >= bb.ZMax - tol and fbb.ZMin >= bb.ZMax - tol:
                return f"Face{i+1}"
        raise RuntimeError(
            f"No face found matching '{selector}' "
            f"(BBox X[{bb.XMin:.1f},{bb.XMax:.1f}] "
            f"Y[{bb.YMin:.1f},{bb.YMax:.1f}] "
            f"Z[{bb.ZMin:.1f},{bb.ZMax:.1f}]). "
            f"Valid selectors: {list(_VALID)}"
        )

    @staticmethod
    def _find_ccx_binary() -> str:
        import shutil, os
        candidates = [
            r"C:\Program Files\FreeCAD 1.1\bin\ccx.exe",
            r"C:\Program Files\FreeCAD 1.0\bin\ccx.exe",
            r"C:\Program Files\FreeCAD 0.21\bin\ccx.exe",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        found = shutil.which("ccx") or shutil.which("ccx2")
        if found:
            return found
        raise RuntimeError(
            "CalculiX (ccx) binary not found. "
            r"Expected at C:\Program Files\FreeCAD 1.1\bin\ccx.exe "
            "or available on PATH as 'ccx'."
        )

    def fem_create_analysis(self, shape_name: str) -> dict:
        """Create a FEM analysis container linked to an existing solid shape."""
        doc = self._require_doc()
        obj = self._get_obj(doc, shape_name)
        if obj is None:
            raise RuntimeError(f"Shape '{shape_name}' not found.")
        if not hasattr(obj, "Shape"):
            raise RuntimeError(f"'{shape_name}' has no geometry.")
        try:
            import ObjectsFem
        except ImportError as e:
            raise RuntimeError(
                "FreeCAD FEM module (ObjectsFem) not available in this Python environment. "
                "Ensure the server is launched with FreeCAD's bundled Python via start.bat."
            ) from e

        # Reset any prior FEM state in this session
        self._state.fem = FEMState()

        analysis = ObjectsFem.makeAnalysis(doc, "FEM_Analysis")
        doc.recompute()

        self._state.fem.analysis_name = analysis.Name
        self._state.fem.target_shape = shape_name
        logger.info("fem_create_analysis: analysis='%s' shape='%s'",
                    analysis.Name, shape_name)
        return {
            "analysis_name": analysis.Name,
            "shape_name": shape_name,
            "shape_volume_mm3": round(obj.Shape.Volume, 3),
        }

    def fem_mesh(
        self,
        shape_name: str,
        max_cell_size: float = 10.0,
        second_order: bool = True,
    ) -> dict:
        """Generate a Netgen tetrahedral mesh on the named shape."""
        doc = self._require_doc()
        fem = self._state.fem
        if not fem.analysis_name:
            raise RuntimeError("Call /fem/create_analysis before /fem/mesh.")
        analysis = doc.getObject(fem.analysis_name)
        if analysis is None:
            raise RuntimeError(f"Analysis object '{fem.analysis_name}' not found in document.")
        obj = self._get_obj(doc, shape_name)
        if obj is None:
            raise RuntimeError(f"Shape '{shape_name}' not found.")

        import ObjectsFem

        mesh_obj = ObjectsFem.makeMeshNetgenLegacy(doc, "FEMMeshNetgen")
        mesh_obj.Shape = obj
        mesh_obj.MaxSize = float(max_cell_size)
        mesh_obj.MinSize = max(0.1, float(max_cell_size) * 0.05)
        mesh_obj.SecondOrder = second_order
        mesh_obj.Optimize = True
        mesh_obj.Fineness = 3  # 0=VeryCoarse 5=VeryFine
        analysis.addObject(mesh_obj)
        doc.recompute()

        fem.mesh_name = mesh_obj.Name
        node_count = mesh_obj.FemMesh.NodeCount
        elem_count = mesh_obj.FemMesh.VolumeCount
        logger.info("fem_mesh: nodes=%d elements=%d max_size=%.1f",
                    node_count, elem_count, max_cell_size)
        return {
            "mesh_name": mesh_obj.Name,
            "node_count": node_count,
            "element_count": elem_count,
            "max_cell_size": max_cell_size,
            "second_order": second_order,
            "element_type": "Tet10" if second_order else "Tet4",
        }

    def fem_material(
        self,
        material_name: str = "Steel-1C22",
        youngs_modulus_mpa: float = 210000.0,
        poisson_ratio: float = 0.30,
        density_kg_m3: float = 7872.0,
    ) -> dict:
        """Add a mechanical material to the FEM analysis."""
        doc = self._require_doc()
        fem = self._state.fem
        if not fem.analysis_name:
            raise RuntimeError("Call /fem/create_analysis before /fem/material.")
        analysis = doc.getObject(fem.analysis_name)
        import ObjectsFem

        mat_obj = ObjectsFem.makeMaterialSolid(doc, "MechanicalMaterial")
        mat_obj.Material = {
            "Name": material_name,
            "YoungsModulus": f"{youngs_modulus_mpa} MPa",
            "PoissonRatio": str(poisson_ratio),
            "Density": f"{density_kg_m3} kg/m^3",
        }
        analysis.addObject(mat_obj)
        doc.recompute()

        fem.material_name = mat_obj.Name
        logger.info("fem_material: '%s' E=%.0f MPa nu=%.3f", material_name,
                    youngs_modulus_mpa, poisson_ratio)
        return {
            "material_object": mat_obj.Name,
            "material_name": material_name,
            "youngs_modulus_mpa": youngs_modulus_mpa,
            "poisson_ratio": poisson_ratio,
            "density_kg_m3": density_kg_m3,
        }

    def fem_constraint_fixed(self, shape_name: str, face_selector: str) -> dict:
        """Fix a face of the shape (zero displacement in all directions)."""
        doc = self._require_doc()
        fem = self._state.fem
        if not fem.analysis_name:
            raise RuntimeError("Call /fem/create_analysis before adding constraints.")
        analysis = doc.getObject(fem.analysis_name)
        obj = self._get_obj(doc, shape_name)
        if obj is None:
            raise RuntimeError(f"Shape '{shape_name}' not found.")

        import ObjectsFem

        face_ref = self._face_ref_by_selector(obj.Shape, face_selector)
        face = obj.Shape.Faces[int(face_ref[4:]) - 1]
        face_area = round(face.Area, 3)

        constraint = ObjectsFem.makeConstraintFixed(doc, f"ConstraintFixed_{face_selector}")
        constraint.References = [(obj, face_ref)]
        analysis.addObject(constraint)
        doc.recompute()

        fem.fixed_names.append(constraint.Name)
        logger.info("fem_constraint_fixed: shape='%s' face='%s' area=%.1f mm²",
                    shape_name, face_ref, face_area)
        return {
            "constraint_name": constraint.Name,
            "shape_name": shape_name,
            "face_selector": face_selector,
            "face_ref": face_ref,
            "face_area_mm2": face_area,
        }

    def fem_force_load(
        self,
        shape_name: str,
        face_selector: str,
        force_n: float,
        direction: list,
    ) -> dict:
        """Apply a distributed force on a face of the shape."""
        doc = self._require_doc()
        fem = self._state.fem
        if not fem.analysis_name:
            raise RuntimeError("Call /fem/create_analysis before adding loads.")
        analysis = doc.getObject(fem.analysis_name)
        obj = self._get_obj(doc, shape_name)
        if obj is None:
            raise RuntimeError(f"Shape '{shape_name}' not found.")

        from freecad_bridge import get_freecad
        FC = get_freecad()
        import ObjectsFem

        face_ref = self._face_ref_by_selector(obj.Shape, face_selector)
        face = obj.Shape.Faces[int(face_ref[4:]) - 1]
        face_area = round(face.Area, 3)

        dir_vec = FC.Vector(direction[0], direction[1], direction[2])
        # Normalise
        length = (dir_vec.x**2 + dir_vec.y**2 + dir_vec.z**2) ** 0.5
        if length < 1e-9:
            raise RuntimeError("direction vector must be non-zero.")
        dir_vec = FC.Vector(dir_vec.x / length, dir_vec.y / length, dir_vec.z / length)

        constraint = ObjectsFem.makeConstraintForce(doc, f"ConstraintForce_{face_selector}")
        constraint.References = [(obj, face_ref)]
        constraint.Force = float(force_n)
        constraint.DirectionVector = dir_vec
        constraint.Reversed = False
        analysis.addObject(constraint)
        doc.recompute()

        fem.force_names.append(constraint.Name)
        logger.info("fem_force_load: shape='%s' face='%s' force=%.1f N dir=%s",
                    shape_name, face_ref, force_n, list(direction))
        return {
            "constraint_name": constraint.Name,
            "shape_name": shape_name,
            "face_selector": face_selector,
            "face_ref": face_ref,
            "face_area_mm2": face_area,
            "force_n": force_n,
            "direction": [dir_vec.x, dir_vec.y, dir_vec.z],
        }

    def fem_run_solver(
        self,
        analysis_type: str = "static",
        working_dir: str = "",
    ) -> dict:
        """Write CalculiX .inp file and run the solver."""
        import os
        from pathlib import Path

        doc = self._require_doc()
        fem = self._state.fem
        if not fem.analysis_name:
            raise RuntimeError("No FEM analysis found. Call /fem/create_analysis first.")
        if not fem.mesh_name:
            raise RuntimeError("No mesh found. Call /fem/mesh first.")
        if not fem.material_name:
            raise RuntimeError("No material found. Call /fem/material first.")
        if not fem.fixed_names:
            raise RuntimeError("No fixed constraints found. Call /fem/constraint_fixed first.")
        if not fem.force_names:
            raise RuntimeError("No force loads found. Call /fem/force_load first.")

        analysis = doc.getObject(fem.analysis_name)
        import ObjectsFem

        # Create solver
        solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "SolverCcx")
        solver.AnalysisType = analysis_type
        solver.GeometricalNonlinearity = "linear"
        solver.ThermoMechSteadyState = False
        solver.MatrixSolverType = "spooles"
        analysis.addObject(solver)
        doc.recompute()
        fem.solver_name = solver.Name

        # Resolve working directory
        if not working_dir:
            working_dir = str(
                Path(__file__).parent / "output" / "fem"
            )
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        fem.working_dir = working_dir

        # Find and register CalculiX binary
        ccx_path = self._find_ccx_binary()
        from freecad_bridge import get_freecad
        FC = get_freecad()
        try:
            pref = FC.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
            pref.SetString("ccxBinaryPath", ccx_path)
        except Exception:
            pass

        from femtools import ccxtools
        import time

        fea = ccxtools.FemToolsCcx(analysis, solver)
        fea.update_objects()
        fea.setup_working_dir(working_dir)

        prereq_msg = fea.check_prerequisites()
        if prereq_msg:
            raise RuntimeError(f"FEM prerequisites not met: {prereq_msg}")

        inp_write_msg = fea.write_inp_file()
        if inp_write_msg:
            logger.warning("write_inp_file message: %s", inp_write_msg)

        inp_path = os.path.join(working_dir, "FEM_run.inp")

        t0 = time.time()
        run_msg = fea.ccx_run()
        elapsed = round(time.time() - t0, 2)

        # Load results into document
        fea.load_results()
        doc.recompute()

        # Find result object
        results_name = ""
        for o in doc.Objects:
            if o.isDerivedFrom("Fem::FemResultObject"):
                results_name = o.Name
                break
        fem.results_name = results_name

        logger.info("fem_run_solver: elapsed=%.1fs results='%s'", elapsed, results_name)
        return {
            "solver_name": solver.Name,
            "analysis_type": analysis_type,
            "working_dir": working_dir,
            "ccx_binary": ccx_path,
            "inp_file": inp_path,
            "elapsed_seconds": elapsed,
            "results_name": results_name,
            "run_message": str(run_msg) if run_msg else "",
        }

    def fem_get_results(self, quantity: str = "displacement_z") -> dict:
        """Extract scalar statistics from FEM results."""
        doc = self._require_doc()
        fem = self._state.fem

        if not fem.results_name:
            # Try to find result object
            for o in doc.Objects:
                if o.isDerivedFrom("Fem::FemResultObject"):
                    fem.results_name = o.Name
                    break
        if not fem.results_name:
            raise RuntimeError(
                "No FEM results found. Call /fem/run_solver first."
            )

        results = doc.getObject(fem.results_name)
        if results is None:
            raise RuntimeError(f"Result object '{fem.results_name}' not found.")

        # FreeCAD 1.1 stores displacements in DisplacementVectors (list of Base.Vector)
        # and magnitudes in DisplacementLengths. Stress in vonMises.
        _VECTOR_COMPONENT = {
            "displacement_x": "x",
            "displacement_y": "y",
            "displacement_z": "z",
        }
        _SCALAR_ATTR = {
            "displacement_magnitude": "DisplacementLengths",
            "von_mises_stress": "vonMises",
            "principal_stress_1": "PS1",
            "principal_stress_2": "PS2",
            "principal_stress_3": "PS3",
            "temperature": "Temperature",
        }
        _VALID = list(_VECTOR_COMPONENT.keys()) + list(_SCALAR_ATTR.keys())
        if quantity not in _VALID:
            raise RuntimeError(
                f"Unknown quantity '{quantity}'. Valid: {_VALID}"
            )

        if quantity in _VECTOR_COMPONENT:
            component = _VECTOR_COMPONENT[quantity]
            vecs = getattr(results, "DisplacementVectors", None)
            if vecs is None or len(vecs) == 0:
                available = []
                if getattr(results, "DisplacementVectors", None):
                    available += ["displacement_x", "displacement_y", "displacement_z", "displacement_magnitude"]
                for k, v in _SCALAR_ATTR.items():
                    if getattr(results, v, None):
                        available.append(k)
                raise RuntimeError(
                    f"Quantity '{quantity}' not available in results. "
                    f"Available: {available}"
                )
            # FreeCAD CCX importer returns DisplacementVectors in meters; convert to mm
            vals = [getattr(v, component) * 1000.0 for v in vecs]
        else:
            attr = _SCALAR_ATTR[quantity]
            scalar_vals = getattr(results, attr, None)
            if scalar_vals is None or len(scalar_vals) == 0:
                available = []
                if getattr(results, "DisplacementVectors", None):
                    available += ["displacement_x", "displacement_y", "displacement_z", "displacement_magnitude"]
                for k, v in _SCALAR_ATTR.items():
                    if getattr(results, v, None):
                        available.append(k)
                raise RuntimeError(
                    f"Quantity '{quantity}' not available in results. "
                    f"Available: {available}"
                )
            # DisplacementLengths is also in meters from CCX importer; convert to mm
            if quantity == "displacement_magnitude":
                vals = [v * 1000.0 for v in scalar_vals]
            else:
                vals = list(scalar_vals)
        min_val = round(min(vals), 4)
        max_val = round(max(vals), 4)
        abs_max = max(abs(min_val), abs(max_val))

        attr_label = _VECTOR_COMPONENT.get(quantity, _SCALAR_ATTR.get(quantity, quantity))
        logger.info("fem_get_results: %s min=%.4f max=%.4f nodes=%d",
                    quantity, min_val, max_val, len(vals))
        return {
            "quantity": quantity,
            "attribute": attr_label,
            "min_value": min_val,
            "max_value": max_val,
            "abs_max_value": round(abs_max, 4),
            "node_count": len(vals),
            "unit": "mm" if "displacement" in quantity else "MPa",
            "results_name": fem.results_name,
        }

    # ------------------------------------------------------------------
    # Mechanical integration checks
    # ------------------------------------------------------------------

    def check_interference(self, shape_a: str, shape_b: str) -> dict:
        """
        Compute the boolean intersection of two shapes and return its volume.

        Use to verify:
        - Parts that SHOULD NOT overlap: expect interference_volume_mm3 < 0.1
        - Parts that SHOULD engage (screw in bore): expect a substantial overlap volume
        """
        from freecad_bridge import get_freecad
        get_freecad()

        doc = self._require_doc()
        obj_a = self._get_obj(doc, shape_a)
        obj_b = self._get_obj(doc, shape_b)
        if obj_a is None:
            raise RuntimeError(f"Shape '{shape_a}' not found.")
        if obj_b is None:
            raise RuntimeError(f"Shape '{shape_b}' not found.")
        if not hasattr(obj_a, "Shape"):
            raise RuntimeError(f"'{shape_a}' has no geometry.")
        if not hasattr(obj_b, "Shape"):
            raise RuntimeError(f"'{shape_b}' has no geometry.")

        intersection = obj_a.Shape.common(obj_b.Shape)
        int_vol = round(intersection.Volume, 4)
        vol_a = round(obj_a.Shape.Volume, 4)
        vol_b = round(obj_b.Shape.Volume, 4)
        frac_a = round(int_vol / vol_a, 6) if vol_a > 0 else 0.0
        frac_b = round(int_vol / vol_b, 6) if vol_b > 0 else 0.0

        logger.info(
            "check_interference '%s' x '%s': vol=%.2f mm3 (%.1f%% of A, %.1f%% of B)",
            shape_a, shape_b, int_vol, frac_a * 100, frac_b * 100,
        )
        return {
            "shape_a": shape_a,
            "shape_b": shape_b,
            "interference_volume_mm3": int_vol,
            "has_interference": int_vol > 0.1,
            "shape_a_volume_mm3": vol_a,
            "shape_b_volume_mm3": vol_b,
            "interference_fraction_of_a": frac_a,
            "interference_fraction_of_b": frac_b,
        }

    def check_min_distance(self, shape_a: str, shape_b: str) -> dict:
        """
        Compute the minimum surface-to-surface distance between two shapes.

        Returns 0.0 when shapes touch or overlap.
        Use to verify required clearances (min_distance_mm >= required_gap).
        """
        from freecad_bridge import get_freecad
        get_freecad()

        doc = self._require_doc()
        obj_a = self._get_obj(doc, shape_a)
        obj_b = self._get_obj(doc, shape_b)
        if obj_a is None:
            raise RuntimeError(f"Shape '{shape_a}' not found.")
        if obj_b is None:
            raise RuntimeError(f"Shape '{shape_b}' not found.")
        if not hasattr(obj_a, "Shape"):
            raise RuntimeError(f"'{shape_a}' has no geometry.")
        if not hasattr(obj_b, "Shape"):
            raise RuntimeError(f"'{shape_b}' has no geometry.")

        dist, pairs, _ = obj_a.Shape.distToShape(obj_b.Shape)
        dist = round(dist, 4)
        pt_a = ({"x": round(pairs[0][0].x, 3), "y": round(pairs[0][0].y, 3), "z": round(pairs[0][0].z, 3)}
                if pairs else {})
        pt_b = ({"x": round(pairs[0][1].x, 3), "y": round(pairs[0][1].y, 3), "z": round(pairs[0][1].z, 3)}
                if pairs else {})

        logger.info("check_min_distance '%s' <-> '%s': %.3f mm", shape_a, shape_b, dist)
        return {
            "shape_a": shape_a,
            "shape_b": shape_b,
            "min_distance_mm": dist,
            "is_touching_or_overlapping": dist < 0.01,
            "closest_point_on_a": pt_a,
            "closest_point_on_b": pt_b,
        }

# ---------------------------------------------------------------------------
# Module-level singleton â€” imported by main.py
# ---------------------------------------------------------------------------

_session = FreeCADSession()
_session_lock = asyncio.Lock()


def get_session() -> FreeCADSession:
    return _session


def get_session_lock() -> asyncio.Lock:
    """Acquire before any mutating session call to prevent concurrent document corruption."""
    return _session_lock


