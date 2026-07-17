"""
FreeCAD Tool Server — Phase 0
FastAPI application exposing 5 high-level tools for AI agents.

Start with:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Or:
    python main.py
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from freecad_bridge import freecad_available, get_freecad
from models import (
    AddBoxRequest,
    AddConeRequest,
    AddCylinderRequest,
    AddWingRequest,
    MirrorShapeRequest,
    BooleanCutRequest,
    BooleanUnionRequest,
    ChamferEdgesRequest,
    CreateArcPathRequest,
    ExtrudePolygonRequest,
    PolarPatternRequest,
    RevolveProfileRequest,
    CreateRectProfileRequest,
    LinearPatternRequest,
    BoundingBoxResult,
    CreateDocumentRequest,
    DocumentInfo,
    ExportAssemblyRequest,
    ExportStepRequest,
    FilletEdgesRequest,
    ElmerSetupHeatRequest,
    ElmerRunRequest,
    ElmerGetResultsRequest,
    ElmerSetupRadiationHeatRequest,
    FEMCreateAnalysisRequest,
    FEMConstraintFixedRequest,
    FEMForceLoadRequest,
    FEMGetResultsRequest,
    FEMMaterialRequest,
    FEMMeshRequest,
    FEMRunSolverRequest,
    AddPropellerBladeRequest,
    PropellerBladeStation,
    CheckInterferenceRequest,
    CheckMinDistanceRequest,
    GetShapeInfoRequest,
    HealthResponse,
    ScreenshotRequest,
    MakeHoleRequest,
    ShapeInfo,
    SolidValidationResult,
    SweepRequest,
    ToolResponse,
    ValidateStepRequest,
)
from session import get_session, get_session_lock
import elmer_solver as elmer
import elmer_radiation as elmer_rad

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("freecad_server")


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FreeCAD Tool Server starting up…")
    if freecad_available():
        FC = get_freecad()
        logger.info("FreeCAD %s ready.", FC.Version()[0])
    else:
        logger.warning(
            "FreeCAD NOT found. Set FREECAD_PATH env var to your FreeCAD bin directory. "
            "Tool endpoints will return errors until FreeCAD is available."
        )
    yield
    logger.info("Shutting down — closing any open document.")
    get_session().close_document()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FreeCAD Tool Server",
    description=(
        "High-level HTTP API for AI agents to control FreeCAD. "
        "Create 3D geometry, query model properties, and export STEP files "
        "through clean, strongly-typed tool endpoints."
    ),
    version="0.2.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# C1 fix: Wrap Pydantic validation errors in ToolResponse envelope
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Ensure all input validation failures return ToolResponse format, not FastAPI's
    default {"detail": [...]} schema — so agents always see success/message/errors.
    """
    errors = [
        f"{' → '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=ToolResponse(
            success=False,
            message="Input validation failed — check field values and types.",
            errors=errors,
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(message: str, data: dict | None = None, warnings: list[str] | None = None) -> ToolResponse:
    return ToolResponse(success=True, message=message, data=data, warnings=warnings or [])


def _err(message: str, errors: list[str] | None = None) -> ToolResponse:
    return ToolResponse(success=False, message=message, errors=errors or [message])


def _freecad_guard() -> None:
    """Raise HTTP 503 if FreeCAD is not available."""
    if not freecad_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "FreeCAD is not available on this server. "
                "Set FREECAD_PATH to your FreeCAD bin directory and restart."
            ),
        )


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------

@app.get("/", response_model=HealthResponse, tags=["Status"])
async def root() -> HealthResponse:
    """
    Server health check.

    Returns FreeCAD availability, version, and current document state.
    Agents should call this first to confirm the server is operational.
    """
    session = get_session()
    fc_ok = freecad_available()
    version = None
    if fc_ok:
        try:
            version = ".".join(get_freecad().Version()[:3])
        except Exception:
            pass

    return HealthResponse(
        status="ok" if fc_ok else "degraded",
        freecad_available=fc_ok,
        freecad_version=version,
        active_document=session.state.document_name if session.is_active else None,
        shape_count=session.state.shape_count if session.is_active else 0,
    )


@app.get("/health", response_model=HealthResponse, tags=["Status"])
async def health() -> HealthResponse:
    """Alias for the root health endpoint."""
    return await root()


# ---------------------------------------------------------------------------
# Tool 1 — create_document
# ---------------------------------------------------------------------------

@app.post("/document/create", response_model=ToolResponse, tags=["Document"])
async def create_document(req: CreateDocumentRequest) -> ToolResponse:
    """
    **Tool: create_document**

    Create a new FreeCAD document (and session). If a document is already open
    it will be closed and replaced — Phase 0 supports one document at a time.

    Call this before adding any shapes. The returned `session_id` uniquely
    identifies this session and appears in all subsequent responses.

    **Inputs**
    - `name`: Document name (identifier-safe string, default: "Model")

    **Returns**
    - `session_id`, `document_name`, `created_at`, `shape_count`
    """
    _freecad_guard()
    session = get_session()
    warnings: list[str] = []

    try:
        if session.is_active:
            warnings.append(
                f"Previous document '{session.state.document_name}' was closed "
                "to open the new one."
            )
        state = session.create_document(req.name)
        return _ok(
            message=f"Document '{req.name}' created successfully.",
            data=DocumentInfo(
                session_id=state.session_id,
                document_name=state.document_name,
                created_at=state.created_at,
                shape_count=state.shape_count,
            ).model_dump(mode="json"),
            warnings=warnings,
        )
    except Exception as exc:
        logger.exception("create_document failed")
        return _err(f"Failed to create document: {exc}")


# ---------------------------------------------------------------------------
# Tool 2 — add_box
# ---------------------------------------------------------------------------

@app.post("/shapes/add_box", response_model=ToolResponse, tags=["Shapes"])
async def add_box(req: AddBoxRequest) -> ToolResponse:
    """
    **Tool: add_box**

    Add a rectangular box (cuboid) to the active document.

    The box origin is at the given (x, y, z) coordinate and extends in the
    +X, +Y, +Z directions by `length`, `width`, and `height` respectively.

    **Inputs**
    - `name`: Unique label for the shape
    - `length` / `width` / `height`: Dimensions in mm (all > 0)
    - `x` / `y` / `z`: Position of the box corner origin in mm (default 0)

    **Returns**
    - Shape metadata including volume, surface area, position, and dimensions
    """
    _freecad_guard()
    session = get_session()

    try:
        meta = session.add_box(
            name=req.name,
            length=req.length,
            width=req.width,
            height=req.height,
            x=req.x,
            y=req.y,
            z=req.z,
            rotation_z=req.rotation_z,
        )
        info = session.get_shape_info(req.name)
        return _ok(
            message=f"Box '{req.name}' added successfully.",
            data=ShapeInfo(**info).model_dump(),
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("add_box failed")
        return _err(f"Unexpected error adding box: {exc}")


# ---------------------------------------------------------------------------
# Tool 3 — add_cylinder
# ---------------------------------------------------------------------------

@app.post("/shapes/add_cylinder", response_model=ToolResponse, tags=["Shapes"])
async def add_cylinder(req: AddCylinderRequest) -> ToolResponse:
    """
    **Tool: add_cylinder**

    Add a cylinder to the active document.

    The cylinder base-center is placed at (x, y, z) and the cylinder extends
    upward along the +Z axis by `height`. The cross-section has the given `radius`.

    **Inputs**
    - `name`: Unique label for the shape
    - `radius`: Cylinder radius in mm (> 0)
    - `height`: Cylinder height in mm (> 0)
    - `x` / `y` / `z`: Position of the base-center in mm (default 0)

    **Returns**
    - Shape metadata including volume, surface area, position, and dimensions
    """
    _freecad_guard()
    session = get_session()

    try:
        session.add_cylinder(
            name=req.name,
            radius=req.radius,
            height=req.height,
            x=req.x,
            y=req.y,
            z=req.z,
            axis=req.axis,
        )
        info = session.get_shape_info(req.name)
        return _ok(
            message=f"Cylinder '{req.name}' added successfully.",
            data=ShapeInfo(**info).model_dump(),
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("add_cylinder failed")
        return _err(f"Unexpected error adding cylinder: {exc}")


@app.post("/shapes/add_cone", response_model=ToolResponse, tags=["Shapes"])
async def add_cone(req: AddConeRequest) -> ToolResponse:
    """
    **Tool: add_cone**

    Add a cone or frustum (truncated cone) to the active document.

    A frustum has a circular base (radius1) and a circular top (radius2). Set radius2=0
    for a true point-tip cone. Use this for tapered shafts, countersink drill profiles,
    nozzles, taper transitions, and any geometry where the cross-section radius changes
    linearly along the axis.

    **Inputs**
    - `name`: Unique label for the shape
    - `radius1`: Bottom radius in mm (> 0)
    - `radius2`: Top radius in mm (≥ 0, set 0 for a point)
    - `height`: Height in mm (> 0)
    - `x` / `y` / `z`: Position of the base center (mm)
    - `axis`: Direction the cone extends — 'x', 'y', or 'z' (default 'z')
    """
    _freecad_guard()
    session = get_session()
    try:
        meta = session.add_cone(req.name, req.radius1, req.radius2, req.height, req.x, req.y, req.z, req.axis)
        return _ok(
            message=f"Cone '{req.name}' added: R1={req.radius1}mm R2={req.radius2}mm H={req.height}mm.",
            data={"name": meta.name, **meta.dimensions, "position": meta.position},
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("add_cone failed")
        return _err(f"Unexpected error adding cone: {exc}")


@app.post("/shapes/add_wing", response_model=ToolResponse, tags=["Shapes"])
async def add_wing(req: AddWingRequest) -> ToolResponse:
    """
    **Tool: add_wing**

    Generate a tapered wing half using a NACA 4-digit airfoil profile lofted from root to tip.

    The wing extends in the **+Y direction** from the root at (x, y, z) to tip at
    (x + sweep_offset, y + half_span, z + dihedral_offset).

    - `root_chord` / `tip_chord`: chord lengths in mm — taper is applied automatically.
    - `thickness_ratio`: max thickness as fraction of chord (0.12 = NACA ??12).
    - `naca_camber` / `naca_camber_pos`: camber fraction and position (0 = symmetric airfoil).
    - `sweep_le`: leading-edge sweep in degrees (positive = aft); adds x-offset to tip.
    - `dihedral`: dihedral in degrees (positive = tip raised); adds z-offset to tip.

    **To create both wings**: call add_wing for the right side, then use `mirror` (plane=xz)
    to create the left side, then `boolean_union` both into the fuselage.

    **Airfoil presets**:
    - NACA 2412 (general aviation): camber=0.02, camber_pos=0.4, thickness=0.12
    - NACA 0009 (symmetric tail): camber=0.0, camber_pos=0.4, thickness=0.09
    - NACA 2415 (thicker wing): camber=0.02, camber_pos=0.4, thickness=0.15
    """
    _freecad_guard()
    async with get_session_lock():
        session = get_session()
        try:
            meta = session.add_wing(
                req.name,
                req.root_chord, req.tip_chord, req.half_span,
                req.thickness_ratio, req.naca_camber, req.naca_camber_pos,
                req.x, req.y, req.z,
                req.sweep_le, req.dihedral, req.span_axis,
            )
            return _ok(
                message=(
                    f"Wing '{req.name}' created: root_chord={req.root_chord}mm "
                    f"tip_chord={req.tip_chord}mm span={req.half_span}mm "
                    f"NACA {round(req.naca_camber*100)}{round(req.naca_camber_pos*10)}"
                    f"{round(req.thickness_ratio*100):02d}."
                ),
                data={"name": meta.name, **meta.dimensions, "position": meta.position},
            )
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("add_wing failed")
            return _err(f"Unexpected error creating wing: {exc}")


@app.post("/shapes/add_propeller_blade", response_model=ToolResponse, tags=["Shapes"])
async def add_propeller_blade(req: AddPropellerBladeRequest) -> ToolResponse:
    """
    **Tool: add_propeller_blade**

    Generate a twisted, tapered propeller blade by lofting NACA 4-digit airfoil
    cross-sections through radial stations. Each station has independent chord,
    twist angle, and NACA profile — enabling realistic spanwise twist and taper.

    **Inputs**
    - `name`: Shape name for the resulting solid
    - `stations`: List of radial cross-sections (root to tip), each with r_mm, chord_mm,
      twist_deg, naca (4-digit string), and tc_pct (thickness override)
    - `rotation_axis`: Propeller spin axis — x, y, or z (default z)
    - `hub_offset_mm`: Radial offset added to all station r_mm values

    **Returns**
    - Shape metadata including volume, faces, edges
    """
    _freecad_guard()
    async with get_session_lock():
        session = get_session()
        try:
            import Part
            import math
            import FreeCAD

            def make_naca4_points(naca_str, chord, tc_pct_override=0.0, n_points=32):
                """Generate NACA 4-digit airfoil points, scaled to chord."""
                m = int(naca_str[0]) / 100.0
                p = int(naca_str[1]) / 10.0
                t_default = int(naca_str[2:]) / 100.0
                t = (tc_pct_override / 100.0) if tc_pct_override > 0 else t_default

                # Cosine spacing for better LE resolution
                betas = [math.pi * i / (n_points - 1) for i in range(n_points)]
                xs = [(1 - math.cos(b)) / 2 for b in betas]

                def thickness(x):
                    return 5 * t * (0.2969*math.sqrt(max(x, 0)) - 0.1260*x
                                    - 0.3516*x**2 + 0.2843*x**3 - 0.1015*x**4)

                def camber_and_slope(x):
                    if p == 0 or m == 0:
                        return 0.0, 0.0
                    if x < p:
                        yc = m/p**2 * (2*p*x - x**2)
                        dyc = 2*m/p**2 * (p - x)
                    else:
                        yc = m/(1-p)**2 * ((1-2*p) + 2*p*x - x**2)
                        dyc = 2*m/(1-p)**2 * (p - x)
                    return yc, dyc

                upper = []
                lower = []
                for x in xs:
                    yc, dyc = camber_and_slope(x)
                    yt = thickness(x)
                    theta = math.atan(dyc)
                    xu = x - yt * math.sin(theta)
                    yu = yc + yt * math.cos(theta)
                    xl = x + yt * math.sin(theta)
                    yl = yc - yt * math.cos(theta)
                    upper.append((xu * chord, yu * chord))
                    lower.append((xl * chord, yl * chord))

                pts = upper + list(reversed(lower[1:-1]))
                return pts

            def make_blade_wire(naca_str, chord_mm, twist_deg, r_mm, axis, tc_pct):
                pts_2d = make_naca4_points(naca_str, chord_mm, tc_pct)
                twist_rad = math.radians(twist_deg)
                cos_t = math.cos(twist_rad)
                sin_t = math.sin(twist_rad)

                # Center airfoil at quarter-chord before rotating
                qc_x = chord_mm * 0.25
                verts = []
                for (xc, yc) in pts_2d:
                    xc_centered = xc - qc_x
                    chord_rot = xc_centered * cos_t - yc * sin_t
                    thick_rot = xc_centered * sin_t + yc * cos_t
                    if axis == 'z':
                        v = FreeCAD.Vector(r_mm, chord_rot, thick_rot)
                    elif axis == 'x':
                        v = FreeCAD.Vector(chord_rot, r_mm, thick_rot)
                    else:  # y
                        v = FreeCAD.Vector(chord_rot, thick_rot, r_mm)
                    verts.append(v)

                # Close the loop by adding first point again
                verts.append(verts[0])

                # Build BSpline through points (non-periodic open curve that closes)
                bspline = Part.BSplineCurve()
                bspline.interpolate(verts, PeriodicFlag=False)
                edge = bspline.toShape()
                wire = Part.Wire(edge)
                return wire

            if not session.is_active:
                return _err("No active document. Call /document/create first.")

            doc = session._doc  # access underlying FreeCAD document

            wires = []
            axis = req.rotation_axis.lower()
            for station in req.stations:
                r = station.r_mm + req.hub_offset_mm
                w = make_blade_wire(
                    station.naca,
                    station.chord_mm,
                    station.twist_deg,
                    r,
                    axis,
                    station.tc_pct,
                )
                wires.append(w)

            # Loft through all wires
            try:
                blade_shape = Part.makeLoft(wires, True, False, False)
            except Exception as loft_err:
                logger.warning(f"BSpline loft failed ({loft_err}), trying polygon fallback")
                # Polygon fallback
                poly_wires = []
                for station in req.stations:
                    r = station.r_mm + req.hub_offset_mm
                    pts_2d = make_naca4_points(station.naca, station.chord_mm, station.tc_pct)
                    twist_rad = math.radians(station.twist_deg)
                    cos_t = math.cos(twist_rad)
                    sin_t = math.sin(twist_rad)
                    qc_x = station.chord_mm * 0.25
                    verts = []
                    for (xc, yc) in pts_2d:
                        xc_c = xc - qc_x
                        cr = xc_c * cos_t - yc * sin_t
                        tr = xc_c * sin_t + yc * cos_t
                        if axis == 'z':
                            verts.append(FreeCAD.Vector(r, cr, tr))
                        elif axis == 'x':
                            verts.append(FreeCAD.Vector(cr, r, tr))
                        else:
                            verts.append(FreeCAD.Vector(cr, tr, r))
                    verts.append(verts[0])
                    poly_wires.append(Part.makePolygon(verts))
                blade_shape = Part.makeLoft(poly_wires, True, False, False)

            if blade_shape is None or blade_shape.isNull():
                return _err("Loft produced a null shape — check station geometry.")

            # Register shape in document
            part_obj = doc.addObject("Part::Feature", req.name)
            part_obj.Shape = blade_shape
            doc.recompute()

            # Record in session state
            from session import ShapeMeta
            bb = blade_shape.BoundBox
            vol = blade_shape.Volume
            area = blade_shape.Area
            meta = ShapeMeta(
                name=req.name,
                shape_type="PropellerBlade",
                position={"x": bb.XMin, "y": bb.YMin, "z": bb.ZMin},
                dimensions={
                    "volume_mm3": vol,
                    "surface_area_mm2": area,
                    "station_count": len(req.stations),
                    "root_r_mm": req.stations[0].r_mm,
                    "tip_r_mm": req.stations[-1].r_mm,
                    "root_chord_mm": req.stations[0].chord_mm,
                    "tip_chord_mm": req.stations[-1].chord_mm,
                    "root_twist_deg": req.stations[0].twist_deg,
                    "tip_twist_deg": req.stations[-1].twist_deg,
                },
            )
            session.state.shapes[req.name] = meta

            info = session.get_shape_info(req.name)
            return _ok(
                message=(
                    f"Propeller blade '{req.name}' created: {len(req.stations)} stations, "
                    f"twist {req.stations[0].twist_deg:.1f}°→{req.stations[-1].twist_deg:.1f}°, "
                    f"vol={vol:.1f} mm³."
                ),
                data=ShapeInfo(**info).model_dump(),
            )
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("add_propeller_blade failed")
            import traceback
            return _err(f"Unexpected error creating propeller blade: {exc}\n{traceback.format_exc()}")


@app.post("/operations/mirror", response_model=ToolResponse, tags=["Operations"])
async def mirror_shape(req: MirrorShapeRequest) -> ToolResponse:
    """
    **Tool: mirror**

    Mirror a shape across the XY, XZ, or YZ plane through the origin.

    By default (`keep_original=true`) the source shape is kept and the mirrored copy
    is added as a new shape. Call `boolean_union(source, mirror)` afterward to produce
    a complete symmetric solid from the two halves.

    **Workflow for symmetric parts:**
    1. Build one half of the part (e.g., left half of a bracket, origin at the symmetry plane)
    2. `mirror(source="half", plane="yz", result_name="half_mirror")`
    3. `boolean_union("half", "half_mirror", result_name="bracket")` → full symmetric solid

    **Planes:**
    - `yz`: mirrors across X=0 (flips X — use when part is symmetric left-right)
    - `xz`: mirrors across Y=0 (flips Y — use when part is symmetric front-back)
    - `xy`: mirrors across Z=0 (flips Z — use when part is symmetric top-bottom)
    """
    _freecad_guard()
    session = get_session()
    try:
        meta = session.mirror_shape(req.source_shape, req.plane, req.result_name, req.keep_original)
        return _ok(
            message=(
                f"Mirror of '{req.source_shape}' across {req.plane.upper()} plane → '{req.result_name}' "
                f"(vol={meta.dimensions['volume_mm3']:.1f}mm³)."
            ),
            data={"name": meta.name, **meta.dimensions},
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("mirror_shape failed")
        return _err(f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Tool 4 — get_bounding_box
# ---------------------------------------------------------------------------

@app.get("/model/bounding_box", response_model=ToolResponse, tags=["Query"])
async def get_bounding_box() -> ToolResponse:
    """
    **Tool: get_bounding_box**

    Compute the axis-aligned bounding box (AABB) of all shapes in the active document.

    Use this to understand the overall extents of the model before export,
    or to verify that shapes are positioned as expected.

    **Returns**
    - Min/max extents on X, Y, Z axes (mm)
    - X, Y, Z sizes (mm)
    - Overall diagonal length (mm)
    - Count and names of included shapes
    """
    _freecad_guard()
    session = get_session()

    try:
        result = session.get_bounding_box()
        warnings = result.pop("_warnings", [])
        bb = BoundingBoxResult(**result)
        return _ok(
            message="Bounding box computed successfully.",
            data=bb.model_dump(),
            warnings=warnings,
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("get_bounding_box failed")
        return _err(f"Unexpected error computing bounding box: {exc}")


# ---------------------------------------------------------------------------
# Tool: screenshot
# ---------------------------------------------------------------------------

@app.post("/model/screenshot", response_model=ToolResponse, tags=["Query"])
async def screenshot(req: ScreenshotRequest) -> ToolResponse:
    """
    **Tool: screenshot**

    Render a PNG image of the named shape (or all shapes in the document) using
    FreeCAD's tessellation engine and matplotlib's 3D renderer.

    **Requires matplotlib** in FreeCAD's bundled Python:
    ```
    "C:\\Program Files\\FreeCAD 1.1\\bin\\python.exe" -m pip install matplotlib
    ```

    **Inputs**
    - `shape_name`: shape to render (omit to render all shapes)
    - `view`: camera angle — `iso`, `front`, `back`, `top`, `bottom`, `right`, `left`
    - `width` / `height`: image dimensions in pixels (default 800×600)
    - `output_path`: if set, writes PNG to disk and returns path; if empty, returns base64 PNG

    **Returns**
    - `image_base64` (PNG) when no output_path — can be displayed directly in a browser
    - `output_path` + `file_size_bytes` when saved to disk
    - `shape_count`, `view`, `width`, `height`
    """
    _freecad_guard()
    session = get_session()
    try:
        result = session.screenshot(
            shape_name=req.shape_name,
            view=req.view,
            width=req.width,
            height=req.height,
            output_path=req.output_path,
        )
        shape_desc = req.shape_name or "all shapes"
        return _ok(
            message=f"Screenshot rendered: {shape_desc}, view={req.view}, "
                    f"{req.width}×{req.height}px.",
            data=result,
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("screenshot failed")
        return _err(f"Unexpected error during screenshot: {exc}")


# ---------------------------------------------------------------------------
# Tool: get_shape_info
# ---------------------------------------------------------------------------

@app.post("/model/get_shape_info", response_model=ToolResponse, tags=["Query"])
async def get_shape_info(req: GetShapeInfoRequest) -> ToolResponse:
    """
    **Tool: get_shape_info**

    Return volume, surface area, face count, and edge count for any named shape
    in the active document. Use this to verify geometry after booleans, measure
    material volume, or inspect edge topology before running fillet/chamfer.

    **Inputs**
    - `shape_name`: name of the shape to inspect

    **Returns**
    - `volume_mm3`, `surface_area_mm2`
    - `face_count`, `edge_count`
    - `shape_type`, `position`, `dimensions`
    """
    _freecad_guard()
    session = get_session()
    try:
        info = session.get_shape_info(req.shape_name)
        return _ok(
            message=f"Shape '{req.shape_name}': {info['volume_mm3']:.1f} mm³, "
                    f"{info['face_count']} faces, {info['edge_count']} edges.",
            data=ShapeInfo(**info).model_dump(),
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("get_shape_info failed")
        return _err(f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Mechanical integration checks
# ---------------------------------------------------------------------------

@app.post("/model/check_interference", response_model=ToolResponse, tags=["Query"])
async def check_interference(req: CheckInterferenceRequest) -> ToolResponse:
    """
    **Tool: check_interference**

    Compute the boolean intersection volume of two shapes.

    Use this to verify assembly fit:
    - Parts that **should NOT overlap** (e.g. handlebar vs stem body clamp):
      expect `interference_volume_mm3 < 0.1` and `has_interference = false`
    - Parts that **should engage** (e.g. screw shank in bore hole):
      expect `interference_fraction_of_b > 0.8` (screw is mostly inside the bore)

    **Workflow**: add a witness solid at its nominal installed position, call
    this endpoint, then remove the witness before export.

    **Returns** interference volume, per-part volumes, and fractional overlaps.
    """
    _freecad_guard()
    async with get_session_lock():
        session = get_session()
        try:
            data = session.check_interference(req.shape_a, req.shape_b)
            if data["has_interference"]:
                msg = (
                    f"INTERFERENCE: '{req.shape_a}' and '{req.shape_b}' overlap by "
                    f"{data['interference_volume_mm3']:.2f} mm³ "
                    f"({data['interference_fraction_of_a']*100:.1f}% of A, "
                    f"{data['interference_fraction_of_b']*100:.1f}% of B)."
                )
            else:
                msg = (
                    f"CLEAR: '{req.shape_a}' and '{req.shape_b}' do not overlap "
                    f"(intersection volume = {data['interference_volume_mm3']:.4f} mm³)."
                )
            return _ok(message=msg, data=data)
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("check_interference failed")
            return _err(f"Interference check failed: {exc}")


@app.post("/model/check_min_distance", response_model=ToolResponse, tags=["Query"])
async def check_min_distance(req: CheckMinDistanceRequest) -> ToolResponse:
    """
    **Tool: check_min_distance**

    Compute the minimum surface-to-surface distance between two shapes.

    Returns 0.0 when shapes touch or overlap. Use this to verify clearances:
    - `min_distance_mm >= required_clearance_mm` → clearance is satisfied
    - `is_touching_or_overlapping = true` → shapes are in contact or colliding

    Also returns the closest point on each shape so you can identify where
    the near-contact occurs.

    **Returns** min_distance_mm, is_touching_or_overlapping, closest_point_on_a/b.
    """
    _freecad_guard()
    async with get_session_lock():
        session = get_session()
        try:
            data = session.check_min_distance(req.shape_a, req.shape_b)
            warnings = []
            if req.required_clearance_mm > 0 and data["min_distance_mm"] < req.required_clearance_mm:
                warnings.append(
                    f"Clearance {data['min_distance_mm']:.3f} mm is less than required "
                    f"{req.required_clearance_mm:.3f} mm."
                )
            if data["is_touching_or_overlapping"]:
                msg = (
                    f"CONTACT: '{req.shape_a}' and '{req.shape_b}' are touching or overlapping "
                    f"(distance = {data['min_distance_mm']:.4f} mm)."
                )
            else:
                msg = (
                    f"GAP: '{req.shape_a}' to '{req.shape_b}' minimum distance = "
                    f"{data['min_distance_mm']:.3f} mm."
                )
            return _ok(message=msg, data=data, warnings=warnings)
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("check_min_distance failed")
            return _err(f"Distance check failed: {exc}")


# ---------------------------------------------------------------------------
# Tool 5 — export_step
# ---------------------------------------------------------------------------

@app.post("/model/export_step", response_model=ToolResponse, tags=["Export"])
async def export_step(req: ExportStepRequest) -> ToolResponse:
    """
    **Tool: export_step**

    Export shapes from the active document as a STEP (.step / .stp) file.

    STEP is an ISO standard 3D format compatible with virtually all CAD software
    (SolidWorks, Fusion 360, AutoCAD, CATIA, etc.).

    **Inputs**
    - `output_path`: Absolute path for the output file. Directory must exist.
      Example: `C:/Users/me/models/my_part.step`
    - `shape_name` (recommended): export only this shape. Omitting it exports ALL
      document shapes, including leftover construction solids — which makes
      validate_step report solid_count > 1.

    **Returns**
    - `output_path`: Confirmed file path written
    - `shape_count`: Number of shapes exported
    - `shape_names`: Names of exported shapes
    - `file_size_bytes`: Size of the written file
    """
    _freecad_guard()
    session = get_session()

    try:
        result = session.export_step(req.output_path, req.shape_name)
        return _ok(
            message=f"Model exported to '{result['output_path']}' ({result['file_size_bytes']} bytes).",
            data=result,
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("export_step failed")
        return _err(f"Unexpected error during export: {exc}")


class _ExportStlRequest(BaseModel):
    output_path: str

@app.post("/model/export_stl", response_model=ToolResponse, tags=["Export"])
async def export_stl(req: _ExportStlRequest) -> ToolResponse:
    """Export all shapes as a binary STL file for browser preview."""
    _freecad_guard()
    session = get_session()
    try:
        result = session.export_stl(req.output_path)
        return _ok(message=f"STL exported to '{result['output_path']}'.", data=result)
    except Exception as exc:
        return _err(str(exc))


@app.post("/model/export_assembly", response_model=ToolResponse, tags=["Export"])
async def export_assembly(req: ExportAssemblyRequest) -> ToolResponse:
    """
    **Tool: export_assembly**

    Combine multiple STEP files into a single multi-body STEP assembly file.

    Each part is imported, optionally translated to its assembly position, and
    exported together as one STEP file. CAD viewers (FreeCAD, Fusion 360, STEP
    viewers) display each body as an individually named, selectable component in
    the assembly tree.

    Use this after building individual parts with `export_step` to produce a
    single file that shows how all parts fit together.

    **Inputs**
    - `parts`: List of parts, each with:
      - `step_path`: Path to an existing .step file
      - `name`: Label shown in the assembly tree
      - `x`, `y`, `z`: Optional translation offset in mm (default 0)
    - `output_path`: Absolute path for the assembly STEP file

    **Example — hub assembly with axle centred in cage:**
    ```json
    {
      "parts": [
        {"step_path": ".../hub_cage.step",         "name": "Hub_Cage"},
        {"step_path": ".../hub_axle.step",         "name": "Axle"},
        {"step_path": ".../hub_bearing_cover.step","name": "Bearing_Cover_Left",  "z": -67.5},
        {"step_path": ".../hub_bearing_cover.step","name": "Bearing_Cover_Right", "z":  59.5}
      ],
      "output_path": ".../hub_assembly.step"
    }
    ```
    """
    _freecad_guard()
    session = get_session()

    try:
        result = session.export_assembly(
            [p.model_dump() for p in req.parts],
            req.output_path,
        )
        return _ok(
            message=(
                f"Assembly '{result['output_path'].split('/')[-1].split(chr(92))[-1]}' exported: "
                f"{result['part_count']} parts, {result['file_size_bytes']:,} bytes."
            ),
            data=result,
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("export_assembly failed")
        return _err(f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Tool 6 — linear_pattern
# ---------------------------------------------------------------------------

@app.post("/operations/linear_pattern", response_model=ToolResponse, tags=["Operations"])
async def linear_pattern(req: LinearPatternRequest) -> ToolResponse:
    """
    **Tool: linear_pattern**

    Create a repeating linear array of a shape, fused into one solid body.
    Use this to build bolt hole tool bodies, rib arrays, or any repeated geometry.

    **Inputs**
    - `source_shape`: shape to repeat (consumed)
    - `direction`: `x`, `y`, or `z` — axis along which copies are placed
    - `count`: total number of instances (min 2)
    - `spacing`: center-to-center distance between instances (mm)
    - `result_name`: name for the fused result

    **Example** — create a row of 5 holes spaced 20mm apart, then boolean_cut from plate:
    ```
    add_cylinder(name="hole_template", radius=4, height=10)
    linear_pattern(source_shape="hole_template", direction="x", count=5, spacing=20,
                   result_name="hole_row")
    boolean_cut(target_shape="plate", tool_shape="hole_row", result_name="plate")
    ```
    """
    _freecad_guard()
    session = get_session()
    try:
        session.linear_pattern(
            source_name=req.source_shape,
            direction=req.direction,
            count=req.count,
            spacing=req.spacing,
            result_name=req.result_name,
        )
        info = session.get_shape_info(req.result_name)
        return _ok(
            message=f"Linear pattern: {req.count}× '{req.source_shape}' every {req.spacing}mm along {req.direction} → '{req.result_name}'.",
            data=ShapeInfo(**info).model_dump(),
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("linear_pattern failed")
        return _err(f"Unexpected error in linear_pattern: {exc}")


# ---------------------------------------------------------------------------
# Tool 7 — boolean_union
# ---------------------------------------------------------------------------

@app.post("/operations/boolean_union", response_model=ToolResponse, tags=["Operations"])
async def boolean_union(req: BooleanUnionRequest) -> ToolResponse:
    """
    **Tool: boolean_union**

    Fuse two shapes into a single unified solid. Both input shapes are consumed
    and replaced by `result_name`. Internal faces at the junction are removed so
    the result is a clean manifold solid.

    Use this to combine a boss onto a plate, attach a flange to a pipe, or join
    any two bodies that should become one part.

    **Inputs**
    - `shape_a`: first shape to merge
    - `shape_b`: second shape to merge
    - `result_name`: name for the fused result (may equal shape_a)

    **Important**
    - The shapes must touch or overlap. A gap between them produces a non-manifold
      result (technically valid geometry but not manufacturable as a single part).
    - To union more than two shapes, chain calls: union A+B → AB, then union AB+C → ABC.

    **Returns**
    - Shape metadata for the resulting unified solid
    """
    _freecad_guard()
    session = get_session()
    try:
        session.boolean_union(req.shape_a, req.shape_b, req.result_name)
        info = session.get_shape_info(req.result_name)
        return _ok(
            message=f"Unified '{req.shape_a}' + '{req.shape_b}' → '{req.result_name}'.",
            data=ShapeInfo(**info).model_dump(),
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("boolean_union failed")
        return _err(f"Unexpected error during union: {exc}")


# ---------------------------------------------------------------------------
# Tool 7 — boolean_cut
# ---------------------------------------------------------------------------

@app.post("/operations/boolean_cut", response_model=ToolResponse, tags=["Operations"])
async def boolean_cut(req: BooleanCutRequest) -> ToolResponse:
    """
    **Tool: boolean_cut**

    Subtract one shape (the tool) from another (the target), creating a void
    where the tool overlapped. Both input shapes are consumed; the result is a
    new shape named `result_name`.

    Use this to create pockets, slots, and arbitrary cutouts. For cylindrical
    holes specifically, prefer `make_hole` which is simpler.

    **Inputs**
    - `target_shape`: name of the body to cut FROM
    - `tool_shape`: name of the body to cut WITH (becomes the void)
    - `result_name`: name for the resulting shape (may equal target_shape)

    **Returns**
    - Shape metadata for the resulting cut body
    - Volume reflects material removed

    **Common mistakes**
    - Tool shape must overlap the target shape or the result will be unchanged
    - Both shapes must exist in the active document
    """
    _freecad_guard()
    session = get_session()
    try:
        meta = session.boolean_cut(req.target_shape, req.tool_shape, req.result_name)
        info = session.get_shape_info(req.result_name)
        warnings: list[str] = []
        volume_removed = meta.dimensions.get("volume_removed_mm3", 0.0)
        volume_before = meta.dimensions.get("volume_before_mm3", 0.0)
        if volume_before > 0 and volume_removed < 0.01 * volume_before:
            warnings.append(
                f"Volume removed ({volume_removed:.3f} mm³) is less than 1% of the target "
                f"({volume_before:.3f} mm³). The tool shape may not overlap the target, "
                "or only touched it tangentially. Verify joint overlap ≥ 1 mm."
            )
        resp = _ok(
            message=f"Cut '{req.target_shape}' with '{req.tool_shape}' → '{req.result_name}' "
                    f"(removed {volume_removed:.1f} mm³).",
            data=ShapeInfo(**info).model_dump(),
        )
        resp.warnings.extend(warnings)
        return resp
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("boolean_cut failed")
        return _err(f"Unexpected error during boolean cut: {exc}")


# ---------------------------------------------------------------------------
# Tool 7 — make_hole
# ---------------------------------------------------------------------------

@app.post("/operations/make_hole", response_model=ToolResponse, tags=["Operations"])
async def make_hole(req: MakeHoleRequest) -> ToolResponse:
    """
    **Tool: make_hole**

    Drill a cylindrical through-hole (or blind hole) into an existing solid shape.
    This is the primary tool for adding screw holes, bolt holes, and cable
    passthroughs to a part.

    The hole is always oriented along the +Z axis. The hole center is at (x, y)
    and starts at height z.

    **Inputs**
    - `target_shape`: name of the solid to drill into
    - `diameter`: hole diameter in mm
    - `x`, `y`: center of the hole on the entry face (mm)
    - `z`: Z height where the hole starts (mm, default 0)
    - `depth`: hole depth in mm. Omit or pass null for a through-hole.
    - `result_name`: name for the result (set equal to target_shape to update in place)

    **Returns**
    - Shape metadata showing updated volume and hole parameters

    **Example workflow**
    ```
    make_hole(target_shape="plate", diameter=8, x=10, y=10, result_name="plate")
    make_hole(target_shape="plate", diameter=8, x=70, y=10, result_name="plate")
    ```
    Each call replaces "plate" with a new version that has one more hole.
    """
    _freecad_guard()
    session = get_session()
    try:
        session.make_hole(
            target_name=req.target_shape,
            diameter=req.diameter,
            x=req.x,
            y=req.y,
            z=req.z,
            result_name=req.result_name,
            depth=req.depth,
            axis=req.axis,
        )
        info = session.get_shape_info(req.result_name)
        depth_desc = f"depth={req.depth}mm" if req.depth is not None else "through"
        return _ok(
            message=f"Hole dia={req.diameter}mm ({depth_desc}) drilled at ({req.x},{req.y}) into '{req.target_shape}' → '{req.result_name}'.",
            data=ShapeInfo(**info).model_dump(),
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("make_hole failed")
        return _err(f"Unexpected error making hole: {exc}")


# ---------------------------------------------------------------------------
# Tool 8 — fillet_edges
# ---------------------------------------------------------------------------

@app.post("/operations/fillet_edges", response_model=ToolResponse, tags=["Operations"])
async def fillet_edges(req: FilletEdgesRequest) -> ToolResponse:
    """
    **Tool: fillet_edges**

    Apply a smooth radius fillet to selected edges of a shape. Commonly used
    to round the vertical corners of a plate or block for aesthetics and to
    eliminate stress concentrations.

    The `edge_selector` controls which edges are rounded:
    - `all_vertical` — edges parallel to Z axis (the four vertical corners of a box)
    - `all` — every edge on the shape
    - `top` — edges lying on the top face
    - `bottom` — edges lying on the bottom face

    **Inputs**
    - `target_shape`: name of the shape to fillet
    - `radius`: fillet radius in mm (must be smaller than adjacent wall thickness)
    - `edge_selector`: which edges to fillet (default: `all_vertical`)
    - `result_name`: name for the result (may equal target_shape)

    **Returns**
    - Shape metadata including how many edges were filleted

    **If the operation fails**
    - Try a smaller radius
    - Switch from `all` to `all_vertical` to target only corner edges
    """
    _freecad_guard()
    session = get_session()
    try:
        session.fillet_edges(
            target_name=req.target_shape,
            radius=req.radius,
            edge_selector=req.edge_selector,
            result_name=req.result_name,
        )
        info = session.get_shape_info(req.result_name)
        return _ok(
            message=f"Fillet r={req.radius}mm applied to '{req.edge_selector}' edges of '{req.target_shape}' → '{req.result_name}'.",
            data=ShapeInfo(**info).model_dump(),
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("fillet_edges failed")
        return _err(f"Unexpected error during fillet: {exc}")


# ---------------------------------------------------------------------------
# Tool — chamfer_edges
# ---------------------------------------------------------------------------

@app.post("/operations/chamfer_edges", response_model=ToolResponse, tags=["Operations"])
async def chamfer_edges(req: ChamferEdgesRequest) -> ToolResponse:
    """
    **Tool: chamfer_edges**

    Apply a flat 45° chamfer (bevelled edge break) to selected edges.
    Use for deburring sharp edges on manufactured parts, or to create the
    lead-in chamfer on screw heads and fasteners.

    Same `edge_selector` options as `fillet_edges`:
    - `top` (default) — edges on the topmost face
    - `all_vertical` — Z-parallel corner edges
    - `all` — every edge
    - `bottom` — edges on the bottom face

    **Inputs**
    - `target_shape`: shape to chamfer
    - `size`: chamfer distance in mm
    - `edge_selector`: which edges to chamfer (default: `top`)
    - `result_name`: result name (may equal target_shape)
    """
    _freecad_guard()
    session = get_session()
    try:
        session.chamfer_edges(
            target_name=req.target_shape,
            size=req.size,
            edge_selector=req.edge_selector,
            result_name=req.result_name,
        )
        info = session.get_shape_info(req.result_name)
        return _ok(
            message=f"Chamfer size={req.size}mm applied to '{req.edge_selector}' edges of '{req.target_shape}' → '{req.result_name}'.",
            data=ShapeInfo(**info).model_dump(),
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("chamfer_edges failed")
        return _err(f"Unexpected error during chamfer: {exc}")


# ---------------------------------------------------------------------------
# Document status (bonus utility endpoint)
# ---------------------------------------------------------------------------

@app.get("/document/status", response_model=ToolResponse, tags=["Document"])
async def document_status() -> ToolResponse:
    """
    Return the current document state: name, session ID, and all shapes.
    Useful for agents to verify state before proceeding.
    """
    session = get_session()
    if not session.is_active:
        return _ok(
            message="No active document.",
            data={"active": False},
        )
    state = session.state
    return _ok(
        message=f"Document '{state.document_name}' is active with {state.shape_count} shape(s).",
        data={
            "active": True,
            "session_id": state.session_id,
            "document_name": state.document_name,
            "created_at": state.created_at.isoformat(),
            "shape_count": state.shape_count,
            "shapes": [
                {
                    "name": s.name,
                    "type": s.shape_type,
                    "position": s.position,
                    "dimensions": s.dimensions,
                }
                for s in state.shapes.values()
            ],
        },
    )


# ---------------------------------------------------------------------------
# Wire / sweep API
# ---------------------------------------------------------------------------

@app.post("/paths/create_arc", response_model=ToolResponse, tags=["Paths"])
async def create_arc_path(req: CreateArcPathRequest) -> ToolResponse:
    """
    Define a 3-point arc as a sweep spine. The arc passes through start → mid → end.
    Store it under the given name for use with POST /operations/sweep.
    """
    _freecad_guard()
    session = get_session()
    try:
        meta = session.create_arc_path(req.name, req.start, req.mid, req.end)
        return _ok(
            message=f"Arc path '{req.name}' created (length={meta.dimensions['length_mm']:.1f}mm).",
            data={"name": meta.name, "wire_type": meta.wire_type, **meta.dimensions},
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("create_arc_path failed")
        return _err(f"Unexpected error: {exc}")


@app.post("/shapes/revolve_profile", response_model=ToolResponse, tags=["Shapes"])
async def revolve_profile(req: RevolveProfileRequest) -> ToolResponse:
    """
    **Tool: revolve_profile**


    Create a solid of revolution by revolving a 2D cross-section profile 360° around
    the Z axis. This is the equivalent of FreeCAD's Sketch → Revolution operation.

    Use this for any rotationally symmetric part: axles, shafts, hub shells, bearing
    cups, flanges, pulleys, wheels, nozzles — anything with circular cross-sections
    that vary along a central axis.

    The profile is defined as a list of [radius, z_position] pairs tracing the outer
    boundary of the cross-section from one end to the other. The tool automatically
    closes the profile back along the Z axis (r=0), so you only need to describe
    the outer surface.

    Example — stepped axle shaft:
      profile = [[4.5,0],[4.5,25],[5.5,25],[5.5,145],[4.5,145],[4.5,170]]
      This creates a shaft: 9mm dia ends (z=0–25, z=145–170), 11mm dia center.

    Example — hub flange profile:
      profile = [[14,-67.5],[20,-60],[28,-45],[28,-40],[18,-40],[18,40],
                 [28,40],[28,45],[20,60],[14,67.5]]
      Sharp corners at radius steps; use fillet_edges afterward to round them.
    """
    _freecad_guard()
    session = get_session()
    try:
        meta = session.revolve_profile(req.name, req.profile, req.x, req.y, req.z)
        return _ok(
            message=(
                f"Revolution '{req.name}' created: {len(req.profile)} profile points, "
                f"r_max={meta.dimensions['r_max']:.1f}mm, "
                f"vol={meta.dimensions['volume_mm3']:.1f}mm³."
            ),
            data={"name": meta.name, **meta.dimensions},
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("revolve_profile failed")
        return _err(f"Unexpected error: {exc}")


@app.post("/operations/polar_pattern", response_model=ToolResponse, tags=["Operations"])
async def polar_pattern(req: PolarPatternRequest) -> ToolResponse:
    """
    **Tool: polar_pattern**

    Create a circular (polar) array by rotating a shape N times at equal angular
    spacing (360/N degrees) around the specified axis through the origin, then
    unioning all instances into one solid. The source shape is consumed.

    Primary use case — circular hole arrays:
      1. Create one cutting cylinder at the correct radial offset (e.g. r=22mm for spoke holes)
      2. Call polar_pattern(source=cylinder, count=28, axis="z") → union of all 28 cutters
      3. boolean_cut(hub_cage, 28_cutters) → hub with all spoke holes in one operation

    This replaces 28 individual make_hole calls with 2 operations.
    """
    _freecad_guard()
    session = get_session()
    try:
        meta = session.polar_pattern(req.source_shape, req.count, req.axis, req.result_name)
        return _ok(
            message=(
                f"Polar pattern '{req.result_name}': {req.count} instances at "
                f"{meta.dimensions['angle_step_deg']:.2f}° spacing, "
                f"vol={meta.dimensions['volume_mm3']:.1f}mm³."
            ),
            data={"name": meta.name, **meta.dimensions},
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("polar_pattern failed")
        return _err(f"Unexpected error: {exc}")


@app.post("/shapes/extrude_polygon", response_model=ToolResponse, tags=["Shapes"])
async def extrude_polygon(req: ExtrudePolygonRequest) -> ToolResponse:
    """
    **Tool: extrude_polygon**

    Extrude a 2D polygon (defined as a list of [a, b] point pairs) into a solid prism.
    This is the equivalent of FreeCAD's Sketch → Pad operation for arbitrary polygons.

    Use this to create non-rectangular prismatic shapes — trapezoids, L-shapes,
    T-sections, hex prisms, or any custom 2D outline.

    Point conventions by axis:
    - axis="z" (default): points are [x, y] in the XY plane, extruded upward in +Z
    - axis="x": points are [y, z] in the YZ plane, extruded in +X
    - axis="y": points are [x, z] in the XZ plane, extruded in +Y

    The (x, y, z) parameters offset the entire prism from the origin.
    """
    _freecad_guard()
    session = get_session()
    try:
        meta = session.extrude_polygon(
            req.name, req.points, req.height, req.axis, req.x, req.y, req.z
        )
        return _ok(
            message=(
                f"Polygon prism '{req.name}' created: {len(req.points)} points, "
                f"h={req.height}mm, vol={meta.dimensions['volume_mm3']:.1f}mm³."
            ),
            data={"name": meta.name, **meta.dimensions},
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("extrude_polygon failed")
        return _err(f"Unexpected error: {exc}")


@app.post("/profiles/rect", response_model=ToolResponse, tags=["Profiles"])
async def create_rect_profile(req: CreateRectProfileRequest) -> ToolResponse:
    """
    Define a closed rectangular cross-section profile for sweeping.
    Width = Y direction, Height = Z direction. Placed at origin, in the YZ plane.
    Store it under the given name for use with POST /operations/sweep.
    """
    _freecad_guard()
    session = get_session()
    try:
        meta = session.create_rect_profile(req.name, req.width, req.height, req.corner_radius)
        return _ok(
            message=f"Rect profile '{req.name}' created ({req.width}×{req.height}mm, r={req.corner_radius}mm).",
            data={"name": meta.name, "wire_type": meta.wire_type, **meta.dimensions},
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("create_rect_profile failed")
        return _err(f"Unexpected error: {exc}")


@app.post("/operations/sweep", response_model=ToolResponse, tags=["Operations"])
async def sweep_profile(req: SweepRequest) -> ToolResponse:
    """
    Sweep a closed profile wire along a path wire to produce a solid.
    Both wires must have been created first via /paths/* and /profiles/*.
    """
    _freecad_guard()
    session = get_session()
    try:
        meta = session.sweep(req.profile_name, req.path_name, req.result_name)
        info = {
            "name": meta.name,
            "shape_type": meta.shape_type,
            "volume_mm3": meta.dimensions["volume_mm3"],
            "profile": meta.dimensions["profile"],
            "path": meta.dimensions["path"],
        }
        return _ok(
            message=f"Sweep '{req.result_name}' created (vol={meta.dimensions['volume_mm3']:.1f}mm³).",
            data=info,
        )
    except RuntimeError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("sweep failed")
        return _err(f"Unexpected error during sweep: {exc}")


# ---------------------------------------------------------------------------
# Solid validation
# ---------------------------------------------------------------------------

@app.get("/model/validate/{shape_name}", response_model=ToolResponse, tags=["Validation"])
async def validate_solid(shape_name: str) -> ToolResponse:
    """
    **Tool: validate_solid**

    Run a full BRep inspection on a named shape currently in the document.

    Checks performed:
    - FreeCAD `isValid()` — basic topology
    - Shape type (must be Solid or Compound of Solids)
    - Volume > 0 and surface area > 0
    - Free edges (watertight check — must be 0)
    - Non-manifold edges (must be 0 for slicers/CAM)
    - Degenerate faces and edges
    - Shell count per solid
    - BRep checker (self-intersections, bad curves/surfaces)

    Returns `is_clean: true` only if ALL checks pass.
    """
    _freecad_guard()
    try:
        session = get_session()
        result = session.validate_solid(shape_name)
        ok = result["is_clean"]
        return ToolResponse(
            success=True,
            message=result["summary"],
            data=result,
            warnings=result["warnings"],
            errors=result["issues"] if not ok else [],
        )
    except RuntimeError as exc:
        return ToolResponse(success=False, message=str(exc), errors=[str(exc)])
    except Exception as exc:
        logger.exception("validate_solid failed")
        import traceback
        return ToolResponse(success=False, message="Unexpected error during validation.",
                            errors=[traceback.format_exc()])


@app.post("/model/validate_step", response_model=ToolResponse, tags=["Validation"])
async def validate_step(req: ValidateStepRequest) -> ToolResponse:
    """
    **Tool: validate_step**

    Re-import a STEP file from disk and run a full BRep inspection on the
    imported shape. This validates the file itself, not just the in-memory geometry —
    confirming that what was written to disk is a clean, uploadable solid.

    Use this after `export_step` to confirm the file is ready for Protolabs or a slicer.
    """
    _freecad_guard()
    try:
        session = get_session()
        result = session.validate_step_file(req.step_path)
        ok = result["is_clean"]
        return ToolResponse(
            success=True,
            message=result["summary"],
            data=result,
            warnings=result["warnings"],
            errors=result["issues"] if not ok else [],
        )
    except RuntimeError as exc:
        return ToolResponse(success=False, message=str(exc), errors=[str(exc)])
    except Exception as exc:
        logger.exception("validate_step failed")
        import traceback
        return ToolResponse(success=False, message="Unexpected error during STEP validation.",
                            errors=[traceback.format_exc()])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


# ===========================================================================
# FEM — Finite Element Analysis endpoints
# ===========================================================================

@app.post("/fem/create_analysis", response_model=ToolResponse, tags=["FEM"])
async def fem_create_analysis(req: FEMCreateAnalysisRequest) -> ToolResponse:
    """
    **Tool: fem/create_analysis**

    Create a FEM analysis container linked to a named solid shape.
    This must be called first before any other /fem/* tool.

    **Returns** analysis_name, shape_name, shape_volume_mm3.
    """
    _freecad_guard()
    async with get_session_lock():
        session = get_session()
        try:
            data = session.fem_create_analysis(req.shape_name)
            return _ok(
                message=f"FEM analysis created for '{req.shape_name}'.",
                data=data,
            )
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("fem_create_analysis failed")
            return _err(f"Unexpected error: {exc}")


@app.post("/fem/mesh", response_model=ToolResponse, tags=["FEM"])
async def fem_mesh(req: FEMMeshRequest) -> ToolResponse:
    """
    **Tool: fem/mesh**

    Generate a Netgen tetrahedral mesh on the named shape.
    Requires /fem/create_analysis to be called first.

    - `max_cell_size`: largest element edge in mm (smaller = finer mesh, slower solve)
    - `second_order`: Tet10 elements give higher accuracy than Tet4

    **Returns** mesh_name, node_count, element_count.
    """
    _freecad_guard()
    async with get_session_lock():
        session = get_session()
        try:
            data = session.fem_mesh(req.shape_name, req.max_cell_size, req.second_order)
            return _ok(
                message=f"Mesh generated: {data['node_count']} nodes, "
                        f"{data['element_count']} elements ({data['element_type']}).",
                data=data,
            )
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("fem_mesh failed")
            return _err(f"Unexpected error during meshing: {exc}")


@app.post("/fem/material", response_model=ToolResponse, tags=["FEM"])
async def fem_material(req: FEMMaterialRequest) -> ToolResponse:
    """
    **Tool: fem/material**

    Assign a mechanical material to the FEM analysis.

    Built-in presets (pass these as material_name; override individual fields as needed):
    - Steel-1C22: E=210000 MPa, nu=0.3, rho=7872 kg/m³
    - Aluminium-2024: E=73100 MPa, nu=0.33, rho=2780 kg/m³

    **Returns** material_object name and confirmed properties.
    """
    _freecad_guard()
    async with get_session_lock():
        session = get_session()
        try:
            data = session.fem_material(
                req.material_name, req.youngs_modulus_mpa,
                req.poisson_ratio, req.density_kg_m3,
            )
            return _ok(
                message=f"Material '{req.material_name}' applied "
                        f"(E={req.youngs_modulus_mpa:.0f} MPa, nu={req.poisson_ratio}).",
                data=data,
            )
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("fem_material failed")
            return _err(f"Unexpected error: {exc}")


@app.post("/fem/constraint_fixed", response_model=ToolResponse, tags=["FEM"])
async def fem_constraint_fixed(req: FEMConstraintFixedRequest) -> ToolResponse:
    """
    **Tool: fem/constraint_fixed**

    Fix a face of the shape — zero displacement in all directions (clamped wall).

    `face_selector` chooses the face by bounding-box position:
    - `xmin` — face at the minimum X extreme (left end of beam)
    - `xmax` — face at the maximum X extreme (right end)
    - `ymin`, `ymax`, `zmin`, `zmax` — similarly for Y and Z

    **Returns** constraint_name, face_ref (e.g. "Face5"), face_area_mm2.
    """
    _freecad_guard()
    async with get_session_lock():
        session = get_session()
        try:
            data = session.fem_constraint_fixed(req.shape_name, req.face_selector)
            return _ok(
                message=f"Fixed constraint applied to '{req.face_selector}' face "
                        f"({data['face_ref']}, area={data['face_area_mm2']:.1f} mm²).",
                data=data,
            )
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("fem_constraint_fixed failed")
            return _err(f"Unexpected error: {exc}")


@app.post("/fem/force_load", response_model=ToolResponse, tags=["FEM"])
async def fem_force_load(req: FEMForceLoadRequest) -> ToolResponse:
    """
    **Tool: fem/force_load**

    Apply a distributed force to a face of the shape.

    - `face_selector`: which face (xmin|xmax|ymin|ymax|zmin|zmax)
    - `force_n`: total force in Newtons
    - `direction`: unit vector [x, y, z] — e.g. [0,0,-1] for downward (-Z)

    **Tutorial values**: face_selector="zmax", force_n=1000, direction=[0,0,-1]

    **Returns** constraint_name, face_ref, face_area_mm2, confirmed direction.
    """
    _freecad_guard()
    async with get_session_lock():
        session = get_session()
        try:
            data = session.fem_force_load(
                req.shape_name, req.face_selector,
                req.force_n, req.direction,
            )
            return _ok(
                message=f"Force load {req.force_n:.0f} N applied to '{req.face_selector}' "
                        f"face ({data['face_ref']}) in direction {data['direction']}.",
                data=data,
            )
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("fem_force_load failed")
            return _err(f"Unexpected error: {exc}")


@app.post("/fem/run_solver", response_model=ToolResponse, tags=["FEM"])
async def fem_run_solver(req: FEMRunSolverRequest) -> ToolResponse:
    """
    **Tool: fem/run_solver**

    Write the CalculiX input file (.inp) and run the solver.
    Requires create_analysis, mesh, material, constraint_fixed, and force_load.

    CalculiX must be installed (bundled with FreeCAD 1.1 at
    `C:\\Program Files\\FreeCAD 1.1\\bin\\ccx.exe`).

    **Returns** working_dir, inp_file, elapsed_seconds, results_name.
    This may take 10–120 seconds depending on mesh density.
    """
    _freecad_guard()
    async with get_session_lock():
        session = get_session()
        try:
            data = session.fem_run_solver(req.analysis_type, req.working_dir)
            return _ok(
                message=f"CalculiX solver finished in {data['elapsed_seconds']:.1f}s. "
                        f"Results: '{data['results_name']}'.",
                data=data,
            )
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("fem_run_solver failed")
            return _err(f"Unexpected error during solve: {exc}")


@app.post("/fem/get_results", response_model=ToolResponse, tags=["FEM"])
async def fem_get_results(req: FEMGetResultsRequest) -> ToolResponse:
    """
    **Tool: fem/get_results**

    Extract min/max statistics for a result quantity from the completed FEM analysis.

    Valid quantities:
    - `displacement_z` — vertical deflection (tutorial expects max ~ -356 mm)
    - `displacement_x`, `displacement_y`, `displacement_magnitude`
    - `von_mises_stress`, `principal_stress_1`, `principal_stress_2`, `principal_stress_3`
    - `temperature` (thermal analyses)

    **Returns** min_value, max_value, abs_max_value, node_count, unit.
    """
    _freecad_guard()
    async with get_session_lock():
        session = get_session()
        try:
            data = session.fem_get_results(req.quantity)
            return _ok(
                message=f"{req.quantity}: min={data['min_value']:.4f}, "
                        f"max={data['max_value']:.4f} {data['unit']} "
                        f"({data['node_count']} nodes).",
                data=data,
            )
        except RuntimeError as exc:
            return _err(str(exc))
        except Exception as exc:
            logger.exception("fem_get_results failed")
            return _err(f"Unexpected error reading results: {exc}")


# ---------------------------------------------------------------------------
# Elmer FEM endpoints  (no FreeCAD dependency — pure subprocess)
# ---------------------------------------------------------------------------

@app.get("/elmer/health", response_model=ToolResponse, tags=["Elmer"])
async def elmer_health() -> ToolResponse:
    """Check whether ElmerSolver.exe is reachable at its expected install path."""
    available = elmer.elmer_available()
    return _ok(
        message="Elmer is available." if available else "ElmerSolver.exe not found.",
        data={
            "elmer_available": available,
            "solver_path": str(elmer.ELMER_SOLVER),
        },
    )


@app.post("/elmer/setup_heat", response_model=ToolResponse, tags=["Elmer"])
async def elmer_setup_heat(req: ElmerSetupHeatRequest) -> ToolResponse:
    """
    **Tool: elmer/setup_heat**

    Prepare a steady-state heat equation case:
    1. Optionally copy mesh files from `mesh_source_dir` → `working_dir`.
    2. Write `case.sif` with the supplied material, body force, and boundary conditions.
    3. Write `ELMERSOLVER_STARTINFO`.

    After this call, run `/elmer/run_solver` to execute the simulation.

    **Boundary tag integers** must match Elmer mesh boundary tags (column 2 of `mesh.boundary`).
    For the Tutorial-1 pump geometry, bore-interior surfaces = tag 57.
    """
    try:
        working_dir = elmer.Path(req.working_dir)
        working_dir.mkdir(parents=True, exist_ok=True)

        # Copy mesh files if a source directory was given
        if req.mesh_source_dir:
            mesh_src = elmer.Path(req.mesh_source_dir)
            copied = []
            for f in mesh_src.glob("mesh.*"):
                dest = working_dir / f.name
                elmer.shutil.copy2(f, dest)
                copied.append(f.name)
        else:
            copied = []

        # Convert boundary conditions from pydantic models to plain dicts
        bcs = []
        for bc in req.boundary_conditions:
            d: dict = {"tags": bc.tags}
            if bc.temperature is not None:
                d["temperature"] = bc.temperature
            if bc.heat_flux is not None:
                d["heat_flux"] = bc.heat_flux
            bcs.append(d)

        mat = req.material
        sif_path = elmer.write_heat_sif(
            working_dir,
            heat_conductivity=mat.heat_conductivity,
            density=mat.density,
            heat_capacity=mat.heat_capacity,
            heat_source=req.heat_source,
            coordinate_scaling=req.coordinate_scaling,
            boundary_conditions=bcs,
            sif_name=req.sif_name,
        )
        elmer.write_startinfo(working_dir, req.sif_name)

        # List mesh files present
        mesh_files = [f.name for f in working_dir.glob("mesh.*")]

        return _ok(
            message=f"Heat case written to {sif_path}. "
                    f"{len(mesh_files)} mesh files present. "
                    f"Ready to run /elmer/run_solver.",
            data={
                "sif_path": str(sif_path),
                "working_dir": str(working_dir),
                "mesh_files_copied": copied,
                "mesh_files_present": mesh_files,
                "boundary_conditions_count": len(bcs),
                "coordinate_scaling": req.coordinate_scaling,
            },
        )
    except Exception as exc:
        logger.exception("elmer_setup_heat failed")
        return _err(f"Setup failed: {exc}")


@app.post("/elmer/run_solver", response_model=ToolResponse, tags=["Elmer"])
async def elmer_run_solver(req: ElmerRunRequest) -> ToolResponse:
    """
    **Tool: elmer/run_solver**

    Execute ElmerSolver in the working directory (must already contain a .sif
    file and mesh files — call `/elmer/setup_heat` first).

    Returns convergence status, Elmer result norm, elapsed time, and VTU paths.
    After this call, use `/elmer/get_results` to extract field statistics.
    """
    try:
        result = elmer.run_elmer(
            elmer.Path(req.working_dir),
            timeout_seconds=req.timeout_seconds,
        )
        if result["converged"]:
            msg = (
                f"ElmerSolver converged in {result['elapsed_seconds']:.1f}s. "
                f"Result norm = {result['result_norm']}."
            )
        else:
            msg = (
                f"ElmerSolver finished in {result['elapsed_seconds']:.1f}s but "
                f"convergence not confirmed. Check log_snippet."
            )
        return _ok(message=msg, data=result)
    except Exception as exc:
        logger.exception("elmer_run_solver failed")
        return _err(f"Solver failed: {exc}")


@app.post("/elmer/get_results", response_model=ToolResponse, tags=["Elmer"])
async def elmer_get_results(req: ElmerGetResultsRequest) -> ToolResponse:
    """
    **Tool: elmer/get_results**

    Parse the VTU result file produced by ElmerSolver and return field statistics:
    min, max, mean, and RMS norm for the requested scalar field.

    For a heat equation simulation the field name is `Temperature`.
    """
    try:
        stats = elmer.get_field_stats(elmer.Path(req.working_dir), req.field_name)
        return _ok(
            message=(
                f"{req.field_name}: min={stats['min_value']:.4f}, "
                f"max={stats['max_value']:.4f}, "
                f"mean={stats['mean_value']:.4f}, "
                f"rms_norm={stats['rms_norm']:.4f} "
                f"({stats['node_count']} nodes)."
            ),
            data=stats,
        )
    except Exception as exc:
        logger.exception("elmer_get_results failed")
        return _err(f"Failed to read results: {exc}")


# ---------------------------------------------------------------------------
# Elmer transient heat endpoints (Tutorial 3)
# ---------------------------------------------------------------------------

from models import (  # noqa: E402 — appended import
    ElmerTransientHeatSetupRequest,
    ElmerGetTransientResultsRequest,
)
import elmer_transient as _et
import shutil as _shutil


@app.post("/elmer/setup_transient_heat", response_model=ToolResponse, tags=["Elmer"])
async def t3_setup_transient_heat(req: ElmerTransientHeatSetupRequest) -> ToolResponse:
    """
    **Tool: elmer/setup_transient_heat**

    Write a transient heat-equation .sif file and ELMERSOLVER_STARTINFO into
    working_dir, optionally copying mesh files from mesh_source_dir.

    Supports constant and tabular (piecewise-linear) initial conditions, which
    are needed for geological / geothermal simulations where the initial
    temperature profile varies with depth.

    After this call, run the solver with `/elmer/run_solver` then fetch results
    with `/elmer/get_transient_results`.
    """
    try:
        work = elmer.Path(req.working_dir)
        work.mkdir(parents=True, exist_ok=True)

        # Copy mesh files if requested
        if req.mesh_source_dir:
            src = elmer.Path(req.mesh_source_dir)
            for f in src.glob("mesh.*"):
                _shutil.copy2(f, work / f.name)

        # Convert IC specs from Pydantic models to plain dicts
        ic_dicts = []
        for ic in req.initial_conditions:
            d: dict = {
                "body_indices": ic.body_indices,
                "type": ic.type,
            }
            if ic.type == "constant":
                d["value"] = ic.value if ic.value is not None else 293.0
            elif ic.type == "tabular":
                d["variable"] = ic.variable or "coordinate 2"
                d["table"] = [tuple(row) for row in (ic.table or [])]
            ic_dicts.append(d)

        # Convert BC specs
        bc_dicts = [
            {
                "tags": bc.tags,
                **({"temperature": bc.temperature} if bc.temperature is not None else {}),
                **({"heat_flux": bc.heat_flux} if bc.heat_flux is not None else {}),
            }
            for bc in req.boundary_conditions
        ]

        mat = req.material
        sif_path = _et.write_transient_heat_sif(
            work,
            heat_conductivity=mat.heat_conductivity,
            density=mat.density,
            heat_capacity=mat.heat_capacity,
            timestep_intervals=req.timestep_intervals,
            timestep_size_expr=req.timestep_size_expr,
            bdf_order=req.bdf_order,
            output_intervals=req.output_intervals,
            initial_conditions=ic_dicts,
            boundary_conditions=bc_dicts,
            heat_source=req.heat_source,
            coordinate_scaling=req.coordinate_scaling,
            sif_name=req.sif_name,
        )
        _et.write_startinfo(work, req.sif_name)

        return _ok(
            message=(
                f"Transient heat .sif written to {sif_path}. "
                f"Timesteps: {req.timestep_intervals} × {req.timestep_size_expr} s. "
                f"BDF order: {req.bdf_order}. "
                f"Output every {req.output_intervals} steps."
            ),
            data={
                "sif_path": str(sif_path),
                "working_dir": str(work),
                "timestep_intervals": req.timestep_intervals,
                "timestep_size_expr": req.timestep_size_expr,
                "output_intervals": req.output_intervals,
                "ic_count": len(ic_dicts),
                "bc_count": len(bc_dicts),
            },
        )
    except Exception as exc:
        logger.exception("t3_setup_transient_heat failed")
        return _err(f"Failed to write transient SIF: {exc}")


@app.post("/elmer/get_transient_results", response_model=ToolResponse, tags=["Elmer"])
async def t3_get_transient_results(req: ElmerGetTransientResultsRequest) -> ToolResponse:
    """
    **Tool: elmer/get_transient_results**

    Parse ALL .vtu files produced by a transient ElmerSolver run and return
    time-series statistics for the requested field (default: Temperature).

    Returns per-step min/max/mean values plus final-step aggregates.
    Use this instead of `/elmer/get_results` when the simulation is transient
    (multiple VTU files, one per output interval).
    """
    try:
        stats = _et.get_all_vtu_stats(
            elmer.Path(req.working_dir),
            field_name=req.field_name,
        )
        return _ok(
            message=(
                f"{req.field_name} over {stats['vtu_count']} VTU files: "
                f"final min={stats['final_min']:.2f}, "
                f"max={stats['final_max']:.2f}, "
                f"mean={stats['final_mean']:.2f}."
            ),
            data=stats,
        )
    except Exception as exc:
        logger.exception("t3_get_transient_results failed")
        return _err(f"Failed to read transient results: {exc}")


# ---------------------------------------------------------------------------
# Passive elements endpoint (Tutorial 5: Active and Passive Elements)
# ---------------------------------------------------------------------------

from models import (  # noqa: E402 — appended import
    ElmerPassiveElementsRequest,
)
import elmer_passive as _ep
import os as _os
import subprocess as _subprocess
from pathlib import Path as _Path


@app.post("/elmer/setup_passive_elements", response_model=ToolResponse, tags=["Elmer"])
async def passive_setup_passive_elements(req: ElmerPassiveElementsRequest) -> ToolResponse:
    """
    **Tool: elmer/setup_passive_elements**

    Set up (and optionally run) a transient heat simulation with Elmer's
    passive element feature.  Passive elements are excluded from the FEM
    assembly until a time condition activates them, enabling simulation of
    geometry that comes online mid-simulation (e.g. connectors activating at t=5s).

    Workflow:
    1. Writes `case.sif` into `working_dir` using the passive-element template.
    2. Writes `ELMERSOLVER_STARTINFO` so ElmerSolver picks up the right SIF.
    3. If `run_solver=true`, runs ElmerSolver and returns per-timestep temperature
       statistics from the resulting VTU files.

    Returns `data.sif_path` always.  If `run_solver=true`, also returns
    `data.converged`, `data.timestep_stats`, and `data.final_min/max/mean`.
    """
    import elmer_solver as _elmer
    if not _elmer.elmer_available():
        return _err("ElmerSolver not found. Check ELMER_HOME installation.")

    try:
        work = _Path(req.working_dir)
        if not work.exists():
            return _err(f"working_dir does not exist: {work}")

        # Convert Pydantic models to plain dicts for the writer
        bodies = [b.model_dump() for b in req.bodies]
        materials = [m.model_dump() for m in req.materials]
        body_forces = [bf.model_dump() for bf in req.body_forces]
        initial_conditions = [ic.model_dump() for ic in req.initial_conditions]
        boundary_conditions = [bc.model_dump() for bc in req.boundary_conditions]

        sif_path = _ep.write_passive_elements_sif(
            work,
            bodies=bodies,
            materials=materials,
            body_forces=body_forces,
            initial_conditions=initial_conditions,
            boundary_conditions=boundary_conditions,
            timestep_intervals=req.timestep_intervals,
            timestep_sizes=req.timestep_sizes,
            bdf_order=req.bdf_order,
            output_intervals=req.output_intervals,
            sif_name=req.sif_name,
        )

        # Write ELMERSOLVER_STARTINFO
        startinfo = work / "ELMERSOLVER_STARTINFO"
        startinfo.write_text(f"{req.sif_name}\n1\n")

        result_data: dict = {"sif_path": str(sif_path)}

        if not req.run_solver:
            return ToolResponse(
                success=True,
                message=f"SIF written to {sif_path}. Set run_solver=true to execute.",
                data=result_data,
            )

        # Run ElmerSolver
        env = _os.environ.copy()
        env["ELMER_HOME"] = str(_elmer.ELMER_BIN.parent)
        proc = _subprocess.run(
            [str(_elmer.ELMER_SOLVER)],
            cwd=str(work),
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        converged = "ALL DONE" in proc.stdout
        result_data["converged"] = converged
        result_data["solver_exit_code"] = proc.returncode

        # Parse VTU files
        vtu_files = sorted(work.glob("*.vtu"))
        timestep_stats = []
        for vtu in vtu_files:
            try:
                vals = _elmer._parse_vtu_field(vtu, "Temperature")
                timestep_stats.append({
                    "file": vtu.name,
                    "min": round(min(vals), 4),
                    "max": round(max(vals), 4),
                    "mean": round(sum(vals) / len(vals), 4),
                })
            except Exception as vtu_exc:
                timestep_stats.append({"file": vtu.name, "error": str(vtu_exc)})

        result_data["timestep_stats"] = timestep_stats
        result_data["vtu_count"] = len(vtu_files)
        if timestep_stats and "min" in timestep_stats[-1]:
            last = timestep_stats[-1]
            result_data["final_min"] = last["min"]
            result_data["final_max"] = last["max"]
            result_data["final_mean"] = last["mean"]

        warnings = []
        if not converged:
            warnings.append("ElmerSolver did not print 'ALL DONE' — check solver logs.")

        return ToolResponse(
            success=True,
            message=(
                f"Passive elements simulation {'converged' if converged else 'FAILED'}. "
                f"{len(vtu_files)} timesteps parsed."
            ),
            data=result_data,
            warnings=warnings,
        )

    except Exception as exc:
        logger.exception("passive_setup_passive_elements failed")
        return _err(f"Failed to run passive elements simulation: {exc}")


# ---------------------------------------------------------------------------
# Elmer — Radiation Heat Transfer (Tutorial 4 pattern)
# ---------------------------------------------------------------------------

@app.post("/elmer/setup_radiation_heat", response_model=ToolResponse, tags=["Elmer FEM"])
async def radiation_setup_radiation_heat(req: ElmerSetupRadiationHeatRequest) -> ToolResponse:
    """
    **Tool: setup_radiation_heat**

    Set up and optionally run a 2-solver Elmer FEM radiation heat transfer case.

    Implements the Elmer Tutorial 4 pattern: axi-symmetric (or Cartesian) steady-state
    heat conduction with diffuse-gray radiation between surfaces, using the HeatSolve
    solver with built-in radiation factor computation via the ViewFactors executable.

    The Elmer bin directory is automatically added to PATH so ViewFactors.exe is found.

    **Workflow**
    1. Copy mesh files from mesh_source_dir into working_dir (if provided).
    2. Write case.sif with the specified bodies, materials, body forces, ICs, and BCs.
    3. Optionally run ElmerSolver and return field statistics.

    **Boundary condition format**
    - Dirichlet: `{"name": "Wall", "tags": [3], "temperature": 100.0}`
    - Radiation: `{"name": "Inner", "tags": [1], "radiation": "Diffuse Gray",
                    "emissivity": 0.6, "radiation_target_body": -1}`

    **Tutorial 4 example** (concentric cylinders, axi-symmetric):
    - Body 1 (inner, conductivity=10): radiation BC emissivity=0.6
    - Body 2 (outer, conductivity=1): radiation BC emissivity=0.1
    - Exterior: Dirichlet T=100 K
    - Expected max T ≈ 565.7 K

    **Returns**
    - sif_path, converged, result_norm, elapsed_seconds, temperature stats (min/max/mean)
    """
    import shutil as _shutil
    import os as _os
    from pathlib import Path as _P

    try:
        work = _P(req.working_dir)
        work.mkdir(parents=True, exist_ok=True)

        # Copy mesh files if requested
        if req.mesh_source_dir:
            src = _P(req.mesh_source_dir)
            for f in src.glob("mesh.*"):
                _shutil.copy2(f, work / f.name)

        # Build argument dicts from Pydantic models
        bodies = [
            {
                "target_body": b.target_body,
                "material_idx": b.material_idx,
                "body_force_idx": b.body_force_idx,
                "ic_idx": b.ic_idx,
            }
            for b in req.bodies
        ]
        materials = [
            {
                "name": m.name,
                "density": m.density,
                "heat_capacity": m.heat_capacity,
                "heat_conductivity": m.heat_conductivity,
            }
            for m in req.materials
        ]
        body_forces = [
            {"name": bf.name, "heat_source": bf.heat_source}
            for bf in req.body_forces
        ]
        initial_conditions = [
            {"name": ic.name, "temperature": ic.temperature}
            for ic in req.initial_conditions
        ]
        boundary_conditions = []
        for bc in req.boundary_conditions:
            d: dict = {"name": bc.name, "tags": bc.tags}
            if bc.temperature is not None:
                d["temperature"] = bc.temperature
            if bc.radiation is not None:
                d["radiation"] = bc.radiation
                d["emissivity"] = bc.emissivity
                d["radiation_target_body"] = bc.radiation_target_body
            boundary_conditions.append(d)

        sif_path = elmer_rad.write_radiation_heat_sif(
            work,
            coordinate_system=req.coordinate_system,
            bodies=bodies,
            materials=materials,
            body_forces=body_forces,
            initial_conditions=initial_conditions,
            boundary_conditions=boundary_conditions,
            steady_state_max_iter=req.steady_state_max_iter,
            nonlinear_max_iter=req.nonlinear_max_iter,
            nonlinear_tolerance=req.nonlinear_tolerance,
            sif_name=req.sif_name,
        )

        result_data: dict = {"sif_path": str(sif_path)}

        if not req.run_solver:
            return _ok(
                message=f"Radiation heat SIF written to {sif_path}. Solver not started.",
                data=result_data,
            )

        # Ensure ViewFactors.exe is on PATH
        elmer_bin = str(elmer.ELMER_BIN)
        env = _os.environ.copy()
        env["ELMER_HOME"] = str(elmer.ELMER_BIN.parent)
        existing_path = env.get("PATH", "")
        if elmer_bin not in existing_path:
            env["PATH"] = elmer_bin + _os.pathsep + existing_path

        elmer.write_startinfo(work, req.sif_name)

        import subprocess as _sub, time as _time
        t0 = _time.time()
        proc = _sub.run(
            [str(elmer.ELMER_SOLVER)],
            cwd=str(work),
            capture_output=True,
            text=True,
            timeout=req.timeout_seconds,
            env=env,
        )
        elapsed = round(_time.time() - t0, 2)
        stdout = proc.stdout + proc.stderr
        converged = "ALL DONE" in stdout

        result_data.update({
            "converged": converged,
            "elapsed_seconds": elapsed,
            "return_code": proc.returncode,
            "log_snippet": stdout[-2000:],
        })

        if converged:
            try:
                stats = elmer.get_field_stats(work, "Temperature")
                result_data["temperature_min"] = stats["min_value"]
                result_data["temperature_max"] = stats["max_value"]
                result_data["temperature_mean"] = stats["mean_value"]
                result_data["result_norm"] = stats["rms_norm"]
            except Exception as stats_exc:
                result_data["stats_error"] = str(stats_exc)

        warnings = []
        if not converged:
            warnings.append("ElmerSolver did not print 'ALL DONE' — check log_snippet.")

        return _ok(
            message=(
                f"Radiation heat simulation {'converged' if converged else 'FAILED'} "
                f"in {elapsed}s. "
                + (f"Max T = {result_data.get('temperature_max', '?'):.2f} K" if converged else "")
            ),
            data=result_data,
            warnings=warnings,
        )

    except Exception as exc:
        logger.exception("radiation_setup_radiation_heat failed")
        return _err(f"Failed in setup_radiation_heat: {exc}")


# ---------------------------------------------------------------------------
# Elmer — mesh inspection
# ---------------------------------------------------------------------------

from models import ElmerInspectMeshRequest, ElmerElasticity2DRequest, ElmerElasticity3DRequest, ElmerPlateDeflectionRequest, ElmerPlateEigenmodesRequest, ElmerNonlinearElasticityRequest, ElmerElectrostatics2DRequest, ElmerElectrostatics3DRequest, ElmerAcousticsRequest, ElmerElectrostaticsFloatingRequest  # noqa: E402


@app.post("/elmer/inspect_mesh", response_model=ToolResponse, tags=["Elmer"])
async def elmer_inspect_mesh(req: ElmerInspectMeshRequest) -> ToolResponse:
    """
    **Tool: elmer/inspect_mesh**

    Parse Elmer mesh files and return boundary tag statistics: element count,
    node count, centroid, and bounding box for each tag.

    Use this to discover which boundary tags correspond to which surfaces before
    setting up boundary conditions. Essential for new meshes where tag assignments
    are not known in advance.

    **Returns** a list of tag info dicts, sorted by tag index.
    """
    try:
        tags = elmer.inspect_mesh_boundaries(
            elmer.Path(req.mesh_dir), max_tags=req.max_tags
        )
        return _ok(
            message=f"Found {len(tags)} boundary tags in {req.mesh_dir}.",
            data={"tags": tags, "tag_count": len(tags)},
        )
    except Exception as exc:
        logger.exception("elmer_inspect_mesh failed")
        return _err(f"Mesh inspection failed: {exc}")


@app.post("/elmer/setup_elasticity_2d")
def elmer_setup_elasticity_2d(req: ElmerElasticity2DRequest):
    """
    Tutorial 6: 2D linear elasticity for a loaded elastic beam.
    Writes SIF, runs ElmerSolver, returns displacement statistics.
    """
    from pathlib import Path as _P
    import elmer_elasticity_2d as ela2d
    work = _P(req.working_dir)
    ela2d.write_elasticity_2d_sif(
        work,
        poisson_ratio=req.poisson_ratio,
        youngs_modulus=req.youngs_modulus,
        density=req.density,
        wall_bc_tag=req.wall_bc_tag,
        load_bc_tag=req.load_bc_tag,
        force_magnitude=req.force_magnitude,
        plane_stress=req.plane_stress,
    )
    ela2d.write_startinfo(work)
    run = ela2d.run_elasticity(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:]]}
    try:
        stats = ela2d.get_displacement_stats(work)
    except Exception as e:
        return {"success": False, "message": str(e), "data": {"run": run}, "warnings": [], "errors": [str(e)]}
    return {
        "success": True,
        "message": f"Elasticity 2D solved. Max displacement: {stats['max_magnitude_m']:.5f} m",
        "data": {**stats, "solver_return": run["returncode"]},
        "warnings": [],
        "errors": [],
    }


@app.post("/elmer/setup_plate_deflection")
def elmer_setup_plate_deflection(req: ElmerPlateDeflectionRequest):
    """
    Tutorial 9: 2D Smitc plate solver for deflection of an elastic plate under pressure.
    """
    from pathlib import Path as _P
    import elmer_plate as elplate
    work = _P(req.working_dir)
    elplate.write_plate_deflection_sif(
        work,
        density=req.density,
        youngs_modulus=req.youngs_modulus,
        poisson_ratio=req.poisson_ratio,
        thickness=req.thickness,
        tension=req.tension,
        pressure=req.pressure,
        n_boundary_tags=req.n_boundary_tags,
    )
    elplate.write_startinfo(work)
    run = elplate.run_plate(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:] + run["stdout"][-1000:]]}
    try:
        stats = elplate.get_deflection_stats(work)
    except Exception as e:
        return {"success": False, "message": str(e), "data": {"run": run}, "warnings": [], "errors": [str(e)]}
    return {
        "success": True,
        "message": f"Plate deflection solved. Max deflection: {stats['max_deflection_m']*1000:.3f} mm",
        "data": {**stats, "solver_return": run["returncode"]},
        "warnings": [],
        "errors": [],
    }


@app.post("/elmer/setup_plate_eigenmodes")
def elmer_setup_plate_eigenmodes(req: ElmerPlateEigenmodesRequest):
    """
    Tutorial 10: 2D Smitc plate eigenmode analysis for a pentagon plate.
    Returns the computed eigenvalues (omega^2).
    """
    from pathlib import Path as _P
    import elmer_plate_eigen as elpei
    work = _P(req.working_dir)
    elpei.write_plate_eigenmodes_sif(
        work,
        density=req.density,
        youngs_modulus=req.youngs_modulus,
        poisson_ratio=req.poisson_ratio,
        thickness=req.thickness,
        tension=req.tension,
        n_eigen_values=req.n_eigen_values,
        n_boundary_tags=req.n_boundary_tags,
    )
    elpei.write_startinfo(work)
    run = elpei.run_plate_eigen(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:]]}
    eigenvalues = elpei.parse_eigenvalues(run["stdout"])
    vtu_info = elpei.get_eigenmode_vtu_stats(work, req.n_eigen_values)
    return {
        "success": True,
        "message": f"Plate eigenmodes solved. Found {len(eigenvalues)} eigenvalues.",
        "data": {
            "eigenvalues_omega_sq": eigenvalues,
            "expected_first": 18.9,
            "match_first": abs(eigenvalues[0] - 18.9) < 2.0 if eigenvalues else False,
            **vtu_info,
            "solver_return": run["returncode"],
        },
        "warnings": [],
        "errors": [],
    }


@app.post("/elmer/setup_elasticity_3d")
def elmer_setup_elasticity_3d(req: ElmerElasticity3DRequest):
    """
    Tutorial 7: 3D linear elasticity for a loaded elastic beam with gravity.
    Writes SIF, runs ElmerSolver, returns displacement statistics.
    """
    from pathlib import Path as _P
    import elmer_elasticity_3d as ela3d
    work = _P(req.working_dir)
    ela3d.write_elasticity_3d_sif(
        work,
        poisson_ratio=req.poisson_ratio,
        youngs_modulus=req.youngs_modulus,
        density=req.density,
        gravity_force_y=req.gravity_force_y,
        wall_bc_tag=req.wall_bc_tag,
        load_bc_tag=req.load_bc_tag,
        force_y=req.force_y,
    )
    ela3d.write_startinfo(work)
    run = ela3d.run_elasticity_3d(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:]]}
    try:
        stats = ela3d.get_displacement_stats_3d(work)
    except Exception as e:
        return {"success": False, "message": str(e), "data": {"run": run}, "warnings": [], "errors": [str(e)]}
    return {
        "success": True,
        "message": f"Elasticity 3D solved. Max displacement: {stats['max_magnitude_m']*100:.2f} cm",
        "data": {**stats, "solver_return": run["returncode"]},
        "warnings": [],
        "errors": [],
    }


@app.post("/elmer/setup_nonlinear_elasticity")
def elmer_setup_nonlinear_elasticity(req: ElmerNonlinearElasticityRequest):
    """
    Tutorial 8: 3D non-linear elasticity for a U-shaped hook under compression.
    Transient simulation with large displacements.
    """
    from pathlib import Path as _P
    import elmer_nonlinear as elnl
    work = _P(req.working_dir)
    elnl.write_nonlinear_elasticity_sif(
        work,
        density=req.density,
        youngs_modulus=req.youngs_modulus,
        poisson_ratio=req.poisson_ratio,
        n_timesteps=req.n_timesteps,
        timestep_size=req.timestep_size,
        coordinate_scaling=req.coordinate_scaling,
        moving_right_bc_tag=req.moving_right_bc_tag,
        moving_left_bc_tag=req.moving_left_bc_tag,
        displacement_amplitude=req.displacement_amplitude,
    )
    elnl.write_startinfo(work)
    run = elnl.run_nonlinear_elasticity(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-3000:]]}
    vtu_files = list(_P(req.working_dir).glob("case_t*.vtu"))
    n_written = len(vtu_files)
    try:
        stats = elnl.get_final_stress_stats(work, req.n_timesteps)
    except Exception as e:
        stats = {"note": str(e)}
    return {
        "success": True,
        "message": f"Non-linear elasticity solved. {n_written} VTU files written.",
        "data": {**stats, "vtu_files_written": n_written, "solver_return": run["returncode"]},
        "warnings": [],
        "errors": [],
    }


@app.post("/elmer/setup_acoustics")
def elmer_setup_acoustics(req: ElmerAcousticsRequest):
    """Tutorial 17: 2D Helmholtz equation for acoustic pressure waves in a cavity."""
    from pathlib import Path as _P
    import elmer_acoustics as elac
    work = _P(req.working_dir)
    elac.write_acoustics_sif(work, angular_frequency=req.angular_frequency,
        sound_speed=req.sound_speed, density=req.density,
        source_bc_tag=req.source_bc_tag, rigid_bc_tag=req.rigid_bc_tag,
        impedance_bc_tag=req.impedance_bc_tag, wave_flux=req.wave_flux,
        wave_impedance=req.wave_impedance)
    elac.write_startinfo(work)
    run = elac.run_acoustics(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:]]}
    try:
        stats = elac.get_pressure_stats(work)
    except Exception as e:
        stats = {"error": str(e)}
    return {"success": True,
            "message": f"Acoustics solved. Max pressure magnitude: {stats.get('max_magnitude', 'N/A')}",
            "data": {**stats, "solver_return": run["returncode"]},
            "warnings": [], "errors": []}


@app.post("/elmer/setup_electrostatics_2d")
def elmer_setup_electrostatics_2d(req: ElmerElectrostatics2DRequest):
    """Tutorial 11: 2D electrostatics for fringe capacitance computation."""
    from pathlib import Path as _P
    import elmer_electrostatics_2d as elec
    work = _P(req.working_dir)
    elec.write_electrostatics_2d_sif(work, vacuum_permittivity=req.vacuum_permittivity,
        relative_permittivity=req.relative_permittivity, ground_bc_tag=req.ground_bc_tag,
        capacitor_bc_tag=req.capacitor_bc_tag, ground_potential=req.ground_potential,
        capacitor_potential=req.capacitor_potential)
    elec.write_startinfo(work)
    run = elec.run_electrostatics(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:]]}
    capacitance = elec.parse_capacitance(run["stdout"])
    try:
        stats = elec.get_potential_stats(work)
    except Exception as e:
        stats = {}
    return {"success": True,
            "message": f"Electrostatics solved. Capacitance: {capacitance}",
            "data": {"capacitance": capacitance, **stats, "solver_return": run["returncode"]},
            "warnings": [], "errors": []}


@app.post("/elmer/setup_electrostatics_3d")
def elmer_setup_electrostatics_3d(req: ElmerElectrostatics3DRequest):
    """Tutorial 12: 3D electrostatics for capacitance matrix of two conducting balls."""
    from pathlib import Path as _P
    import elmer_electrostatics_3d as elec3d
    work = _P(req.working_dir)
    elec3d.write_capacitance_matrix_sif(work,
        vacuum_permittivity=req.vacuum_permittivity,
        relative_permittivity=req.relative_permittivity,
        farfield_bc_tag=req.farfield_bc_tag,
        cap_body1_bc_tag=req.cap_body1_bc_tag,
        cap_body2_bc_tag=req.cap_body2_bc_tag)
    elec3d.write_startinfo(work)
    run = elec3d.run_electrostatics_3d(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:]]}
    cap_matrix = elec3d.parse_capacitance_matrix(run["stdout"])
    try:
        stats = elec3d.get_potential_stats_3d(work)
    except Exception as e:
        stats = {}
    return {"success": True,
            "message": f"3D electrostatics solved. Capacitance matrix: {cap_matrix}",
            "data": {"capacitance_matrix": cap_matrix, **stats, "solver_return": run["returncode"]},
            "warnings": [], "errors": []}


# ---------------------------------------------------------------------------
# Elmer — Glacier heat (Tutorial 27)
# ---------------------------------------------------------------------------

from models import ElmerGlacierHeatRequest  # noqa: E402


@app.post("/elmer/setup_glacier_heat")
def elmer_setup_glacier_heat(req: ElmerGlacierHeatRequest):
    """Tutorial 27: Steady-state heat equation for temperature distribution in a toy glacier."""
    from pathlib import Path as _P
    import elmer_glacier_heat as elgh
    work = _P(req.working_dir)
    elgh.write_glacier_heat_sif(work, density=req.density,
        heat_conductivity=req.heat_conductivity, heat_capacity=req.heat_capacity,
        surface_bc_tag=req.surface_bc_tag, bottom_bc_tag=req.bottom_bc_tag,
        surface_temperature=req.surface_temperature, bottom_heat_flux=req.bottom_heat_flux)
    elgh.write_startinfo(work)
    run = elgh.run_glacier_heat(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:]]}
    try:
        stats = elgh.get_temperature_stats(work)
    except Exception as e:
        stats = {"error": str(e)}
    return {"success": True,
            "message": f"Glacier heat solved. Max T: {stats.get('max_temperature_k', 'N/A'):.2f} K",
            "data": {**stats, "solver_return": run["returncode"]},
            "warnings": [], "errors": []}


# ---------------------------------------------------------------------------
# Elmer — Laminar flow (Tutorial 19: Navier-Stokes past a step)
# ---------------------------------------------------------------------------

from models import ElmerFlowLaminarRequest  # noqa: E402


@app.post("/elmer/setup_flow_laminar", tags=["Elmer"])
def elmer_setup_flow_laminar(req: ElmerFlowLaminarRequest):
    """Tutorial 19: 2D laminar incompressible Navier-Stokes flow past a step."""
    from pathlib import Path as _P
    import elmer_flow_laminar as elfl
    work = _P(req.working_dir)
    elfl.write_step_flow_sif(
        work,
        wall_tags=req.wall_tags,
        inlet_tag=req.inlet_tag,
        outlet_tag=req.outlet_tag,
        density=req.density,
        viscosity=req.viscosity,
        max_velocity=req.max_inlet_velocity,
        inlet_y_min=req.inlet_y_min,
        inlet_y_max=req.inlet_y_max,
        steady_state_max_iter=req.steady_state_max_iter,
    )
    elfl.write_startinfo(work)
    run = elfl.run_flow(work)
    if run["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerSolver failed",
            "data": {"returncode": run["returncode"], "log_snippet": run["log_snippet"][-2000:]},
            "warnings": [],
            "errors": [run["log_snippet"][-2000:]],
        }
    try:
        stats = elfl.get_flow_stats(work)
    except Exception as e:
        stats = {"error": str(e)}
    return {
        "success": True,
        "message": f"Laminar flow solved. Max velocity: {stats.get('max_velocity_magnitude', 'N/A')}",
        "data": {**stats, "solver_return": run["returncode"], "converged": run["converged"]},
        "warnings": [],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Elmer — Magnetostatics 2D (Tutorial 15: horseshoe permanent magnet)
# ---------------------------------------------------------------------------

from models import ElmerMagnetostatics2DRequest, ElmerDrivenCavityRequest  # noqa: E402


@app.post("/elmer/setup_magnetostatics_2d", tags=["Elmer"])
def elmer_setup_magnetostatics_2d(req: ElmerMagnetostatics2DRequest):
    """Tutorial 15: 2D magnetostatics for a horseshoe permanent magnet."""
    from pathlib import Path as _P
    import elmer_magnetostatics_2d as elmag

    work = _P(req.working_dir)

    # Step 1: convert Gmsh mesh if needed
    try:
        elmag.convert_gmsh_mesh(work)
    except Exception as e:
        return {"success": False, "message": f"Mesh conversion failed: {e}",
                "data": {}, "warnings": [], "errors": [str(e)]}

    # Step 2: inspect mesh bodies and boundaries
    try:
        bodies = elmag.inspect_bodies(work)
    except Exception as e:
        bodies = {}

    try:
        boundaries = elmag.inspect_boundaries(work)
    except Exception as e:
        boundaries = {}

    # Step 3: auto-detect outer boundary tags (those with max_dist >= 2.9)
    outer_tags = req.outer_bc_tags
    if req.auto_detect_bodies and boundaries:
        detected = [
            tag for tag, info in boundaries.items()
            if info.get("max_dist_from_origin", 0) >= 2.9
        ]
        if detected:
            outer_tags = sorted(detected)

    # Step 4: write SIF
    elmag.write_magnetostatics_sif(
        work,
        air_body=req.air_body,
        iron_body=req.iron_body,
        ironplus_body=req.ironplus_body,
        ironminus_body=req.ironminus_body,
        outer_bc_tags=outer_tags,
        magnetization=req.magnetization,
        relative_permeability=req.relative_permeability,
    )

    # Step 5: write startinfo
    elmag.write_startinfo(work)

    # Step 6: run solver
    try:
        run = elmag.run_magnetostatics(work)
    except Exception as e:
        return {"success": False, "message": f"Solver failed: {e}",
                "data": {}, "warnings": [], "errors": [str(e)]}

    if run["returncode"] != 0:
        # Try without post-processor solver if it failed
        stdout = run.get("stdout", "") + run.get("stderr", "")
        if "MagnetoDynamics2DPost" in stdout or "Unable to load" in stdout:
            # Rewrite SIF without Solver 2
            sif_path = work / "case.sif"
            sif_content = sif_path.read_text(encoding="utf-8")
            # Remove Solver 2 block and change Active Solvers to just 1
            import re
            sif_content = re.sub(
                r'Solver 2\s*\n.*?End\n',
                '',
                sif_content,
                flags=re.DOTALL,
            )
            sif_content = sif_content.replace(
                "Active Solvers(2) = 1 2",
                "Active Solvers(1) = 1",
            )
            sif_path.write_text(sif_content, encoding="utf-8")
            run = elmag.run_magnetostatics(work)
            if run["returncode"] != 0:
                return {"success": False, "message": "ElmerSolver failed (even without post-solver)",
                        "data": {}, "warnings": [],
                        "errors": [run["stderr"][-3000:] + "\n" + run["stdout"][-2000:]]}

    # Step 7: parse Az results
    try:
        stats = elmag.get_az_stats(work)
    except Exception as e:
        stats = {"error": str(e)}

    az_min = stats.get("min_az", "?")
    az_max = stats.get("max_az", "?")
    try:
        msg = f"Magnetostatics solved. Az range: [{az_min:.4e}, {az_max:.4e}]"
    except Exception:
        msg = f"Magnetostatics solved. Az stats: {stats}"

    return {
        "success": True,
        "message": msg,
        "data": {
            **stats,
            "bodies_found": len(bodies),
            "body_assignments": {
                "air": req.air_body,
                "iron": req.iron_body,
                "ironplus": req.ironplus_body,
                "ironminus": req.ironminus_body,
            },
            "outer_bc_tags": outer_tags,
            "boundary_tags_found": sorted(boundaries.keys()),
            "solver_return": run["returncode"],
            "converged": run.get("converged", False),
        },
        "warnings": [] if run.get("converged") else ["Solver may not have converged — check stdout"],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Elmer — Tutorial 13: Electrostatics with floating potential
# ---------------------------------------------------------------------------

@app.post("/elmer/setup_electrostatics_floating")
def elmer_setup_electrostatics_floating(req: ElmerElectrostaticsFloatingRequest):
    """Tutorial 13: Electrostatics with floating potential conductors."""
    from pathlib import Path as _P
    import elmer_electrostatics_floating as ef
    work = _P(req.working_dir)
    ef.write_floating_potential_sif(work)
    ef.write_startinfo(work)
    run = ef.run_electrostatics_floating(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:]]}
    try:
        stats = ef.get_potential_stats(work)
    except Exception as e:
        stats = {"vtu_error": str(e)}
    return {"success": True, "message": "Floating potential solved",
            "data": {**stats, "solver_return": run["returncode"]},
            "warnings": [], "errors": []}


# ---------------------------------------------------------------------------
# Elmer — ModelPDE 3D (Tutorial 29: General PDE solver)
# ---------------------------------------------------------------------------

from models import ElmerModelPDERequest  # noqa: E402


@app.post("/elmer/setup_model_pde")
def elmer_setup_model_pde(req: ElmerModelPDERequest):
    """Tutorial 29: ModelPDE general PDE solver on a 3D geometry.

    Solves: c*du/dt - div(k*grad(u)) + a*u = f
    Default: steady-state Poisson equation (-div(grad(u)) = 1) with u=0 on all walls.
    """
    from pathlib import Path as _P
    import elmer_model_pde as mpde

    work = _P(req.working_dir)

    # Write SIF
    mpde.write_model_pde_sif(
        work,
        diffusion_coefficient=req.diffusion_coefficient,
        reaction_coefficient=req.reaction_coefficient,
        time_derivative_coefficient=req.time_derivative_coefficient,
        field_source=req.field_source,
        dirichlet_tags=req.dirichlet_tags if req.dirichlet_tags else None,
        dirichlet_value=req.dirichlet_value,
        neumann_tags=req.neumann_tags if req.neumann_tags else None,
        neumann_value=req.neumann_value,
    )

    # Write ELMERSOLVER_STARTINFO
    mpde.write_startinfo(work)

    # Run solver
    run = mpde.run_model_pde(work, timeout=req.timeout_seconds)

    if run["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerSolver failed",
            "data": {"returncode": run["returncode"], "elapsed_seconds": run["elapsed_seconds"]},
            "warnings": [],
            "errors": [run["stderr"][-2000:]],
        }

    # Parse field statistics from VTU output
    try:
        stats = mpde.get_field_stats(work)
    except Exception as e:
        stats = {"vtu_error": str(e)}

    return {
        "success": True,
        "message": (
            f"ModelPDE solved in {run['elapsed_seconds']:.1f}s. "
            f"Field range: [{stats.get('min_value', '?'):.4f}, {stats.get('max_value', '?'):.4f}]"
        ),
        "data": {**stats, "solver_return": run["returncode"], "converged": run["converged"]},
        "warnings": [] if run["converged"] else ["Solver may not have converged — check stdout"],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Elmer — Driven Cavity (Tutorial 20: Navier-Stokes)
# ---------------------------------------------------------------------------

@app.post("/elmer/setup_driven_cavity", tags=["Elmer"])
def elmer_setup_driven_cavity(req: ElmerDrivenCavityRequest):
    """Tutorial 20: Driven cavity Navier-Stokes."""
    from pathlib import Path as _P
    import elmer_driven_cavity as dc
    work = _P(req.working_dir)
    dc.write_driven_cavity_sif(work, lid_velocity=req.lid_velocity, viscosity=req.viscosity)
    dc.write_startinfo(work)
    run = dc.run_driven_cavity(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:]]}
    try:
        stats = dc.get_velocity_stats(work)
    except Exception as e:
        stats = {"vtu_error": str(e)}
    return {"success": True, "message": "Driven cavity solved",
            "data": {**stats, "solver_return": run["returncode"]},
            "warnings": [], "errors": []}


# ---------------------------------------------------------------------------
# Elmer — Induction Heating (Tutorial 16: MagnetoDynamics2D + Joule heating)
# ---------------------------------------------------------------------------

from models import ElmerInductionHeatingRequest  # noqa: E402


@app.post("/elmer/setup_induction_heating", tags=["Elmer"])
def elmer_setup_induction_heating(req: ElmerInductionHeatingRequest):
    """Tutorial 16: Induction heating of graphite crucible."""
    from pathlib import Path as _P
    import elmer_induction_heating as ih
    work = _P(req.working_dir)
    ih.write_induction_heating_sif(work)
    ih.write_startinfo(work)
    run = ih.run_induction_heating(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:]]}
    try:
        stats = ih.get_temperature_stats(work)
    except Exception as e:
        stats = {"vtu_error": str(e)}
    return {"success": True, "message": "Induction heating solved",
            "data": {**stats, "solver_return": run["returncode"]},
            "warnings": [], "errors": []}


# ---------------------------------------------------------------------------
# Elmer — Von Karman vortex street (Tutorial 23: transient Navier-Stokes)
# ---------------------------------------------------------------------------

from models import ElmerVonKarmanRequest  # noqa: E402


@app.post("/elmer/setup_von_karman")
def elmer_setup_von_karman(req: ElmerVonKarmanRequest):
    """Tutorial 23: Von Karman vortex street (transient Navier-Stokes around cylinder)."""
    from pathlib import Path as _P
    import elmer_von_karman as vk
    work = _P(req.working_dir)
    vk.write_von_karman_sif(work)
    vk.write_startinfo(work)
    run = vk.run_von_karman(work)
    if run["returncode"] != 0:
        return {"success": False, "message": "ElmerSolver failed", "data": {}, "warnings": [], "errors": [run["stderr"][-2000:]]}
    try:
        stats = vk.get_vortex_stats(work)
    except Exception as e:
        stats = {"vtu_error": str(e)}
    return {"success": True, "message": "Von Karman simulation complete",
            "data": {**stats, "solver_return": run["returncode"]},
            "warnings": [], "errors": []}


# ---------------------------------------------------------------------------
# Elmer — Tutorial 21: Eigenfrequency Analysis of an Elastic Plate
# ---------------------------------------------------------------------------

@app.post("/elmer/setup_plate_eigenmodes_t21", tags=["Elmer"])
def elmer_setup_plate_eigenmodes_t21(req: ElmerPlateEigenmodesRequest):
    """
    Tutorial 21: Eigenfrequency (modal) analysis of a clamped elastic plate.

    Uses the Smitc (Reissner-Mindlin) plate bending solver in eigen-analysis mode
    to compute the natural frequencies (omega^2 eigenvalues) of a clamped
    pentagon-shaped plate.

    Mesh source: C:\\Elmer\\tutorials\\tutorials-GUI-files\\ElasticPlateEigenmodesGUI\\

    Default parameters match the tutorial reference:
      density=1000 kg/m^3, E=1e9 Pa, nu=0.3, thickness=0.001 m
    Expected first eigenvalue (omega^2) ~ 18.9

    Returns eigenvalues_omega_sq list, mode shape VTU stats, and solver status.
    """
    from pathlib import Path as _P
    import elmer_plate_eigenmodes_t21 as t21

    work = _P(req.working_dir)
    t21.write_sif(
        work,
        density=req.density,
        youngs_modulus=req.youngs_modulus,
        poisson_ratio=req.poisson_ratio,
        thickness=req.thickness,
        tension=req.tension,
        n_eigen_values=req.n_eigen_values,
        n_boundary_tags=req.n_boundary_tags,
    )
    t21.write_startinfo(work)
    run = t21.run_solver(work, timeout=300)

    if run["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerSolver failed",
            "data": {"returncode": run["returncode"]},
            "warnings": [],
            "errors": [run["log_snippet"][-2000:]],
        }

    eigenvalues = t21.parse_eigenvalues(run["stdout"])
    vtu_info = t21.get_stats(work, req.n_eigen_values)

    first_ev = eigenvalues[0] if eigenvalues else None
    match_first = abs(first_ev - 18.9) < 2.0 if first_ev is not None else False

    return {
        "success": True,
        "message": (
            f"Plate eigenmodes (T21) solved in {run['elapsed_seconds']:.1f}s. "
            f"Found {len(eigenvalues)} eigenvalues. "
            f"First omega^2 = {first_ev:.4f}" if first_ev is not None
            else f"Plate eigenmodes (T21) solved. {len(eigenvalues)} eigenvalues."
        ),
        "data": {
            "eigenvalues_omega_sq": eigenvalues,
            "first_eigenvalue": first_ev,
            "expected_first": 18.9,
            "match_first": match_first,
            "elapsed_seconds": run["elapsed_seconds"],
            "solver_return": run["returncode"],
            "converged": run["converged"],
            **vtu_info,
        },
        "warnings": [] if run["converged"] else ["Solver may not have converged"],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Elmer — Turbulent flow k-epsilon (Tutorial 14: FlowStepKe)
# ---------------------------------------------------------------------------

from models import ElmerFlowKEpsilonRequest, ElmerMagneticWireRequest, ElmerRayleighBenardRequest, ElmerWaveguideRequest  # noqa: E402


@app.post("/elmer/setup_flow_kepsilon", tags=["Elmer"])
def elmer_setup_flow_kepsilon(req: ElmerFlowKEpsilonRequest):
    """
    Tutorial 14: Turbulent 2D Navier-Stokes flow past a backward-facing step
    using the k-epsilon turbulence model (FlowStepKe).

    The k-epsilon model adds two additional transport equations:
      - k  (turbulent kinetic energy)
      - epsilon (turbulent dissipation rate)

    These couple back into the Navier-Stokes solver via an effective turbulent
    viscosity mu_t = Cmu * rho * k^2 / epsilon.

    Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\FlowStepKe\\
    Boundary tags:  1=inlet, 2=outlet, 3=walls

    Expected result: converged steady-state turbulent velocity field with
    recirculation zone downstream of the step.
    """
    import shutil as _shutil
    from pathlib import Path as _P
    import elmer_flow_ke as ke


    if not ke.elmer_available():
        return {"success": False, "message": "ElmerSolver not found.",
                "data": {}, "warnings": [], "errors": ["ElmerSolver.exe missing"]}

    work = _P(req.working_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Copy mesh files if requested
    if req.mesh_source_dir:
        src = _P(req.mesh_source_dir)
        for f in src.glob("mesh.*"):
            _shutil.copy2(f, work / f.name)

    # Write SIF
    sif_path = ke.write_sif(
        work,
        density=req.density,
        viscosity=req.viscosity,
        wall_tags=req.wall_tags,
        inlet_tag=req.inlet_tag,
        outlet_tag=req.outlet_tag,
        max_inlet_velocity=req.max_inlet_velocity,
        inlet_y_min=req.inlet_y_min,
        inlet_y_max=req.inlet_y_max,
        kinetic_energy_init=req.kinetic_energy_init,
        kinetic_dissipation_init=req.kinetic_dissipation_init,
        steady_state_max_iter=req.steady_state_max_iter,
    )
    ke.write_startinfo(work)

    # Run solver
    run = ke.run_solver(work, timeout=300)

    if run["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerSolver failed",
            "data": {
                "returncode": run["returncode"],
                "elapsed_seconds": run["elapsed_seconds"],
                "log_snippet": run["log_snippet"][-2000:],
            },
            "warnings": [],
            "errors": [run["log_snippet"][-2000:]],
        }

    # Parse flow statistics
    field_stats = {}
    for field in ["Velocity 1", "Velocity 2", "Pressure", "Kinetic Energy", "Kinetic Dissipation"]:
        try:
            field_stats[field] = ke.get_stats(work, field)
        except Exception as e:
            field_stats[field] = {"error": str(e)}

    max_vx = field_stats.get("Velocity 1", {}).get("max_value", None)
    msg_part = f"Max Vx = {max_vx:.4f} m/s" if max_vx is not None else "see field_stats"

    return {
        "success": True,
        "message": (
            f"K-epsilon turbulent flow solved in {run['elapsed_seconds']:.1f}s. "
            f"{msg_part}. Converged: {run['converged']}"
        ),
        "data": {
            "sif_path": str(sif_path),
            "returncode": run["returncode"],
            "converged": run["converged"],
            "elapsed_seconds": run["elapsed_seconds"],
            "field_stats": field_stats,
        },
        "warnings": [] if run["converged"] else ["Solver may not have converged — check log"],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Elmer — Magnetic Field Wire (Tutorial 18: harmonic MagnetoDynamics A-V)
# ---------------------------------------------------------------------------

@app.post("/elmer/setup_magnetic_wire", tags=["Elmer"])
def elmer_setup_magnetic_wire(req: ElmerMagneticWireRequest):
    """
    Tutorial 18: Harmonic magnetodynamics for a current-carrying copper wire.

    Uses the WhitneyAVHarmonicSolver to compute the complex magnetic vector
    potential A-V in a copper wire and surrounding air domain. The post-
    processing solver computes magnetic field strength H and Joule heating.

    Mesh: MagneticFieldWire tutorial geometry (two bodies: copper + air).
    Default boundary tags: 1=voltage, 3=ground, 4/5/6=axial field.

    Returns: sif_path, converged, elapsed_seconds, field stats for 'av re'.
    """
    import shutil as _shutil
    from pathlib import Path as _P
    import elmer_magnetic_wire as mw

    if not mw.elmer_available():
        return {"success": False, "message": "ElmerSolver not found.",
                "data": {}, "warnings": [], "errors": ["ElmerSolver.exe missing"]}

    work = _P(req.working_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Copy mesh files
    src_dir = _P(req.mesh_source_dir) if req.mesh_source_dir else mw.TUTORIAL_MESH_DIR
    for f in src_dir.glob("mesh.*"):
        _shutil.copy2(f, work / f.name)

    # Write SIF
    sif_path = mw.write_magnetic_wire_sif(
        work,
        angular_frequency=req.angular_frequency,
        coordinate_scaling=req.coordinate_scaling,
        copper_conductivity=req.copper_conductivity,
        copper_permeability=req.copper_permeability,
        air_permeability=req.air_permeability,
        voltage_amplitude=req.voltage_amplitude,
        voltage_tag=req.voltage_tag,
        ground_tag=req.ground_tag,
        axial_tags=req.axial_tags,
    )
    mw.write_startinfo(work)

    # Run solver
    run = mw.run_solver(work, timeout=req.timeout_seconds)

    if run["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerSolver failed",
            "data": {
                "returncode": run["returncode"],
                "elapsed_seconds": run["elapsed_seconds"],
                "log_snippet": run["log_snippet"][-2000:],
            },
            "warnings": [],
            "errors": [run["log_snippet"][-2000:]],
        }

    # Parse field statistics — try 'av re' first (the magnetic vector potential)
    field_stats = {}
    for field in ["av re", "av im", "joule heating"]:
        try:
            field_stats[field] = mw.get_field_stats(work, field)
        except Exception as e:
            field_stats[field] = {"error": str(e)}

    av_re_stats = field_stats.get("av re", {})  # type: ignore
    av_max = av_re_stats.get("max_value", None)
    try:
        summary = f"Max |AV re| = {av_max:.4e}" if av_max is not None else "see field_stats"
    except Exception:
        summary = str(av_max)

    return {
        "success": True,
        "message": (
            f"Magnetic wire simulation converged in {run['elapsed_seconds']:.1f}s. "
            f"{summary}"
        ),
        "data": {
            "sif_path": str(sif_path),
            "returncode": run["returncode"],
            "converged": run["converged"],
            "elapsed_seconds": run["elapsed_seconds"],
            "field_stats": field_stats,
        },
        "warnings": [] if run["converged"] else ["Solver may not have converged — check log"],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Elmer — Rayleigh-Benard Convection (Tutorial 24)
# ---------------------------------------------------------------------------

@app.post("/elmer/setup_rayleigh_benard", tags=["Elmer"])
def elmer_setup_rayleigh_benard(req: ElmerRayleighBenardRequest):
    """Tutorial 24: Rayleigh-Benard convection (buoyancy-driven flow, coupled NS+Heat).

    Transient 2D simulation of natural convection in a rectangular water layer
    heated from below and cooled from above. Uses the Boussinesq approximation
    for density variation. Based on the RayleighBenardGUI Elmer tutorial.

    Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\RayleighBenardGUI\\
    Boundary tags: 1 = bottom (hot), 2 = top (cold).

    Material defaults (water at room temperature):
      density=998.3, viscosity=1.002e-3, conductivity=0.58,
      capacity=4183, expansion=2.07e-4, T_ref=293 K.
    """
    import shutil as _shutil
    from pathlib import Path as _P
    import elmer_rayleigh_benard as rb

    work = _P(req.working_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Use GUI tutorial mesh as default source
    default_mesh = _P(r"C:\Elmer\tutorials\tutorials-GUI-files\RayleighBenardGUI")
    mesh_src = _P(req.mesh_source_dir) if req.mesh_source_dir else default_mesh

    for f in mesh_src.glob("mesh.*"):
        _shutil.copy2(f, work / f.name)

    sif_path = rb.write_rayleigh_benard_sif(
        work,
        timestep_intervals=req.n_timesteps,
        timestep_size=req.timestep_size,
        density=req.density,
        viscosity=req.viscosity,
        heat_conductivity=req.heat_conductivity,
        heat_capacity=req.heat_capacity,
        heat_expansion_coeff=req.heat_expansion_coefficient,
        reference_temperature=req.reference_temperature,
        bottom_temperature=req.hot_wall_temperature,
        top_temperature=req.cold_wall_temperature,
        initial_temperature=req.initial_temperature,
    )
    rb.write_startinfo(work)

    run = rb.run_rayleigh_benard(work, timeout=req.timeout_seconds)

    if run["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerSolver failed",
            "data": {
                "returncode": run["returncode"],
                "elapsed_seconds": run["elapsed_seconds"],
                "log_snippet": run["log_snippet"][-2000:],
            },
            "warnings": [],
            "errors": [run["log_snippet"][-2000:]],
        }

    try:
        stats = rb.get_stats(work)
    except Exception as e:
        stats = {"vtu_error": str(e)}

    t_max = stats.get("temperature_max", "?")
    t_min = stats.get("temperature_min", "?")
    v_max = stats.get("max_velocity_magnitude", "?")

    return {
        "success": True,
        "message": (
            "Rayleigh-Benard convection solved in {:.1f}s. "
            "T=[{}, {}] K, max_velocity={} m/s".format(
                run["elapsed_seconds"], t_min, t_max, v_max
            )
        ),
        "data": {
            **stats,
            "sif_path": str(sif_path),
            "returncode": run["returncode"],
            "converged": run["converged"],
            "elapsed_seconds": run["elapsed_seconds"],
        },
        "warnings": [] if run["converged"] else ["Solver may not have converged — check log"],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Elmer — Tutorial 30: Vector Helmholtz (3D bent waveguide)
# ---------------------------------------------------------------------------

@app.post("/elmer/setup_waveguide", tags=["Elmer"])
def elmer_setup_waveguide(req: ElmerWaveguideRequest):
    """
    Tutorial 30: Vector Helmholtz equation for EM wave propagation in a bent
    rectangular 3D waveguide (WaveguideGUI).

    Uses Elmer's VectorHelmholtz solver with MUMPS direct solver.
    Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\WaveguideGUI\\
    (14 boundary tags: 1=port-in, 2=port-out, 3-14=PEC walls)

    Returns E-field magnitude statistics from the VTU result file.
    """
    import shutil as _shutil
    from pathlib import Path as _P
    import elmer_waveguide as wg

    if not wg.elmer_available():
        return {"success": False, "message": "ElmerSolver not found.",
                "data": {}, "warnings": [], "errors": ["ElmerSolver.exe missing"]}

    work = _P(req.working_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Copy mesh files
    src_dir = _P(req.mesh_source_dir) if req.mesh_source_dir else wg.TUTORIAL_MESH_DIR
    copied = []
    for f in src_dir.glob("mesh.*"):
        _shutil.copy2(f, work / f.name)
        copied.append(f.name)

    # Write SIF (convert angular_frequency to Hz for write_sif)
    import math as _math
    sif_path = wg.write_sif(
        work,
        frequency=req.angular_frequency / (2 * _math.pi),
        relative_permittivity=req.relative_permittivity,
        relative_permeability=req.relative_permeability,
        port_in_tag=req.port_in_tag,
        port_out_tag=req.port_out_tag,
    )
    wg.write_startinfo(work)

    # Run solver
    run = wg.run_solver(work, timeout_seconds=req.timeout_seconds)

    if run["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerSolver failed",
            "data": {
                "returncode": run["returncode"],
                "elapsed_seconds": run["elapsed_seconds"],
                "log_snippet": run["log_snippet"][-3000:],
            },
            "warnings": [],
            "errors": [run["log_snippet"][-3000:]],
        }

    # Parse E-field statistics
    try:
        stats = wg.get_stats(work)
    except Exception as exc:
        stats = {"vtu_error": str(exc)}

    max_e = stats.get("max_e_magnitude", None)
    try:
        summary = f"Max |E| = {max_e:.4e} V/m" if max_e is not None else "see field_stats"
    except Exception:
        summary = str(max_e)

    return {
        "success": True,
        "message": (
            f"Waveguide Vector Helmholtz solved in {run['elapsed_seconds']:.1f}s. "
            f"{summary}. Converged: {run['converged']}"
        ),
        "data": {
            "sif_path": str(sif_path),
            "mesh_files_copied": copied,
            "returncode": run["returncode"],
            "converged": run["converged"],
            "elapsed_seconds": run["elapsed_seconds"],
            **stats,
        },
        "warnings": [] if run["converged"] else ["Solver may not have converged — check log"],
        "errors": [],
    }

# ---------------------------------------------------------------------------
# Elmer -- Thermal Actuator (Tutorial 22: coupled Joule + Heat + Stress)
# ---------------------------------------------------------------------------

from models import ElmerThermalActuatorRequest  # noqa: E402

@app.post("/elmer/setup_thermal_actuator", tags=["Elmer"])
def elmer_setup_thermal_actuator(req: ElmerThermalActuatorRequest):
    """
    Tutorial 22: Silicon MEMS thermal actuator -- coupled electro-thermo-mechanical analysis.

    Three coupled solvers:
      1. StatCurrentSolve  -- electric potential and Joule heating
      2. Heat Equation     -- temperature distribution from Joule heat source
      3. Stress Analysis   -- thermal stress and displacement

    A box mesh is generated automatically by ElmerGrid (no external mesh needed).
    Material: silicon with temperature-dependent electric conductivity.

    Returns: sif_path, converged, elapsed_seconds, temperature stats, displacement stats.
    """
    from pathlib import Path as _P
    import elmer_thermal_actuator as ta

    if not ta.elmer_available():
        return {"success": False, "message": "ElmerSolver not found.",
                "data": {}, "warnings": [], "errors": ["ElmerSolver.exe missing"]}

    work = _P(req.working_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Generate mesh using ElmerGrid
    mesh_result = ta.generate_mesh(work, nx=req.mesh_nx, ny=req.mesh_ny, nz=req.mesh_nz)
    if mesh_result["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerGrid mesh generation failed",
            "data": {"mesh_result": mesh_result},
            "warnings": [],
            "errors": [mesh_result.get("stderr", "")[-2000:]],
        }

    # Write SIF
    sif_path = ta.write_thermal_actuator_sif(
        work,
        voltage=req.voltage,
        ground_bc_tag=req.ground_bc_tag,
        voltage_bc_tag=req.voltage_bc_tag,
        reference_temperature=req.reference_temperature,
        youngs_modulus=req.youngs_modulus,
        poisson_ratio=req.poisson_ratio,
        heat_expansion_coefficient=req.heat_expansion_coefficient,
        steady_state_max_iter=req.steady_state_max_iter,
    )
    ta.write_startinfo(work)

    # Run solver
    run = ta.run_solver(work, timeout=req.timeout_seconds)

    if run["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerSolver failed",
            "data": {
                "returncode": run["returncode"],
                "elapsed_seconds": run["elapsed_seconds"],
                "log_snippet": run["log_snippet"][-2000:],
            },
            "warnings": [],
            "errors": [run["log_snippet"][-2000:]],
        }

    # Parse field statistics
    try:
        stats = ta.get_stats(work)
    except Exception as e:
        stats = {"vtu_error": str(e)}

    t_max = stats.get("temperature_max", "?")
    disp_max = stats.get("displacement_magnitude_max", "?")

    return {
        "success": True,
        "message": (
            "Thermal actuator solved in {:.1f}s. "
            "T_max={} K, max_disp_magnitude={}".format(
                run["elapsed_seconds"], t_max, disp_max
            )
        ),
        "data": {
            **stats,
            "sif_path": str(sif_path),
            "returncode": run["returncode"],
            "converged": run["converged"],
            "elapsed_seconds": run["elapsed_seconds"],
        },
        "warnings": [] if run["converged"] else ["Solver may not have converged -- check log"],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Elmer — Glacier Temperature + Flow (Tutorial 28)
# ---------------------------------------------------------------------------

from models import ElmerGlacierFlowRequest  # noqa: E402


@app.post("/elmer/setup_glacier_flow", tags=["Elmer"])
def elmer_setup_glacier_flow(req: ElmerGlacierFlowRequest):
    """Tutorial 28: Coupled steady-state heat + Navier-Stokes flow in a toy glacier.

    Solves for temperature distribution and ice flow in a 2D glacier cross-section.
    Ice viscosity follows Glen's flow law (Arrhenius temperature dependence).
    The bedrock is heat-only. Gravity drives the ice flow downslope.

    Mesh: ToyGlacierTemperatureAndFlow tutorial geometry (2 bodies: ice + bedrock).
    Boundary tags: 1=bedrock bottom, 2=left side, 3=glacier surface, 4=right side.

    Returns: temperature range (degC), max ice flow velocity, solver convergence info.
    """
    import shutil as _shutil
    from pathlib import Path as _P
    import elmer_glacier_flow as gf

    if not gf.elmer_available():
        return {"success": False, "message": "ElmerSolver not found.",
                "data": {}, "warnings": [], "errors": ["ElmerSolver.exe missing"]}

    work = _P(req.working_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Copy mesh files
    src_dir = _P(req.mesh_source_dir) if req.mesh_source_dir else gf.TUTORIAL_MESH_DIR
    for f in src_dir.glob("mesh.*"):
        _shutil.copy2(f, work / f.name)

    # Write SIF
    sif_path = gf.write_glacier_flow_sif(
        work,
        ice_density=req.ice_density,
        bedrock_density=req.bedrock_density,
        surface_temperature=req.surface_temperature,
        bottom_heat_flux=req.bottom_heat_flux,
        steady_state_max_iter=req.steady_state_max_iter,
        nonlinear_max_iter=req.nonlinear_max_iter,
        ice_body_tag=req.ice_body_tag,
        bedrock_body_tag=req.bedrock_body_tag,
        surface_bc_tag=req.surface_bc_tag,
        bottom_bc_tag=req.bottom_bc_tag,
        side_bc_tags=req.side_bc_tags,
    )
    gf.write_startinfo(work)

    # Run solver
    run = gf.run_glacier_flow(work, timeout=req.timeout_seconds)

    if run["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerSolver failed",
            "data": {
                "returncode": run["returncode"],
                "elapsed_seconds": run["elapsed_seconds"],
                "log_snippet": run["log_snippet"][-2000:],
            },
            "warnings": [],
            "errors": [run["log_snippet"][-2000:]],
        }

    # Parse field statistics
    try:
        stats = gf.get_stats(work)
    except Exception as e:
        stats = {"parse_error": str(e)}

    t_min = stats.get("min_temperature")
    t_max = stats.get("max_temperature")
    v_max = stats.get("max_velocity_magnitude")

    try:
        temp_summary = f"T=[{t_min:.2f}, {t_max:.2f}] degC" if t_min is not None else "T=unknown"
        vel_summary = f"max_v={v_max:.4e} m/s" if v_max is not None else "v=unknown"
    except Exception:
        temp_summary = str(t_min)
        vel_summary = str(v_max)

    return {
        "success": True,
        "message": (
            f"Glacier flow simulation converged in {run['elapsed_seconds']:.1f}s. "
            f"{temp_summary}, {vel_summary}"
        ),
        "data": {
            **stats,
            "sif_path": str(sif_path),
            "returncode": run["returncode"],
            "converged": run["converged"],
            "elapsed_seconds": run["elapsed_seconds"],
        },
        "warnings": [] if run["converged"] else ["Solver may not have converged — check log"],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Elmer — Tutorial 25: Electrokinetics (electroosmotic flow in T-microchannel)
# ---------------------------------------------------------------------------

from models import ElmerPerforatedPlateRequest  # noqa: E402
import elmer_perforated_plate as _pp  # noqa: E402


# Elmer — Perforated Plate Capacitance (Tutorial 14)
@app.post("/elmer/setup_perforated_plate", tags=["Elmer"])
def elmer_setup_perforated_plate(req: ElmerPerforatedPlateRequest):
    """
    **Tool: elmer/setup_perforated_plate**

    Tutorial 14: 3D electrostatics of a perforated parallel-plate capacitor.

    Computes the electric potential and energy in the air gap of a unit-cell
    model of a square plate with a cylindrical perforation (hole). The effective
    capacitance is reduced by the hole relative to a solid plate.

    Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\CapacitanceOfPerforatedPlate\\
    Mesh is in mm; coordinate_scaling=0.001 converts to SI metres.

    Boundary tags (default):
      - ground_bc_tag=4: ground plane (Potential = 0 V)
      - capacitor_bc_tags=[1,2,3,7]: plate faces (Potential = 1 V)

    Returns: Potential field statistics (min/max/mean) and solver convergence.
    """
    import shutil as _shutil
    from pathlib import Path as _P

    if not _pp.elmer_available():
        return {
            "success": False,
            "message": "ElmerSolver not found.",
            "data": {},
            "warnings": [],
            "errors": ["ElmerSolver.exe missing from expected path."],
        }

    work = _P(req.working_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Copy mesh files from tutorial directory (or custom source)
    src = _P(req.mesh_source_dir) if req.mesh_source_dir else _pp.TUTORIAL_MESH_DIR
    for f in src.glob("mesh.*"):
        _shutil.copy2(f, work / f.name)

    # Write SIF
    sif_path = _pp.write_sif(
        work,
        ground_bc_tag=req.ground_bc_tag,
        capacitor_bc_tags=req.capacitor_bc_tags,
        ground_potential=req.ground_potential,
        capacitor_potential=req.capacitor_potential,
        relative_permittivity=req.relative_permittivity,
        coordinate_scaling=req.coordinate_scaling,
    )
    _pp.write_startinfo(work)

    # Run solver
    run = _pp.run_solver(work, timeout=req.timeout_seconds)

    if run["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerSolver failed.",
            "data": {
                "returncode": run["returncode"],
                "elapsed_seconds": run["elapsed_seconds"],
                "log_snippet": run["log_snippet"][-2000:],
            },
            "warnings": [],
            "errors": [run["log_snippet"][-2000:]],
        }

    # Parse field statistics
    field_stats: dict = {}
    for field in ["Potential", "Electric Field"]:
        try:
            field_stats[field] = _pp.get_stats(work, field)
        except Exception as exc:
            field_stats[field] = {"error": str(exc)}

    pot = field_stats.get("Potential", {})
    max_pot = pot.get("max_value")
    summary = (
        f"Max potential = {max_pot:.4f} V" if max_pot is not None else "see field_stats"
    )

    return {
        "success": True,
        "message": (
            f"Perforated plate capacitance solved in {run['elapsed_seconds']:.1f}s. "
            f"{summary}. Converged: {run['converged']}"
        ),
        "data": {
            "sif_path": str(sif_path),
            "returncode": run["returncode"],
            "converged": run["converged"],
            "elapsed_seconds": run["elapsed_seconds"],
            "field_stats": field_stats,
        },
        "warnings": [] if run["converged"] else ["Solver may not have converged — check log"],
        "errors": [],
    }


from models import ElmerElectrokineticsRequest, ElmerTEAM7Request  # noqa: E402


# ---------------------------------------------------------------------------
# Elmer — Tutorial 31: TEAM Workshop Problem 7 (3D transient eddy currents)
# ---------------------------------------------------------------------------

@app.post("/elmer/setup_team7", tags=["Elmer"])
def elmer_setup_team7(req: ElmerTEAM7Request):
    """
    **Tool: elmer/setup_team7**

    Tutorial 31: TEAM Workshop Problem 7 — Asymmetrical Conductor with a Hole.

    Simulates 3D transient eddy currents in an aluminium plate with an eccentric
    hole driven by a sinusoidal coil current at 50 Hz (2 periods, 16 timesteps).

    Solvers:
      1. CoilSolver       — computes normalised coil current distribution (before all)
      2. WhitneyAVSolver  — transient A-V eddy current formulation
      3. MagnetoDynamicsCalcFields — magnetic flux density B, current density J

    Mesh: elmer-elmag/TEAM7/TEAM7/ (3 bodies: Coil, Plate/Aluminium, Air)
    Boundary: tag 6 = Inf (far-field, A{e} = 0)

    Returns Bz field statistics from the final VTU result file.
    """
    import shutil as _shutil
    from pathlib import Path as _P
    import elmer_team7 as t7

    if not t7.elmer_available():
        return {
            "success": False,
            "message": "ElmerSolver not found.",
            "data": {},
            "warnings": [],
            "errors": ["ElmerSolver.exe missing from expected path."],
        }

    work = _P(req.working_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Copy mesh files into working_dir/TEAM7/
    mesh_src = _P(req.mesh_source_dir) if req.mesh_source_dir else None
    try:
        copied = t7.copy_team7_mesh(work, mesh_src)
    except Exception as exc:
        return {
            "success": False,
            "message": f"Mesh copy failed: {exc}",
            "data": {},
            "warnings": [],
            "errors": [str(exc)],
        }

    # Create results directory
    res_dir = work / "res"
    res_dir.mkdir(exist_ok=True)

    # Write SIF
    sif_path = t7.write_team7_sif(
        work,
        timestep_interval=req.timestep_interval,
        timestep_size=req.timestep_size,
    )

    # Write ELMERSOLVER_STARTINFO
    t7.write_startinfo(work)

    # Run solver
    run = t7.run_team7(work, timeout=req.timeout_seconds)

    if run["returncode"] != 0 and not run["converged"]:
        return {
            "success": False,
            "message": "ElmerSolver failed for TEAM7",
            "data": {
                "returncode": run["returncode"],
                "elapsed_seconds": run["elapsed_seconds"],
                "log_snippet": run["log_snippet"][-3000:],
                "sif_path": str(sif_path),
                "mesh_files_copied": copied,
            },
            "warnings": [],
            "errors": [run["log_snippet"][-3000:]],
        }

    # Parse Bz statistics from final VTU file
    try:
        bz_stats = t7.get_bz_stats(work)
    except Exception as exc:
        bz_stats = {"error": str(exc)}

    abs_max = bz_stats.get("abs_max_bz")
    try:
        bz_summary = f"abs_max_Bz = {abs_max:.4e} T" if abs_max is not None else "see bz_stats"
    except Exception:
        bz_summary = str(abs_max)

    return {
        "success": True,
        "message": (
            f"TEAM7 transient eddy currents solved in {run['elapsed_seconds']:.1f}s. "
            f"{bz_summary}. Converged: {run['converged']}"
        ),
        "data": {
            "sif_path": str(sif_path),
            "mesh_files_copied": copied,
            "timestep_interval": req.timestep_interval,
            "timestep_size": req.timestep_size,
            "returncode": run["returncode"],
            "converged": run["converged"],
            "elapsed_seconds": run["elapsed_seconds"],
            "bz_stats": bz_stats,
        },
        "warnings": [] if run["converged"] else ["Solver may not have printed 'ALL DONE' — check log_snippet"],
        "errors": [],
    }


@app.post("/elmer/setup_electrokinetics", tags=["Elmer"])
def elmer_setup_electrokinetics(req: ElmerElectrokineticsRequest):
    """
    Tutorial 25: Electrokinetic (electroosmotic) flow in a T-shaped microchannel.

    Couples three solvers every timestep:
      1. Electrostatics — DC electric potential in the fluid domain.
      2. Navier-Stokes  — incompressible flow with Helmholtz-Smoluchowski slip BC at walls.
      3. Advection-Diffusion — transport of a solute concentration plug.

    The electroosmotic wall slip is imposed via the Elmer built-in
    Procedure "Electrokinetics" "helmholtz_smoluchowski1/2".

    Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\Electrokinetics\\
    Default boundary tags: 1,5 = walls; 2 = inlet-A (100V); 3 = outlet-B (30V); 4 = outlet-C (0V).
    """
    import shutil as _shutil
    from pathlib import Path as _P
    import elmer_electrokinetics as ek

    if not ek.elmer_available():
        return {"success": False, "message": "ElmerSolver not found.",
                "data": {}, "warnings": [], "errors": ["ElmerSolver.exe missing"]}

    work = _P(req.working_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Copy mesh files
    src_dir = _P(req.mesh_source_dir) if req.mesh_source_dir else ek.TUTORIAL_MESH_DIR
    for f in src_dir.glob("mesh.*"):
        _shutil.copy2(f, work / f.name)

    # Write SIF
    sif_path = ek.write_sif(
        work,
        density=req.density,
        viscosity=req.viscosity,
        diffusivity=req.diffusivity,
        relative_permittivity=req.relative_permittivity,
        eo_mobility=req.eo_mobility,
        wall_tags=req.wall_tags,
        inlet_tag=req.inlet_tag,
        outlet_b_tag=req.outlet_b_tag,
        outlet_c_tag=req.outlet_c_tag,
        inlet_potential=req.inlet_potential,
        outlet_b_potential=req.outlet_b_potential,
        outlet_c_potential=req.outlet_c_potential,
        n_timesteps=req.n_timesteps,
        timestep_size=req.timestep_size,
        output_intervals=req.output_intervals,
        coordinate_scaling=req.coordinate_scaling,
    )
    ek.write_startinfo(work)

    # Run solver
    run = ek.run_solver(work, timeout=req.timeout_seconds)

    if run["returncode"] != 0:
        return {
            "success": False,
            "message": "ElmerSolver failed",
            "data": {
                "returncode": run["returncode"],
                "elapsed_seconds": run["elapsed_seconds"],
                "log_snippet": run["log_snippet"][-2000:],
            },
            "warnings": [],
            "errors": [run["log_snippet"][-2000:]],
        }

    # Parse field statistics
    field_stats = {}
    for field in ["Concentration", "Velocity 1", "Velocity 2", "Potential"]:
        try:
            field_stats[field] = ek.get_stats(work, field)
        except Exception as e:
            field_stats[field] = {"error": str(e)}

    conc_stats = field_stats.get("Concentration", {})
    max_conc = conc_stats.get("max_value", None)
    summary = f"Max concentration = {max_conc:.4f}" if max_conc is not None else "see field_stats"

    return {
        "success": True,
        "message": (
            f"Electrokinetics solved in {run['elapsed_seconds']:.1f}s. "
            f"{summary}. Converged: {run['converged']}"
        ),
        "data": {
            "sif_path": str(sif_path),
            "returncode": run["returncode"],
            "converged": run["converged"],
            "elapsed_seconds": run["elapsed_seconds"],
            "field_stats": field_stats,
        },
        "warnings": [] if run["converged"] else ["Solver may not have converged — check log"],
        "errors": [],
    }
